"""Clients LLM : Claude (analyste principal) et Gemini (second avis).

Claude reçoit un lot de news et rend des signaux structurés via tool-use
(sortie JSON stricte). Gemini contre-expertise chaque signal. Les deux
imports sont paresseux : l'application tourne sans les SDK en mode test.
"""
import json
import logging

log = logging.getLogger(__name__)

SIGNAL_TOOL = {
    "name": "emit_signals",
    "description": "Émet les signaux de trading déduits des actualités.",
    "input_schema": {
        "type": "object",
        "properties": {
            "signals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "asset": {
                            "type": "string",
                            "description": "Ticker US (ex: AAPL, SPY) ou paire crypto en EUR (ex: BTC/EUR)",
                        },
                        "asset_class": {"type": "string", "enum": ["stock", "etf", "crypto"]},
                        "direction": {"type": "string", "enum": ["buy", "sell"]},
                        "conviction": {"type": "integer", "minimum": 0, "maximum": 100},
                        "horizon": {"type": "string", "enum": ["hours", "days", "weeks"]},
                        "stop_pct": {"type": "number", "description": "Distance du stop en % (1-10)"},
                        "target_pct": {"type": "number", "description": "Distance de l'objectif en % (2-20)"},
                        "rationale": {"type": "string", "description": "Justification en 1-2 phrases, en français"},
                        "news_indexes": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "Index des news (dans le lot fourni) qui motivent ce signal",
                        },
                    },
                    "required": ["asset", "asset_class", "direction", "conviction", "rationale"],
                },
            }
        },
        "required": ["signals"],
    },
}

ANALYST_SYSTEM = """Tu es un analyste financier senior, spécialiste du trading événementiel (news-based).
On te fournit un lot d'actualités financières récentes. Ta mission :
1. Identifier les rares news réellement susceptibles de faire bouger un actif liquide à court terme
   (résultats surprises, M&A, décision réglementaire, incident majeur, décision de banque centrale...).
2. N'émettre un signal QUE si l'impact est direct, significatif et encore actionnable.
   La plupart des lots ne méritent AUCUN signal — c'est la réponse normale. Ne force jamais un trade.
3. Pour chaque signal : actif précis (ticker US ou paire crypto en EUR), sens, conviction honnête (0-100),
   distance de stop et d'objectif cohérentes avec la volatilité de l'actif.
Contraintes : positions longues uniquement (un signal "sell" sert à clôturer une position existante).
Pas d'actifs illiquides ni de penny stocks. Réponds exclusivement via l'outil emit_signals."""


def _news_block(news: list[dict]) -> str:
    lines = []
    for i, n in enumerate(news):
        lines.append(f"[{i}] ({n['source']}) {n['title']}\n{(n.get('summary') or '')[:300]}")
    return "\n\n".join(lines)


def analyze_news(news: list[dict]) -> list[dict]:
    """Envoie un lot de news à Claude, renvoie la liste de signaux (souvent vide)."""
    from ..config import get_settings
    from ..secrets import get_secret

    api_key = get_secret("anthropic_api_key")
    if not api_key:
        log.warning("anthropic_api_key manquante : analyse LLM désactivée")
        return []

    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    settings = get_settings()
    try:
        resp = client.messages.create(
            model=settings.claude_model,
            max_tokens=2000,
            system=ANALYST_SYSTEM,
            tools=[SIGNAL_TOOL],
            tool_choice={"type": "tool", "name": "emit_signals"},
            messages=[{"role": "user", "content": f"Actualités des dernières minutes :\n\n{_news_block(news)}"}],
        )
    except Exception as exc:
        log.error("Appel Claude échoué: %s", exc)
        return []

    for block in resp.content:
        if block.type == "tool_use" and block.name == "emit_signals":
            signals = block.input.get("signals", [])
            log.info("Claude a émis %d signal(aux) sur %d news", len(signals), len(news))
            return signals
    return []


def second_opinion(signal: dict, news: list[dict]) -> tuple[bool | None, int | None]:
    """Demande à Gemini s'il est d'accord avec le signal. (None, None) si indisponible."""
    from ..config import get_settings
    from ..secrets import get_secret

    api_key = get_secret("google_api_key")
    if not api_key:
        return None, None

    try:
        from google import genai

        client = genai.Client(api_key=api_key)
        related = [news[i] for i in signal.get("news_indexes", []) if 0 <= i < len(news)] or news
        prompt = (
            "Tu es un gérant de risque sceptique. Un analyste propose ce trade suite à ces actualités.\n\n"
            f"Actualités :\n{_news_block(related)}\n\n"
            f"Trade proposé : {signal['direction']} {signal['asset']} "
            f"(conviction {signal['conviction']}/100) — {signal.get('rationale', '')}\n\n"
            'Réponds UNIQUEMENT en JSON : {"agree": true|false, "conviction": 0-100, "reason": "..."}'
        )
        resp = client.models.generate_content(
            model=get_settings().gemini_model,
            contents=prompt,
            config={"response_mime_type": "application/json"},
        )
        data = json.loads(resp.text)
        return bool(data.get("agree")), int(data.get("conviction", 0))
    except Exception as exc:
        log.warning("Second avis Gemini indisponible: %s", exc)
        return None, None


def write_commentary(stats: dict, kind: str) -> str:
    """Rédige le commentaire de synthèse hebdo/mensuelle (fallback : gabarit)."""
    from ..config import get_settings
    from ..secrets import get_secret

    fallback = (
        f"Période : {stats.get('trades', 0)} trades, "
        f"taux de réussite {stats.get('win_rate', 0):.0f} %, "
        f"P&L net {stats.get('pnl', 0):+.2f} €."
    )
    api_key = get_secret("anthropic_api_key")
    if not api_key:
        return fallback
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        label = "hebdomadaire" if kind == "weekly" else "mensuelle"
        resp = client.messages.create(
            model=get_settings().claude_model,
            max_tokens=500,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Rédige en français la synthèse {label} d'un bot de trading pour son propriétaire. "
                        "Ton direct et factuel, 4-6 phrases : performance, ce qui a marché ou non, "
                        f"un conseil de prudence si pertinent.\nStatistiques : {json.dumps(stats, default=str)}"
                    ),
                }
            ],
        )
        return resp.content[0].text.strip()
    except Exception as exc:
        log.warning("Commentaire Claude indisponible: %s", exc)
        return fallback
