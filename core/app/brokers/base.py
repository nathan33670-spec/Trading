"""Interface commune des courtiers.

Tous les adaptateurs (paper, Trading212, Kraken) implémentent cette interface,
ce qui permet de basculer paper → réel, ou de changer de courtier, sans toucher
au reste de l'application.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Fill:
    """Résultat d'un ordre exécuté."""

    price: float
    qty: float
    broker: str
    is_paper: bool
    fee: float = 0.0   # commission prélevée par le courtier, en devise de base


class BrokerAdapter(ABC):
    name: str = "abstract"
    is_paper: bool = True

    @abstractmethod
    def buy(self, symbol: str, qty: float, price_hint: float) -> Fill:
        """Achat au marché. Lève BrokerError en cas d'échec."""

    @abstractmethod
    def sell(self, symbol: str, qty: float, price_hint: float) -> Fill:
        """Vente au marché (clôture de position). Lève BrokerError en cas d'échec."""


class BrokerError(RuntimeError):
    pass
