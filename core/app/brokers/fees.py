"""Frais de transaction — appliqués aussi en paper trading.

Sans frais, le paper trading ment : une stratégie qui vise +2 % paraît gagnante
alors qu'un aller-retour Revolut en coûte ~3 %. Ici, chaque ordre simulé paie
la même commission qu'en réel, et le P&L affiché est net.

Barème crypto par défaut : **Revolut, compte Standard** — 1,49 % par
transaction avec un plancher de 0,99 €. Les barèmes évoluent : les deux valeurs
sont modifiables dans Réglages → Enveloppes & frais, sans redéploiement.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class FeeSchedule:
    """Commission d'un ordre : pourcentage du notionnel, avec un plancher."""

    name: str
    pct: float = 0.0
    minimum: float = 0.0

    def fee_for(self, notional: float) -> float:
        if notional <= 0:
            return 0.0
        return round(max(notional * self.pct / 100.0, self.minimum), 4)

    def round_trip_pct(self, notional: float) -> float:
        """Coût aller-retour en % du notionnel — ce qu'il faut battre pour gagner."""
        if notional <= 0:
            return 0.0
        return (self.fee_for(notional) * 2) / notional * 100.0


# Barèmes de référence (vérifiez-les chez votre courtier, ils changent)
REVOLUT_STANDARD = FeeSchedule("revolut_standard", pct=1.49, minimum=0.99)
KRAKEN_TAKER = FeeSchedule("kraken", pct=0.26, minimum=0.0)
TRADING212 = FeeSchedule("trading212", pct=0.15, minimum=0.0)  # change de devise
NO_FEES = FeeSchedule("sans frais", pct=0.0, minimum=0.0)


def schedule_for(asset_class: str, cfg=None) -> FeeSchedule:
    """Barème applicable à une classe d'actif, d'après la configuration."""
    if cfg is None:
        return REVOLUT_STANDARD if asset_class == "crypto" else TRADING212
    if asset_class == "crypto":
        return FeeSchedule("crypto", pct=cfg.fee_crypto_pct, minimum=cfg.fee_crypto_min)
    return FeeSchedule("actions", pct=cfg.fee_stock_pct, minimum=cfg.fee_stock_min)
