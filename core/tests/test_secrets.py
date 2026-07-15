from cryptography.fernet import Fernet

from app.secrets import SecretStore


def test_roundtrip_encrypted(tmp_path):
    key = Fernet.generate_key().decode()
    path = str(tmp_path / "creds.enc.json")

    store = SecretStore(path=path, master_key=key)
    store.set("kraken_api_key", "s3cret")
    assert store.get("kraken_api_key") == "s3cret"

    # Le fichier sur disque ne contient jamais la valeur en clair
    raw = (tmp_path / "creds.enc.json").read_bytes()
    assert b"s3cret" not in raw

    # Relecture depuis un nouveau store (nouveau process simulé)
    store2 = SecretStore(path=path, master_key=key)
    assert store2.get("kraken_api_key") == "s3cret"
    assert store2.names() == ["kraken_api_key"]


def test_env_var_overrides(tmp_path, monkeypatch):
    key = Fernet.generate_key().decode()
    store = SecretStore(path=str(tmp_path / "c.json"), master_key=key)
    store.set("finnhub_api_key", "from-file")
    monkeypatch.setenv("FINNHUB_API_KEY", "from-env")
    assert store.get("finnhub_api_key") == "from-env"


def test_missing_master_key_reads_empty(tmp_path):
    store = SecretStore(path=str(tmp_path / "c.json"), master_key="")
    assert store.get("whatever", "default") == "default"
