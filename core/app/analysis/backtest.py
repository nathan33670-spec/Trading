"""Backtest du moteur technique — rejoue l'historique avec les VRAIES règles.

Mêmes détecteurs, mêmes stops, même stop suiveur et surtout **mêmes frais** que
le trading réel. Sert à deux choses :

  * vérifier qu'une modification des règles améliore ou dégrade la stratégie
    avant de la laisser tourner sur de l'argent, même fictif ;
  * donner un ordre de grandeur honnête dans l'app (onglet Marché), plutôt que
    de promettre des résultats.

Hypothèses volontairement pessimistes : entrée à l'ouverture de la bougie
suivante (pas au prix du signal), et si une bougie touche à la fois le stop et
l'objectif, on suppose que le **stop** a été touché en premier.
"""
from dataclasses import dataclass, field

from ..brokers.fees import REVOLUT_STANDARD, FeeSchedule
from .indicators import Candle
from .technical import MIN_CANDLES, read


@dataclass
class BacktestTrade:
    symbol: str
    entry_ts: int
    entry: float
    exit_ts: int
    exit: float
    qty: float
    reason: str
    pnl: float
    fees: float
    conviction: int


@dataclass
class BacktestResult:
    symbol: str
    candles: int
    trades: list[BacktestTrade] = field(default_factory=list)

    @property
    def net(self) -> float:
        return round(sum(t.pnl for t in self.trades), 2)

    @property
    def fees(self) -> float:
        return round(sum(t.fees for t in self.trades), 2)

    @property
    def gross(self) -> float:
        return round(self.net + self.fees, 2)

    @property
    def wins(self) -> int:
        return sum(1 for t in self.trades if t.pnl > 0)

    @property
    def win_rate(self) -> float:
        return round(self.wins / len(self.trades) * 100, 1) if self.trades else 0.0

    def summary(self) -> dict:
        return {
            "symbol": self.symbol,
            "candles": self.candles,
            "trades": len(self.trades),
            "win_rate": self.win_rate,
            "gross": self.gross,
            "fees": self.fees,
            "net": self.net,
            "avg_net": round(self.net / len(self.trades), 2) if self.trades else 0.0,
        }


def run(
    symbol: str,
    candles: list[Candle],
    *,
    stake: float = 1000.0,
    min_conviction: int = 62,
    fees: FeeSchedule = REVOLUT_STANDARD,
    cooldown_candles: int = 3,
    trailing: bool = True,
    trail_activate_r: float = 1.0,
    trail_distance_r: float = 1.0,
    timeframe: str = "4h",
) -> BacktestResult:
    """Rejoue l'historique avec une mise fixe par trade (pas de composition)."""
    result = BacktestResult(symbol=symbol, candles=len(candles))
    if len(candles) < MIN_CANDLES + 2:
        return result

    position: dict | None = None
    cooldown_until = 0

    for i in range(MIN_CANDLES, len(candles) - 1):
        candle = candles[i]

        # ── Gestion d'une position ouverte, bougie par bougie ────────────────
        if position:
            if candle.high > position["highest"]:
                position["highest"] = candle.high
            if trailing:
                r = position["entry"] - position["initial_stop"]
                if r > 0:
                    if not position["trail"] and candle.high >= position["entry"] + r * trail_activate_r:
                        position["trail"] = True
                        cushion = fees.round_trip_pct(position["entry"] * position["qty"]) / 100
                        position["stop"] = max(position["stop"], position["entry"] * (1 + cushion))
                    if position["trail"]:
                        position["stop"] = max(position["stop"], position["highest"] - r * trail_distance_r)

            exit_price = exit_reason = None
            if candle.low <= position["stop"]:          # pessimiste : stop d'abord
                exit_price, exit_reason = position["stop"], "trailing" if position["trail"] else "stop"
            elif candle.high >= position["target"]:
                exit_price, exit_reason = position["target"], "target"

            if exit_price:
                qty = position["qty"]
                exit_fee = fees.fee_for(exit_price * qty)
                total_fees = position["entry_fee"] + exit_fee
                result.trades.append(BacktestTrade(
                    symbol=symbol,
                    entry_ts=position["ts"], entry=position["entry"],
                    exit_ts=candle.ts, exit=exit_price, qty=qty, reason=exit_reason,
                    pnl=round((exit_price - position["entry"]) * qty - total_fees, 2),
                    fees=round(total_fees, 2),
                    conviction=position["conviction"],
                ))
                position = None
                cooldown_until = i + cooldown_candles
            continue

        if i < cooldown_until:
            continue

        # ── Recherche d'une entrée ───────────────────────────────────────────
        reading = read(symbol, candles[: i + 1], timeframe=timeframe, drop_forming=False)
        if not reading or not reading.signal or reading.signal.conviction < min_conviction:
            continue

        sig = reading.signal
        entry = candles[i + 1].open          # on entre à l'ouverture suivante
        if entry <= 0:
            continue
        qty = stake / entry
        stop = entry * (1 - sig.stop_pct / 100)
        target = entry * (1 + sig.target_pct / 100)
        entry_fee = fees.fee_for(entry * qty)

        # Même garde-fou qu'en production : l'objectif doit payer les frais
        if (target - entry) * qty < (entry_fee + fees.fee_for(target * qty)) * 2:
            continue

        position = {
            "ts": candles[i + 1].ts, "entry": entry, "qty": qty,
            "stop": stop, "initial_stop": stop, "target": target,
            "highest": entry, "trail": False, "entry_fee": entry_fee,
            "conviction": sig.conviction,
        }

    return result


def aggregate(results: list[BacktestResult]) -> dict:
    trades = [t for r in results for t in r.trades]
    net = round(sum(t.pnl for t in trades), 2)
    fees_total = round(sum(t.fees for t in trades), 2)
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    return {
        "symbols": len(results),
        "trades": len(trades),
        "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else 0.0,
        "gross": round(net + fees_total, 2),
        "fees": fees_total,
        "net": net,
        "avg_win": round(sum(t.pnl for t in wins) / len(wins), 2) if wins else 0.0,
        "avg_loss": round(sum(t.pnl for t in losses) / len(losses), 2) if losses else 0.0,
        "by_reason": {
            reason: sum(1 for t in trades if t.reason == reason)
            for reason in ("target", "trailing", "stop")
        },
        "per_symbol": [r.summary() for r in results],
    }
