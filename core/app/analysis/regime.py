"""Stratégie de régime — momentum 12 mois, tout ou rien.

## Pourquoi celle-ci

Ce moteur remplace une première tentative de swing trading (cassures, replis,
objectifs à 2R) qui perdait de l'argent de façon mesurable. Le diagnostic, tiré
d'un backtest sur 10 ans de BTC/EUR et de quatre sous-périodes :

* un aller-retour coûte ~3 % (Revolut Standard) : toute stratégie qui trade
  souvent part avec un handicap insurmontable ;
* les objectifs fixes plafonnent les gagnants à 2R alors que les tendances
  crypto courent sur 5 à 20R — or il faut ces quelques trades énormes pour
  compenser les nombreux petits perdants ;
* les signaux rapides (EMA21, SMA50) sont détruits par les faux signaux.

Le signal retenu est le plus simple et le plus documenté de la finance
quantitative (momentum 12 mois, cf. Jegadeesh & Titman, Faber, Antonacci) :

    **investir si le prix est au-dessus de son niveau d'il y a 12 mois,
    rester en cash sinon.**

## Ce que ça donne (BTC/EUR, frais Revolut inclus)

| Période                  | CAGR   | Drawdown max | Mouvements |
|--------------------------|--------|--------------|------------|
| 2016-2026 (10,4 ans)     | 51,4 % | 79,3 %       | 12         |
| 2018-2026                | 34,9 % | 61,7 %       | 10         |
| 2021-2026 *(validation)* | 16,6 % | 34,1 %       | 6          |
| 2022-2026                | 31,5 % | 31,9 %       | 2          |

Positif sur chaque période, avec un drawdown environ deux fois plus faible que
l'achat-conservation. Ce n'est pas une promesse de gain : c'est une exposition
longue au marché, filtrée. Si la crypto baisse durablement, le filtre limite la
casse mais ne crée pas de profit.

## Points d'attention

* **Ne fonctionne bien que sur BTC** (et, moins nettement, ETH). Testé sur XRP,
  LTC, LINK, ADA, le même filtre détruit le capital : leurs hausses sont trop
  brèves pour un signal à 12 mois.
* **Pas de stop serré.** Le stop est un garde-fou catastrophe très éloigné ; la
  sortie se fait sur le signal. Un stop serré ramènerait les défauts du swing.
* **Vérification hebdomadaire, pas quotidienne.** Détail décisif mesuré au
  backtest : contrôler le signal chaque jour produit 32 mouvements sur 10 ans
  (bruit de bord autour du seuil), contre 12 en le contrôlant une fois par
  semaine — pour un rendement supérieur et un drawdown plus faible.
"""
import logging
from dataclasses import dataclass, field

from .indicators import Candle, sma

log = logging.getLogger(__name__)

# Actifs sur lesquels le momentum 12 mois est validé par le backtest.
DEFAULT_ASSETS = ["BTC/EUR"]

# Le filtre n'améliore le résultat que sur ces actifs. Testé sur 11 autres
# (S&P 500, Nasdaq, Apple, Microsoft, or, argent, pétrole, cuivre, gaz, maïs,
# 20 ans de données) : il ne bat l'achat-conservation sur aucun — voir README.
VALIDATED_ASSETS = {"BTC/EUR", "ETH/EUR"}


def validation_note(symbol: str) -> str:
    """Avertissement affiché pour un actif hors périmètre validé."""
    symbol = symbol.upper()
    if symbol == "BTC/EUR":
        return ""
    if symbol == "ETH/EUR":
        return ("ETH : le filtre bat l'achat-conservation sur les périodes récentes "
                "et réduit le drawdown, mais l'actif lui-même stagne (-0,9 %/an sur 5 ans).")
    return ("actif hors périmètre validé : le momentum 12 mois n'a amélioré le "
            "rendement sur aucun actif testé hors BTC/ETH (actions, indices, or, "
            "argent, pétrole, cuivre, gaz, maïs). À vos risques.")

# Stop catastrophe : uniquement pour couvrir un effondrement brutal entre deux
# vérifications quotidiennes. La sortie normale passe par le signal.
CATASTROPHE_STOP_PCT = 50.0


@dataclass
class RegimeReading:
    symbol: str
    price: float
    invested: bool          # le signal dit-il d'être investi ?
    momentum_pct: float | None
    reference_price: float | None
    above_sma: bool | None
    reason: str
    markers: list = field(default_factory=list)


def evaluate_regime(
    symbol: str,
    candles: list[Candle],
    momentum_days: int = 365,
    confirm_sma: int = 0,
) -> RegimeReading | None:
    """Le signal du jour pour une paire. None si l'historique est trop court.

    `confirm_sma` > 0 exige en plus que le prix soit au-dessus de cette moyenne
    mobile (plus prudent, mais le backtest montre que ça réduit le rendement :
    désactivé par défaut).
    """
    if len(candles) < momentum_days + 2:
        return None

    closes = [c.close for c in candles]
    price = closes[-1]
    reference = closes[-1 - momentum_days]
    if price <= 0 or reference <= 0:
        return None

    momentum_pct = (price / reference - 1) * 100
    invested = momentum_pct > 0

    above_sma = None
    if confirm_sma:
        series = sma(closes, confirm_sma)
        if series[-1] is not None:
            above_sma = price > series[-1]
            invested = invested and above_sma

    markers = [{
        "code": "momentum",
        "label": f"prix {'au-dessus' if momentum_pct > 0 else 'en dessous'} de son niveau "
                 f"d'il y a {momentum_days // 30} mois ({momentum_pct:+.1f} %)",
        "score": 1 if momentum_pct > 0 else -1,
        "primary": True,
    }]
    if above_sma is not None:
        markers.append({
            "code": "sma",
            "label": f"prix {'au-dessus de' if above_sma else 'sous'} la SMA{confirm_sma}",
            "score": 1 if above_sma else -1,
            "primary": False,
        })

    if invested:
        reason = f"tendance de fond haussière ({momentum_pct:+.1f} % sur 12 mois) → investi"
    elif momentum_pct <= 0:
        reason = f"tendance de fond baissière ({momentum_pct:+.1f} % sur 12 mois) → hors marché"
    else:
        reason = f"momentum positif mais prix sous la SMA{confirm_sma} → hors marché"

    return RegimeReading(
        symbol=symbol,
        price=price,
        invested=invested,
        momentum_pct=round(momentum_pct, 2),
        reference_price=round(reference, 8),
        above_sma=above_sma,
        reason=reason,
        markers=markers,
    )


# ── Backtest de la stratégie ─────────────────────────────────────────────────

@dataclass
class RegimeBacktest:
    symbol: str
    start_equity: float
    equity: float
    trades: int
    fees: float
    max_drawdown: float
    years: float
    exposure: float
    buy_hold_equity: float
    buy_hold_drawdown: float

    @property
    def cagr(self) -> float:
        if self.years <= 0 or self.equity <= 0 or self.start_equity <= 0:
            return -100.0
        return round(((self.equity / self.start_equity) ** (1 / self.years) - 1) * 100, 1)

    @property
    def buy_hold_cagr(self) -> float:
        if self.years <= 0 or self.buy_hold_equity <= 0:
            return -100.0
        return round(((self.buy_hold_equity / self.start_equity) ** (1 / self.years) - 1) * 100, 1)

    def summary(self) -> dict:
        return {
            "symbol": self.symbol,
            "start_equity": round(self.start_equity, 2),
            "equity": round(self.equity, 2),
            "cagr": self.cagr,
            "max_drawdown": round(self.max_drawdown, 1),
            "trades": self.trades,
            "fees": round(self.fees, 2),
            "years": round(self.years, 1),
            "exposure": round(self.exposure * 100, 1),
            "buy_hold_equity": round(self.buy_hold_equity, 2),
            "buy_hold_cagr": self.buy_hold_cagr,
            "buy_hold_drawdown": round(self.buy_hold_drawdown, 1),
        }


def backtest(
    symbol: str,
    candles: list[Candle],
    fees,
    *,
    start_equity: float = 10_000.0,
    momentum_days: int = 365,
    confirm_sma: int = 0,
    check_every_days: int = 7,
) -> RegimeBacktest | None:
    """Rejoue la stratégie, capital composé, frais réels.

    Décision à la clôture de J, exécution à l'ouverture de J+1 — on ne peut pas
    agir sur un prix qu'on ne connaît pas encore.
    """
    warmup = momentum_days + 2
    if len(candles) < warmup + 30:
        return None

    closes = [c.close for c in candles]
    sma_series = sma(closes, confirm_sma) if confirm_sma else None

    cash, units = start_equity, 0.0
    trades = 0
    fees_paid = 0.0
    peak = start_equity
    max_dd = 0.0
    invested_days = 0

    for i in range(warmup, len(candles) - 1):
        reference = closes[i - momentum_days]
        want = reference > 0 and closes[i] > reference
        if want and sma_series is not None:
            want = sma_series[i] is not None and closes[i] > sma_series[i]

        # Le signal n'est consulté qu'un jour sur `check_every_days` : le
        # contrôler quotidiennement multiplie les allers-retours sans gain.
        due = (i - warmup) % max(check_every_days, 1) == 0
        entry_price = candles[i + 1].open
        if due and entry_price > 0:
            if want and units == 0.0 and cash > 0:
                fee = fees.fee_for(cash)
                spend = cash - fee
                if spend > 0:
                    units = spend / entry_price
                    cash = 0.0
                    fees_paid += fee
                    trades += 1
            elif not want and units > 0.0:
                gross = units * entry_price
                fee = fees.fee_for(gross)
                cash = gross - fee
                units = 0.0
                fees_paid += fee
                trades += 1

        value = cash + units * candles[i + 1].close
        if units > 0:
            invested_days += 1
        peak = max(peak, value)
        if peak > 0:
            max_dd = max(max_dd, (peak - value) / peak * 100)

    equity = cash + units * closes[-1]
    span_days = max(len(candles) - warmup, 1)
    years = span_days / 365.25

    # Référence : acheter au même moment et ne rien faire
    bh_units = (start_equity - fees.fee_for(start_equity)) / candles[warmup].open
    bh_peak, bh_dd = start_equity, 0.0
    for i in range(warmup, len(candles)):
        v = bh_units * candles[i].close
        bh_peak = max(bh_peak, v)
        if bh_peak > 0:
            bh_dd = max(bh_dd, (bh_peak - v) / bh_peak * 100)

    return RegimeBacktest(
        symbol=symbol,
        start_equity=start_equity,
        equity=equity,
        trades=trades,
        fees=fees_paid,
        max_drawdown=max_dd,
        years=years,
        exposure=invested_days / span_days,
        buy_hold_equity=bh_units * closes[-1],
        buy_hold_drawdown=bh_dd,
    )
