"""Configuration centrale du core NewsTrader.

Les réglages non sensibles viennent des variables d'environnement (.env).
Les clés API sensibles vivent dans secrets/credentials.enc.json, chiffré
avec MASTER_KEY — voir app/secrets.py.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Infra
    database_url: str = "sqlite:///./newstrader.db"
    api_token: str = "change-me"
    master_key: str = ""
    secrets_file: str = "/secrets/credentials.enc.json"
    tz: str = "Europe/Paris"

    # Trading
    start_capital: float = 10_000.0
    base_currency: str = "EUR"

    # LLM — par défaut, tout est calibré pour le coût zéro :
    # Gemini en analyste (quota gratuit AI Studio, flash = plafond gratuit élevé),
    # CLI Claude Code en second avis (incluse dans l'abonnement Claude Pro/Max).
    claude_model: str = "claude-sonnet-5"       # utilisé si API Anthropic payante
    gemini_model: str = "gemini-2.5-flash"
    # Conviction minimale pour exécuter un signal validé par les deux modèles
    min_conviction: int = 65
    # Conviction à partir de laquelle Claude seul suffit (si Gemini indisponible)
    solo_conviction: int = 80
    # Nombre max de news envoyées au LLM par lot (maîtrise du coût)
    llm_batch_size: int = 12

    # Scheduler (minutes)
    ingest_interval_min: int = 5
    analyze_interval_min: int = 5
    monitor_interval_min: int = 1

    # Durée de validité d'un signal non exécuté (minutes)
    signal_ttl_min: int = 90


@lru_cache
def get_settings() -> Settings:
    return Settings()
