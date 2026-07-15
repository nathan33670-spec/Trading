from app.risk.engine import PortfolioState, RiskLimits, evaluate, position_size


def state(**kw):
    defaults = dict(equity=10_000, cash=10_000)
    defaults.update(kw)
    return PortfolioState(**defaults)


def test_position_size_formula():
    # risque 1% de 10 000 € = 100 € ; stop à 2 € du prix → 50 unités
    assert position_size(10_000, 1.0, entry=100, stop=98) == 50


def test_position_size_invalid_inputs():
    assert position_size(10_000, 1.0, entry=100, stop=100) == 0
    assert position_size(0, 1.0, entry=100, stop=98) == 0
    assert position_size(10_000, 0, entry=100, stop=98) == 0


def _eval(**kw):
    defaults = dict(
        asset="AAPL",
        conviction=80,
        entry=100.0,
        stop=97.0,
        state=state(),
        limits=RiskLimits(),
    )
    defaults.update(kw)
    return evaluate(**defaults)


def test_nominal_approval_capped_by_exposure():
    d = _eval()
    assert d.approved
    # risque 1% = 100 €, stop à 3 € → 33,33 unités (3 333 €), mais le plafond
    # d'exposition par actif (20% de 10 000 € = 2 000 €) réduit à 20 unités
    assert abs(d.qty - 20.0) < 0.01
    assert abs(d.notional - 2_000) < 1


def test_nominal_approval_full_size():
    d = _eval(limits=RiskLimits(max_exposure_per_asset_pct=50))
    assert d.approved
    assert abs(d.qty - 100 / 3) < 0.01


def test_kill_switch_blocks_everything():
    d = _eval(limits=RiskLimits(kill_switch=True), conviction=100)
    assert not d.approved
    assert "kill-switch" in d.reason


def test_low_conviction_rejected():
    d = _eval(conviction=50)
    assert not d.approved


def test_max_positions_enforced():
    d = _eval(state=state(open_positions=5), limits=RiskLimits(max_positions=5))
    assert not d.approved


def test_daily_loss_limit_blocks():
    # perte du jour: -350 € sur 10 000 € avec limite à 3% (=-300 €)
    d = _eval(state=state(daily_pnl=-350))
    assert not d.approved
    assert "journalière" in d.reason


def test_weekly_loss_limit_blocks():
    d = _eval(state=state(weekly_pnl=-700))
    assert not d.approved
    assert "hebdo" in d.reason


def test_exposure_cap_reduces_position():
    # déjà 1 500 € sur AAPL, plafond 20% de 10 000 € = 2 000 € → il reste 500 €
    d = _eval(state=state(exposure_by_asset={"AAPL": 1_500}))
    assert d.approved
    assert d.notional <= 500.01


def test_exposure_cap_full_rejects():
    d = _eval(state=state(exposure_by_asset={"AAPL": 2_000}))
    assert not d.approved


def test_cash_cap():
    # cash très bas : la position est réduite au cash disponible
    d = _eval(state=state(cash=200))
    assert d.approved
    assert d.notional <= 200.01
