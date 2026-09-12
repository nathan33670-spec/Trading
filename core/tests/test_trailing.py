"""Stop suiveur et P&L net de frais — la gestion de position après l'entrée."""
from app.db.models import AssetClass, RiskConfig, Trade, TradeStatus
from app.portfolio.service import close_trade, update_trailing_stop


def cfg(**kw) -> RiskConfig:
    c = RiskConfig(id=1, trailing_enabled=True, trail_activate_r=2.0, trail_distance_r=1.5,
                   fee_crypto_pct=1.49, fee_crypto_min=0.99)
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def trade(**kw) -> Trade:
    t = Trade(
        broker="paper", is_paper=True, symbol="BTC/EUR", asset_class=AssetClass.crypto,
        side="buy", qty=1.0, entry_price=100.0, stop_price=90.0, initial_stop=90.0,
        target_price=130.0, highest_price=100.0, entry_fee=1.49, status=TradeStatus.open,
    )
    for k, v in kw.items():
        setattr(t, k, v)
    return t


def test_pas_de_mouvement_avant_le_seuil():
    t = trade()
    # +1R seulement (110) alors que le déclenchement est à +2R
    assert update_trailing_stop(t, 110.0, cfg()) is False
    assert t.stop_price == 90.0
    assert not t.trail_active   # None avant insertion en base, False ensuite


def test_activation_a_2R_remonte_au_point_mort():
    t = trade()
    assert update_trailing_stop(t, 120.0, cfg()) is True
    assert t.trail_active is True
    # Point mort frais compris : au-dessus du prix d'entrée
    assert t.stop_price > t.entry_price


def test_suivi_du_plus_haut_apres_activation():
    t = trade()
    update_trailing_stop(t, 120.0, cfg())
    t.highest_price = 150.0
    update_trailing_stop(t, 150.0, cfg())
    # stop = plus haut - 1,5R = 150 - 15 = 135
    assert abs(t.stop_price - 135.0) < 0.01


def test_le_stop_ne_redescend_jamais():
    t = trade()
    update_trailing_stop(t, 120.0, cfg())
    t.highest_price = 150.0
    update_trailing_stop(t, 150.0, cfg())
    haut = t.stop_price
    update_trailing_stop(t, 105.0, cfg())  # le prix rechute
    assert t.stop_price == haut


def test_desactive_ne_touche_a_rien():
    t = trade()
    assert update_trailing_stop(t, 200.0, cfg(trailing_enabled=False)) is False
    assert t.stop_price == 90.0


def test_stop_initial_incoherent_ignore():
    t = trade(initial_stop=0.0)
    assert update_trailing_stop(t, 200.0, cfg()) is False


# ── P&L net ──────────────────────────────────────────────────────────────────

def test_pnl_est_net_de_frais(db, monkeypatch):
    import app.portfolio.service as service

    monkeypatch.setattr(service, "notify_trade_closed", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(service, "_broadcast", lambda *a, **k: None)
    db.add(RiskConfig(id=1, fee_crypto_pct=1.49, fee_crypto_min=0.99))
    t = trade(qty=1.0, entry_price=100.0, entry_fee=1.49)
    db.add(t)
    db.commit()

    close_trade(db, t, price=110.0, reason="target")

    assert t.status == TradeStatus.closed
    # Brut ≈ +10 € (moins le slippage), frais ≈ 1,49 + 1,64 → net nettement < 10
    assert t.pnl < 10.0
    assert t.exit_fee > 0
    assert t.pnl_pct < 10.0


def test_trade_gagnant_de_peu_devient_perdant_avec_les_frais(db, monkeypatch):
    """Un +2 % brut ne survit pas à un aller-retour Revolut (~3 %)."""
    import app.portfolio.service as service

    monkeypatch.setattr(service, "notify_trade_closed", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(service, "_broadcast", lambda *a, **k: None)
    db.add(RiskConfig(id=1, fee_crypto_pct=1.49, fee_crypto_min=0.99))
    t = trade(qty=10.0, entry_price=100.0, entry_fee=14.9)
    db.add(t)
    db.commit()

    close_trade(db, t, price=102.0, reason="target")
    assert t.pnl < 0
