"""Moteur de risque — 100% déterministe, aucun LLM ici.

C'est LE garde-fou : quelle que soit la conviction du modèle, aucun ordre
ne part sans passer ces contrôles, et la taille de position est calculée
à partir du taux de risque défini par l'utilisateur.

Trois familles de contrôles :
  1. blocages absolus (kill-switch, pertes max, conviction, capital) ;
  2. **enveloppes** — part maximale du portefeuille engageable au total et par
     classe d'actif : elles réduisent la position au lieu de la refuser ;
  3. rentabilité nette de frais — une position dont l'objectif ne couvre pas
     plusieurs fois l'aller-retour de commissions n'a pas d'espérance positive.
"""
from dataclasses import dataclass, field


def _default_envelopes() -> dict[str, float]:
    return {"crypto": 30.0, "stock": 40.0, "etf": 40.0}


@dataclass
class PortfolioState:
    equity: float
    cash: float
    open_positions: int = 0
    # notionnel ouvert par actif, ex: {"AAPL": 1200.0}
    exposure_by_asset: dict[str, float] = field(default_factory=dict)
    # notionnel ouvert par classe d'actif, ex: {"crypto": 800.0}
    exposure_by_class: dict[str, float] = field(default_factory=dict)
    invested: float = 0.0
    daily_pnl: float = 0.0
    weekly_pnl: float = 0.0


@dataclass
class RiskLimits:
    risk_per_trade_pct: float = 1.0
    max_daily_loss_pct: float = 3.0
    max_weekly_loss_pct: float = 6.0
    max_positions: int = 5
    max_exposure_per_asset_pct: float = 20.0
    min_conviction: int = 65
    kill_switch: bool = False
    # Enveloppes
    max_invested_pct: float = 60.0
    envelope_pct: dict[str, float] = field(default_factory=_default_envelopes)
    # L'objectif doit valoir au moins N fois les frais d'aller-retour
    min_target_fee_ratio: float = 3.0


@dataclass
class RiskDecision:
    approved: bool
    reason: str = ""
    qty: float = 0.0
    notional: float = 0.0
    fees: float = 0.0          # aller-retour estimé
    capped_by: str = ""        # quelle contrainte a réduit la position


def position_size(equity: float, risk_pct: float, entry: float, stop: float) -> float:
    """Quantité telle que la perte au stop == equity * risk_pct.

    taille = (capital × risque%) / distance_au_stop
    """
    dist = abs(entry - stop)
    if dist <= 0 or entry <= 0 or equity <= 0 or risk_pct <= 0:
        return 0.0
    return (equity * risk_pct / 100.0) / dist


def evaluate(
    *,
    asset: str,
    conviction: int,
    entry: float,
    stop: float,
    state: PortfolioState,
    limits: RiskLimits,
    asset_class: str = "stock",
    target: float | None = None,
    fees=None,
) -> RiskDecision:
    if limits.kill_switch:
        return RiskDecision(False, "kill-switch actif")

    if conviction < limits.min_conviction:
        return RiskDecision(False, f"conviction {conviction} < seuil {limits.min_conviction}")

    if state.open_positions >= limits.max_positions:
        return RiskDecision(False, f"nombre max de positions atteint ({limits.max_positions})")

    if state.equity <= 0:
        return RiskDecision(False, "capital épuisé")

    daily_limit = -state.equity * limits.max_daily_loss_pct / 100.0
    if state.daily_pnl <= daily_limit:
        return RiskDecision(False, "perte max journalière atteinte")

    weekly_limit = -state.equity * limits.max_weekly_loss_pct / 100.0
    if state.weekly_pnl <= weekly_limit:
        return RiskDecision(False, "perte max hebdomadaire atteinte (kill-switch hebdo)")

    qty = position_size(state.equity, limits.risk_per_trade_pct, entry, stop)
    if qty <= 0:
        return RiskDecision(False, "taille de position invalide (stop trop proche ?)")

    notional = qty * entry
    capped_by = ""

    def cap(room: float, label: str) -> str | None:
        """Réduit la position à `room` ; renvoie un motif de refus si nul."""
        nonlocal qty, notional, capped_by
        if notional <= room:
            return None
        if room <= 0:
            return label
        qty = room / entry
        notional = qty * entry
        capped_by = label
        return None

    # Enveloppe globale : part maximale du portefeuille jamais dépassée
    refusal = cap(
        state.equity * limits.max_invested_pct / 100.0 - state.invested,
        f"enveloppe globale atteinte ({limits.max_invested_pct:g} % du portefeuille)",
    )
    if refusal:
        return RiskDecision(False, refusal)

    # Enveloppe de la classe d'actif (crypto / actions / ETF)
    env_pct = limits.envelope_pct.get(asset_class)
    if env_pct is not None:
        refusal = cap(
            state.equity * env_pct / 100.0 - state.exposure_by_class.get(asset_class, 0.0),
            f"enveloppe {asset_class} atteinte ({env_pct:g} % du portefeuille)",
        )
        if refusal:
            return RiskDecision(False, refusal)

    # Plafond d'exposition par actif
    refusal = cap(
        state.equity * limits.max_exposure_per_asset_pct / 100.0
        - state.exposure_by_asset.get(asset, 0.0),
        f"exposition max sur {asset} atteinte",
    )
    if refusal:
        return RiskDecision(False, refusal)

    # On ne dépense jamais plus que le cash disponible.
    # Marge de 0,2 % pour absorber le slippage à l'exécution.
    refusal = cap(state.cash * 0.998, "cash insuffisant")
    if refusal:
        return RiskDecision(False, refusal)

    # Garde-fou final : position trop petite pour être pertinente
    if notional < state.equity * 0.001:
        return RiskDecision(False, "position résiduelle trop petite")

    # Rentabilité nette de frais : l'objectif doit valoir plusieurs fois
    # l'aller-retour de commissions, sinon le courtier est seul gagnant.
    round_trip = 0.0
    if fees is not None:
        exit_notional = (target or entry) * qty
        round_trip = fees.fee_for(notional) + fees.fee_for(exit_notional)
        if target is not None and limits.min_target_fee_ratio > 0:
            expected_gain = (target - entry) * qty
            if expected_gain < round_trip * limits.min_target_fee_ratio:
                return RiskDecision(
                    False,
                    f"gain visé ({expected_gain:.2f} €) trop faible face aux frais "
                    f"({round_trip:.2f} € aller-retour) — position trop petite ou objectif trop court",
                )

    return RiskDecision(
        True, "ok",
        qty=round(qty, 8),
        notional=round(notional, 2),
        fees=round(round_trip, 2),
        capped_by=capped_by,
    )
