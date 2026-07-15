"""Courtier simulé : exécute au prix de marché réel, sans argent réel.

On applique un léger slippage pour ne pas s'illusionner sur les performances.
"""
from .base import BrokerAdapter, BrokerError, Fill

SLIPPAGE_PCT = 0.05  # 0,05 % défavorable sur chaque exécution


class PaperBroker(BrokerAdapter):
    name = "paper"
    is_paper = True

    def buy(self, symbol: str, qty: float, price_hint: float) -> Fill:
        if price_hint <= 0:
            raise BrokerError(f"prix indisponible pour {symbol}")
        price = price_hint * (1 + SLIPPAGE_PCT / 100)
        return Fill(price=round(price, 8), qty=qty, broker=self.name, is_paper=True)

    def sell(self, symbol: str, qty: float, price_hint: float) -> Fill:
        if price_hint <= 0:
            raise BrokerError(f"prix indisponible pour {symbol}")
        price = price_hint * (1 - SLIPPAGE_PCT / 100)
        return Fill(price=round(price, 8), qty=qty, broker=self.name, is_paper=True)
