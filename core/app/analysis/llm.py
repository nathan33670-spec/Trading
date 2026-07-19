"""Fournisseurs LLM interchangeables — priorité au coût zéro.

Trois fournisseurs, essayés dans cet ordre pour l'analyse :

1. ``gemini``      — API Gemini avec le **quota gratuit** AI Studio
                     (secret ``google_api_key``, aucun paiement requis)
2. ``claude_cli``  — CLI Claude Code, **incluse dans l'abonnement Claude Pro/Max**
                     (secret ``claude_code_oauth_token``, généré par
                     ``claude setup-token`` sur n'importe quelle machine)
3. ``anthropic``   — API Anthropic classique (payante, purement optionnelle)

Le second avis utilise un fournisseur DIFFÉRENT de l'analyste ; s'il n'en
reste aucun, le signal n'est exécutable qu'au-dessus de ``solo_conviction``.
"""
import json
import logging
import os
import shutil
import subprocess

log = logging.getLogger(__name__)

PROVIDERS = ("gemini", "claude_cli", "anthropic")


def _secret(name: str) -> str:
    from ..secrets import get_secret

    return get_secret(name)


# ── Disponibilité ────────────────────────────────────────────────────────────

def _gemini_ok() -> bool:
    return bool(_secret("google_api_key"))


def _claude_cli_ok() -> bool:
    return bool(shutil.which("claude")) and bool(
        _secret("claude_code_oauth_token") or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    )


def _anthropic_ok() -> bool:
    return bool(_secret("anthropic_api_key"))


_AVAILABILITY = {"gemini": _gemini_ok, "claude_cli": _claude_cli_ok, "anthropic": _anthropic_ok}


# ── Générateurs (prompt → texte brut) ────────────────────────────────────────

def _gen_gemini(prompt: str) -> str:
    from google import genai

    from ..config import get_settings

    client = genai.Client(api_key=_secret("google_api_key"))
    resp = client.models.generate_content(
        model=get_settings().gemini_model,
        contents=prompt,
        config={"response_mime_type": "application/json"},
    )
    return resp.text or ""


def _gen_claude_cli(prompt: str) -> str:
    """Claude via la CLI Claude Code (couvert par l'abonnement Pro/Max)."""
    env = os.environ.copy()
    token = _secret("claude_code_oauth_token")
    if token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    result = subprocess.run(
        ["claude", "-p", "--model", "sonnet"],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=240,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI: {(result.stderr or result.stdout)[:300]}")
    return result.stdout


def _gen_anthropic(prompt: str) -> str:
    import anthropic

    from ..config import get_settings

    client = anthropic.Anthropic(api_key=_secret("anthropic_api_key"))
    resp = client.messages.create(
        model=get_settings().claude_model,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text


_GENERATORS = {"gemini": _gen_gemini, "claude_cli": _gen_claude_cli, "anthropic": _gen_anthropic}


# ── Génération avec repli ────────────────────────────────────────────────────

def extract_json(text: str) -> dict | None:
    """Extrait le premier objet JSON d'une réponse (tolère prose et ```fences```)."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def generate_text(prompt: str, exclude: tuple = ()) -> tuple[str, str]:
    """Essaie les fournisseurs dans l'ordre. Renvoie (texte, fournisseur) ou ("", "")."""
    for provider in PROVIDERS:
        if provider in exclude or not _AVAILABILITY[provider]():
            continue
        try:
            return _GENERATORS[provider](prompt), provider
        except Exception as exc:
            log.warning("Fournisseur %s en échec: %s", provider, exc)
    return "", ""


def generate_json(prompt: str, exclude: tuple = ()) -> tuple[dict | None, str]:
    """Comme generate_text mais parse le JSON ; passe au suivant si illisible."""
    for provider in PROVIDERS:
        if provider in exclude or not _AVAILABILITY[provider]():
            continue
        try:
            data = extract_json(_GENERATORS[provider](prompt))
            if data is not None:
                return data, provider
            log.warning("Fournisseur %s: réponse sans JSON exploitable", provider)
        except Exception as exc:
            log.warning("Fournisseur %s en échec: %s", provider, exc)
    return None, ""


# ── Prompts métier ───────────────────────────────────────────────────────────

ANALYST_PROMPT = """Tu es un analyste financier senior, spécialiste du trading événementiel (news-based).
On te fournit un lot d'actualités financières récentes. Ta mission :
1. Identifier les rares news réellement susceptibles de faire bouger un actif liquide à court terme
   (résultats surprises, M&A, décision réglementaire, incident majeur, décision de banque centrale...).
2. N'émettre un signal QUE si l'impact est direct, significatif et encore actionnable.
   La plupart des lots ne méritent AUCUN signal — c'est la réponse normale. Ne force jamais un trade.
3. Pour chaque signal : actif précis (ticker US ou paire crypto en EUR), sens, conviction honnête (0-100),
   distance de stop et d'objectif cohérentes avec la volatilité de l'actif.
Contraintes : positions longues uniquement (un signal "sell" sert à clôturer une position existante).
Pas d'actifs illiquides ni de penny stocks.

Actualités des dernières minutes :

{news}

Réponds UNIQUEMENT avec un objet JSON, sans aucun texte autour, au format exact :
{{"signals": [{{"asset": "AAPL ou BTC/EUR", "asset_class": "stock|etf|crypto", "direction": "buy|sell",
"conviction": 0-100, "horizon": "hours|days|weeks", "stop_pct": 1-10, "target_pct": 2-20,
"rationale": "justification en 1-2 phrases en français", "news_indexes": [0]}}]}}
S'il n'y a aucun signal pertinent : {{"signals": []}}"""


def _news_block(news: list[dict]) -> str:
    lines = []
    for i, n in enumerate(news):
        lines.append(f"[{i}] ({n['source']}) {n['title']}\n{(n.get('summary') or '')[:300]}")
    return "\n\n".join(lines)


def analyze_news(news: list[dict]) -> tuple[list[dict], str]:
    """Analyse un lot de news. Renvoie (signaux, fournisseur utilisé)."""
    data, provider = generate_json(ANALYST_PROMPT.format(news=_news_block(news)))
    if data is None:
        if provider == "":
            log.warning("Aucun fournisseur LLM disponible : analyse désactivée "
                        "(voir README, section coût zéro)")
        return [], ""
    signals = data.get("signals", [])
    if not isinstance(signals, list):
        signals = []
    log.info("Analyste (%s) a émis %d signal(aux) sur %d news", provider, len(signals), len(news))
    return signals, provider


SECOND_OPINION_PROMPT = """Tu es un gérant de risque sceptique. Un analyste propose ce trade suite à ces actualités.

Actualités :
{news}

Trade proposé : {direction} {asset} (conviction {conviction}/100) — {rationale}

Réponds UNIQUEMENT en JSON : {{"agree": true|false, "conviction": 0-100, "reason": "..."}}"""


def second_opinion(signal: dict, news: list[dict], exclude: tuple = ()) -> tuple[bool | None, int | None]:
    """Contre-expertise par un fournisseur différent de l'analyste. (None, None) si aucun."""
    related = [news[i] for i in signal.get("news_indexes", []) if 0 <= i < len(news)] or news
    prompt = SECOND_OPINION_PROMPT.format(
        news=_news_block(related),
        direction=signal.get("direction", "buy"),
        asset=signal.get("asset", "?"),
        conviction=signal.get("conviction", 0),
        rationale=signal.get("rationale", ""),
    )
    data, provider = generate_json(prompt, exclude=exclude)
    if data is None:
        return None, None
    log.info("Second avis (%s): agree=%s", provider, data.get("agree"))
    try:
        return bool(data.get("agree")), int(data.get("conviction", 0))
    except (TypeError, ValueError):
        return None, None


def write_commentary(stats: dict, kind: str) -> str:
    """Rédige le commentaire de synthèse hebdo/mensuelle (fallback : gabarit)."""
    fallback = (
        f"Période : {stats.get('trades', 0)} trades, "
        f"taux de réussite {stats.get('win_rate', 0):.0f} %, "
        f"P&L net {stats.get('pnl', 0):+.2f} €."
    )
    label = "hebdomadaire" if kind == "weekly" else "mensuelle"
    text, _ = generate_text(
        f"Rédige en français la synthèse {label} d'un bot de trading pour son propriétaire. "
        "Ton direct et factuel, 4-6 phrases : performance, ce qui a marché ou non, "
        "un conseil de prudence si pertinent. Réponds uniquement avec le texte de la synthèse.\n"
        f"Statistiques : {json.dumps(stats, default=str)}"
    )
    return text.strip() if text.strip() else fallback
