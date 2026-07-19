"""Moteur de risque — 100% déterministe, aucun LLM ici.

C'est LE garde-fou : quelle que soit la conviction du modèle, aucun ordre
ne part sans passer ces contrôles, et la taille de position est calculée
à partir du taux de risque défini par l'utilisateur.
"""
from dataclasses import dataclass, field


@dataclass
class PortfolioState:
    equity: float
    cash: float
    open_positions: int = 0
    # notionnel ouvert par actif, ex: {"AAPL": 1200.0}
    exposure_by_asset: dict[str, float] = field(default_factory=dict)
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


@dataclass
class RiskDecision:
    approved: bool
    reason: str = ""
    qty: float = 0.0
    notional: float = 0.0


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

    # Plafond d'exposition par actif
    max_asset_notional = state.equity * limits.max_exposure_per_asset_pct / 100.0
    already = state.exposure_by_asset.get(asset, 0.0)
    if already + notional > max_asset_notional:
        allowed = max_asset_notional - already
        if allowed <= 0:
            return RiskDecision(False, f"exposition max sur {asset} atteinte")
        qty = allowed / entry
        notional = qty * entry

    # On ne dépense jamais plus que le cash disponible.
    # Marge de 0,2 % pour absorber le slippage à l'exécution.
    available_cash = state.cash * 0.998
    if notional > available_cash:
        if available_cash <= 0:
            return RiskDecision(False, "cash insuffisant")
        qty = available_cash / entry
        notional = qty * entry

    # Garde-fou final : position trop petite pour être pertinente
    if notional < state.equity * 0.001:
        return RiskDecision(False, "position résiduelle trop petite")

    return RiskDecision(True, "ok", qty=round(qty, 8), notional=round(notional, 2))
