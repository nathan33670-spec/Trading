"""Adaptateur Kraken (crypto) via ccxt — utilisé seulement si live_kraken=True.

Secrets requis : kraken_api_key, kraken_api_secret.
"""
from .base import BrokerAdapter, BrokerError, Fill


class KrakenBroker(BrokerAdapter):
    name = "kraken"
    is_paper = False

    def __init__(self):
        import ccxt  # import paresseux : non requis en mode paper

        from ..secrets import get_secret

        key = get_secret("kraken_api_key")
        secret = get_secret("kraken_api_secret")
        if not key or not secret:
            raise BrokerError("kraken_api_key / kraken_api_secret manquants")
        self._x = ccxt.kraken({"apiKey": key, "secret": secret})

    def _order(self, side: str, symbol: str, qty: float) -> Fill:
        try:
            order = self._x.create_order(symbol, "market", side, qty)
            filled = self._x.fetch_order(order["id"], symbol)
            price = float(filled.get("average") or filled.get("price") or 0)
            amount = float(filled.get("filled") or qty)
            if price <= 0:
                raise BrokerError(f"ordre {side} {symbol}: prix d'exécution inconnu")
            return Fill(price=price, qty=amount, broker=self.name, is_paper=False)
        except BrokerError:
            raise
        except Exception as exc:
            raise BrokerError(f"Kraken {side} {symbol}: {exc}") from exc

    def buy(self, symbol: str, qty: float, price_hint: float) -> Fill:
        return self._order("buy", symbol, qty)

    def sell(self, symbol: str, qty: float, price_hint: float) -> Fill:
        return self._order("sell", symbol, qty)
