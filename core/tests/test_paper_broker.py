import pytest

from app.brokers.base import BrokerError
from app.brokers.paper import PaperBroker


def test_buy_applies_adverse_slippage():
    fill = PaperBroker().buy("BTC/EUR", qty=0.1, price_hint=50_000)
    assert fill.price > 50_000
    assert fill.is_paper


def test_sell_applies_adverse_slippage():
    fill = PaperBroker().sell("BTC/EUR", qty=0.1, price_hint=50_000)
    assert fill.price < 50_000


def test_no_price_raises():
    with pytest.raises(BrokerError):
        PaperBroker().buy("AAPL", qty=1, price_hint=0)
