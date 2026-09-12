"""Durcissement de l'API : comparaison de jetons à temps constant et
verrouillage anti-force-brute par adresse IP.

L'app n'est pensée que pour un réseau local / VPN, mais on la traite comme si
elle était exposée : le jeton protège les clés de courtiers.
"""
import secrets as pysecrets
import threading
import time

from fastapi import HTTPException, Request

# Fenêtre glissante : au-delà de MAX_FAILURES échecs en WINDOW_S secondes,
# l'IP est bloquée LOCKOUT_S secondes.
MAX_FAILURES = 5
WINDOW_S = 15 * 60
LOCKOUT_S = 15 * 60

_lock = threading.Lock()
_failures: dict[str, list[float]] = {}
_locked_until: dict[str, float] = {}


def tokens_match(provided: str, expected: str) -> bool:
    """Comparaison à temps constant (pas de fuite par chronométrage)."""
    if not provided or not expected:
        return False
    return pysecrets.compare_digest(provided.encode(), expected.encode())


def client_ip(request: Request) -> str:
    # X-Real-IP est posé par notre nginx ; derrière lui, request.client est
    # l'IP du proxy. Si le core est joint en direct, l'en-tête est absent.
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "?")


def check_not_locked(ip: str) -> None:
    now = time.monotonic()
    with _lock:
        until = _locked_until.get(ip, 0.0)
        if until > now:
            raise HTTPException(
                status_code=429,
                detail=f"trop de tentatives — réessayez dans {int(until - now) + 1} s",
            )


def record_failure(ip: str) -> None:
    now = time.monotonic()
    with _lock:
        attempts = [t for t in _failures.get(ip, []) if now - t < WINDOW_S]
        attempts.append(now)
        _failures[ip] = attempts
        if len(attempts) >= MAX_FAILURES:
            _locked_until[ip] = now + LOCKOUT_S
            _failures[ip] = []


def record_success(ip: str) -> None:
    with _lock:
        _failures.pop(ip, None)
        _locked_until.pop(ip, None)
