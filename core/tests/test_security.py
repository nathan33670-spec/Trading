import pytest
from fastapi import HTTPException

from app import security


class FakeTime:
    now = 1000.0

    @classmethod
    def monotonic(cls):
        return cls.now


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    security._failures.clear()
    security._locked_until.clear()
    FakeTime.now = 1000.0
    monkeypatch.setattr(security, "time", FakeTime)


def test_tokens_match():
    assert security.tokens_match("abc", "abc")
    assert not security.tokens_match("abc", "abd")
    assert not security.tokens_match("", "")
    assert not security.tokens_match("abc", "")


def test_verrouillage_apres_5_echecs():
    for _ in range(security.MAX_FAILURES):
        security.check_not_locked("1.2.3.4")
        security.record_failure("1.2.3.4")
    with pytest.raises(HTTPException) as exc:
        security.check_not_locked("1.2.3.4")
    assert exc.value.status_code == 429


def test_verrouillage_expire():
    for _ in range(security.MAX_FAILURES):
        security.record_failure("1.2.3.4")
    FakeTime.now += security.LOCKOUT_S + 1
    security.check_not_locked("1.2.3.4")  # ne lève plus


def test_succes_remet_le_compteur_a_zero():
    for _ in range(security.MAX_FAILURES - 1):
        security.record_failure("1.2.3.4")
    security.record_success("1.2.3.4")
    for _ in range(security.MAX_FAILURES - 1):
        security.record_failure("1.2.3.4")
    security.check_not_locked("1.2.3.4")  # toujours pas verrouillé


def test_ips_independantes():
    for _ in range(security.MAX_FAILURES):
        security.record_failure("1.2.3.4")
    security.check_not_locked("5.6.7.8")  # une autre IP n'est pas punie
