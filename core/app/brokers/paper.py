"""Courtier simulé : exécute au prix de marché réel, sans argent réel.

Deux frottements sont reproduits pour ne pas s'illusionner sur les
performances : un léger slippage sur le prix, et la **commission réelle** du
courtier visé (par défaut le barème Revolut Standard pour la crypto).
"""
from .base import BrokerAdapter, BrokerError, Fill
from .fees import NO_FEES, FeeSchedule

SLIPPAGE_PCT = 0.05  # 0,05 % défavorable sur chaque exécution


class PaperBroker(BrokerAdapter):
    name = "paper"
    is_paper = True

    def __init__(self, fees: FeeSchedule | None = None):
        self.fees = fees or NO_FEES

    def _fill(self, symbol: str, qty: float, price_hint: float, side: str) -> Fill:
        if price_hint <= 0:
            raise BrokerError(f"prix indisponible pour {symbol}")
        sign = 1 if side == "buy" else -1
        price = price_hint * (1 + sign * SLIPPAGE_PCT / 100)
        return Fill(
            price=round(price, 8),
            qty=qty,
            broker=self.name,
            is_paper=True,
            fee=self.fees.fee_for(price * qty),
        )

    def buy(self, symbol: str, qty: float, price_hint: float) -> Fill:
        return self._fill(symbol, qty, price_hint, "buy")

    def sell(self, symbol: str, qty: float, price_hint: float) -> Fill:
        return self._fill(symbol, qty, price_hint, "sell")
