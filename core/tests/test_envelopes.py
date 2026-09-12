"""Enveloppes : la part du portefeuille engageable, au total et par classe."""
from app.brokers.fees import REVOLUT_STANDARD, FeeSchedule
from app.risk.engine import PortfolioState, RiskLimits, evaluate

GRATUIT = FeeSchedule("sans frais", 0.0, 0.0)


def _eval(**kw):
    defaults = dict(
        asset="BTC/EUR",
        asset_class="crypto",
        conviction=80,
        entry=100.0,
        stop=97.0,
        state=PortfolioState(equity=10_000, cash=10_000),
        limits=RiskLimits(max_exposure_per_asset_pct=100),
    )
    defaults.update(kw)
    return evaluate(**defaults)


def test_enveloppe_globale_reduit_la_position():
    # 55 % déjà investis, plafond global 60 % → il reste 500 €
    state = PortfolioState(equity=10_000, cash=10_000, invested=5_500)
    d = _eval(state=state, limits=RiskLimits(max_invested_pct=60, max_exposure_per_asset_pct=100))
    assert d.approved
    assert d.notional <= 500.01
    assert "enveloppe globale" in d.capped_by


def test_enveloppe_globale_saturee_refuse():
    state = PortfolioState(equity=10_000, cash=10_000, invested=6_000)
    d = _eval(state=state, limits=RiskLimits(max_invested_pct=60))
    assert not d.approved
    assert "enveloppe globale" in d.reason


def test_enveloppe_crypto_limite_la_classe():
    # 25 % de crypto déjà en portefeuille, enveloppe crypto 30 % → reste 500 €
    state = PortfolioState(equity=10_000, cash=10_000, invested=2_500,
                           exposure_by_class={"crypto": 2_500})
    d = _eval(state=state, limits=RiskLimits(
        envelope_pct={"crypto": 30.0}, max_exposure_per_asset_pct=100))
    assert d.approved
    assert d.notional <= 500.01
    assert "crypto" in d.capped_by


def test_enveloppe_crypto_saturee_refuse_mais_pas_les_actions():
    state = PortfolioState(equity=10_000, cash=10_000, invested=3_000,
                           exposure_by_class={"crypto": 3_000})
    limits = RiskLimits(envelope_pct={"crypto": 30.0, "stock": 40.0},
                        max_exposure_per_asset_pct=100)
    assert not _eval(state=state, limits=limits).approved
    # Le budget actions reste disponible
    d = _eval(state=state, limits=limits, asset="AAPL", asset_class="stock")
    assert d.approved


def test_classe_sans_enveloppe_nest_pas_bloquee():
    state = PortfolioState(equity=10_000, cash=10_000)
    d = _eval(state=state, asset_class="autre", limits=RiskLimits(
        envelope_pct={"crypto": 1.0}, max_exposure_per_asset_pct=100))
    assert d.approved


# ── Rentabilité nette de frais ───────────────────────────────────────────────

def test_objectif_trop_court_face_aux_frais_est_refuse():
    # Objectif +2 % alors que l'aller-retour Revolut coûte ~3 % : sans issue
    d = _eval(entry=100.0, stop=99.0, target=102.0, fees=REVOLUT_STANDARD,
              limits=RiskLimits(max_exposure_per_asset_pct=100, min_target_fee_ratio=3.0))
    assert not d.approved
    assert "frais" in d.reason


def test_objectif_large_est_accepte():
    d = _eval(entry=100.0, stop=97.0, target=115.0, fees=REVOLUT_STANDARD,
              limits=RiskLimits(max_exposure_per_asset_pct=100, min_target_fee_ratio=3.0))
    assert d.approved
    assert d.fees > 0


def test_sans_frais_le_controle_ne_bloque_pas():
    d = _eval(entry=100.0, stop=99.0, target=102.0, fees=GRATUIT,
              limits=RiskLimits(max_exposure_per_asset_pct=100))
    assert d.approved


def test_ratio_desactive_laisse_passer():
    d = _eval(entry=100.0, stop=99.0, target=102.0, fees=REVOLUT_STANDARD,
              limits=RiskLimits(max_exposure_per_asset_pct=100, min_target_fee_ratio=0))
    assert d.approved


def test_frais_estimes_sont_remontes():
    d = _eval(entry=100.0, stop=97.0, target=120.0, fees=REVOLUT_STANDARD,
              limits=RiskLimits(max_exposure_per_asset_pct=100))
    assert d.approved
    assert d.fees > 0  # aller-retour estimé, visible dans la traçabilité
