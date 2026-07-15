"""Adaptateur Trading212 (actions/ETF) — utilisé seulement si live_trading212=True.

API officielle : https://t212public-api-docs.redoc.ly/
La clé (secret `trading212_api_key`) peut être générée pour le compte Practice
(démo) ou Invest (réel) — l'URL change selon le mode via T212_ENV.
"""
import os
import time

import httpx

from .base import BrokerAdapter, BrokerError, Fill

BASE_URLS = {
    "demo": "https://demo.trading212.com/api/v0",
    "live": "https://live.trading212.com/api/v0",
}


class Trading212Broker(BrokerAdapter):
    name = "trading212"

    def __init__(self):
        from ..secrets import get_secret

        key = get_secret("trading212_api_key")
        if not key:
            raise BrokerError("trading212_api_key manquante")
        env = os.environ.get("T212_ENV", "demo")
        self.is_paper = env == "demo"
        self._base = BASE_URLS.get(env, BASE_URLS["demo"])
        self._headers = {"Authorization": key}

    def _market_order(self, symbol: str, qty: float) -> Fill:
        # Trading212 : quantité signée (négatif = vente)
        try:
            resp = httpx.post(
                f"{self._base}/equity/orders/market",
                headers=self._headers,
                json={"ticker": symbol, "quantity": qty},
                timeout=20,
            )
            resp.raise_for_status()
            order = resp.json()
            # L'exécution est asynchrone : on interroge l'ordre quelques secondes
            for _ in range(10):
                st = httpx.get(
                    f"{self._base}/equity/orders/{order['id']}",
                    headers=self._headers,
                    timeout=20,
                ).json()
                if st.get("status") in ("FILLED",):
                    price = float(st.get("filledValue", 0)) / max(abs(float(st.get("filledQuantity", 1))), 1e-9)
                    return Fill(price=price, qty=abs(qty), broker=self.name, is_paper=self.is_paper)
                if st.get("status") in ("REJECTED", "CANCELLED"):
                    raise BrokerError(f"ordre Trading212 {st.get('status')}")
                time.sleep(1)
            raise BrokerError("ordre Trading212 non exécuté après 10s")
        except BrokerError:
            raise
        except Exception as exc:
            raise BrokerError(f"Trading212 {symbol}: {exc}") from exc

    def buy(self, symbol: str, qty: float, price_hint: float) -> Fill:
        return self._market_order(symbol, qty)

    def sell(self, symbol: str, qty: float, price_hint: float) -> Fill:
        return self._market_order(symbol, -qty)
