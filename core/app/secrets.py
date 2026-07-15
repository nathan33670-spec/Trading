"""Stockage chiffré des credentials API sur le serveur.

Le fichier secrets/credentials.enc.json contient un JSON {nom: valeur}
chiffré en Fernet (AES128-CBC + HMAC) avec la clé MASTER_KEY.

CLI :
    python -m app.secrets gen-key                 # génère une clé maître
    python -m app.secrets set anthropic_api_key   # ajoute/chiffre un secret
    python -m app.secrets list                    # liste les noms stockés
    python -m app.secrets gen-vapid               # génère les clés Web Push

Noms de secrets utilisés par l'application :
    google_api_key            (Gemini, quota gratuit AI Studio — analyste)
    claude_code_oauth_token   (CLI Claude Code via abonnement Pro — second avis)
    anthropic_api_key         (API Anthropic payante — optionnelle)
    finnhub_api_key, trading212_api_key, kraken_api_key, kraken_api_secret,
    vapid_public_key, vapid_private_key
"""
import json
import os
import sys
from pathlib import Path

from cryptography.fernet import Fernet

from .config import get_settings


class SecretStore:
    def __init__(self, path: str | None = None, master_key: str | None = None):
        s = get_settings()
        self.path = Path(path or s.secrets_file)
        key = master_key if master_key is not None else s.master_key
        self._fernet = Fernet(key.encode()) if key else None
        self._cache: dict[str, str] | None = None

    def _load(self) -> dict[str, str]:
        if self._cache is not None:
            return self._cache
        if not self._fernet or not self.path.exists():
            self._cache = {}
            return self._cache
        blob = self.path.read_bytes()
        self._cache = json.loads(self._fernet.decrypt(blob)) if blob else {}
        return self._cache

    def _save(self, data: dict[str, str]) -> None:
        if not self._fernet:
            raise RuntimeError("MASTER_KEY manquante : impossible de chiffrer les secrets")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(self._fernet.encrypt(json.dumps(data).encode()))
        os.chmod(self.path, 0o600)
        self._cache = data

    def get(self, name: str, default: str = "") -> str:
        # Une variable d'environnement du même nom (en majuscules) prime,
        # pratique en développement.
        env = os.environ.get(name.upper())
        if env:
            return env
        return self._load().get(name, default)

    def set(self, name: str, value: str) -> None:
        data = dict(self._load())
        data[name] = value
        self._save(data)

    def names(self) -> list[str]:
        return sorted(self._load().keys())


_store: SecretStore | None = None


def get_secret(name: str, default: str = "") -> str:
    global _store
    if _store is None:
        _store = SecretStore()
    return _store.get(name, default)


def _gen_vapid() -> tuple[str, str]:
    """Génère une paire de clés VAPID (P-256) encodées base64url."""
    import base64

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    priv = ec.generate_private_key(ec.SECP256R1())
    priv_num = priv.private_numbers().private_value.to_bytes(32, "big")
    pub = priv.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    return b64(pub), b64(priv_num)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    cmd = argv[0]
    if cmd == "gen-key":
        print(Fernet.generate_key().decode())
        return 0
    if cmd == "gen-vapid":
        store = SecretStore()
        public, private = _gen_vapid()
        store.set("vapid_public_key", public)
        store.set("vapid_private_key", private)
        print(f"Clés VAPID générées et stockées.\nClé publique : {public}")
        return 0
    if cmd == "set":
        if len(argv) < 2:
            print("usage: python -m app.secrets set <nom>")
            return 1
        import getpass

        value = getpass.getpass(f"Valeur pour '{argv[1]}' : ")
        SecretStore().set(argv[1], value)
        print(f"Secret '{argv[1]}' enregistré (chiffré).")
        return 0
    if cmd == "list":
        print("\n".join(SecretStore().names()) or "(aucun secret)")
        return 0
    print(f"Commande inconnue : {cmd}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
