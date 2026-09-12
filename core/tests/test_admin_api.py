"""Endpoints d'admin : gestion des clés depuis la PWA, sans fuite des valeurs."""
import pytest
from fastapi.testclient import TestClient

from app import security
from app.main import app

HEADERS = {"X-API-Token": "test-token"}


@pytest.fixture
def client():
    security._failures.clear()
    security._locked_until.clear()
    with TestClient(app) as c:
        yield c


def test_sans_jeton_401(client):
    assert client.get("/api/admin/secrets").status_code == 401


def test_cycle_set_list_delete(client):
    value = "AIzaFAKE-testvalue-1234"
    r = client.put("/api/admin/secrets/google_api_key", json={"value": value}, headers=HEADERS)
    assert r.status_code == 200

    r = client.get("/api/admin/secrets", headers=HEADERS)
    assert r.status_code == 200
    assert value not in r.text  # la valeur ne redescend jamais
    item = next(i for i in r.json() if i["name"] == "google_api_key")
    assert item["configured"] is True
    assert item["hint"] == "…1234"

    r = client.delete("/api/admin/secrets/google_api_key", headers=HEADERS)
    assert r.status_code == 200
    item = next(i for i in client.get("/api/admin/secrets", headers=HEADERS).json()
                if i["name"] == "google_api_key")
    assert item["configured"] is False


def test_cle_inconnue_404(client):
    r = client.put("/api/admin/secrets/pas_une_cle", json={"value": "x"}, headers=HEADERS)
    assert r.status_code == 404


def test_status_fournisseurs(client):
    client.put("/api/admin/secrets/google_api_key", json={"value": "AIzaFAKE"}, headers=HEADERS)
    st = client.get("/api/admin/status", headers=HEADERS).json()
    assert st["providers"]["gemini"] is True
    assert st["analyst"] == "gemini"
    assert st["push_ready"] is True  # clés VAPID auto-générées au démarrage
    client.delete("/api/admin/secrets/google_api_key", headers=HEADERS)


def test_verrouillage_force_brute(client):
    for _ in range(security.MAX_FAILURES):
        assert client.post("/api/auth/login", json={"token": "mauvais"}).status_code == 401
    # Même le bon jeton est refusé pendant le verrouillage
    assert client.post("/api/auth/login", json={"token": "test-token"}).status_code == 429


def test_en_tetes_de_securite(client):
    r = client.get("/api/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Cache-Control"] == "no-store"
