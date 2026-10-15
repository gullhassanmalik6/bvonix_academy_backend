"""Production checks for signing secrets.

Development and test processes may start with a local placeholder.
Production must not.
"""

from __future__ import annotations

_PRODUCTION = {"production", "prod"}
_PLACEHOLDERS = {
    "change_me",
    "change_me_to_a_long_random_secret",
    "secret",
    "password",
    "jwt_secret",
}
_MINIMUM_SECRET_BYTES = 32


def production_environment(app_env: str) -> bool:
    return (app_env or "").strip().lower() in _PRODUCTION


def ensure_production_origins(*, app_env: str, allowed_origins: str | None) -> None:
    """Production must name its frontend origins. An empty list must not fall back to localhost."""
    if not production_environment(app_env):
        return
    origins = [item.strip() for item in (allowed_origins or "").split(",") if item.strip()]
    if not origins:
        raise RuntimeError("Production startup failed because ALLOWED_ORIGINS is empty.")


def ensure_production_secret(*, app_env: str, jwt_secret: str | None, jwt_algorithm: str | None) -> None:
    """Refuse to serve production traffic with a placeholder or short signing secret.

    The exception text does not include the configured value.
    """
    if not production_environment(app_env):
        return
    secret = jwt_secret or ""
    algorithm = (jwt_algorithm or "").strip().upper()
    if (
        not secret.strip()
        or secret.strip().lower() in _PLACEHOLDERS
        or len(secret.encode("utf-8")) < _MINIMUM_SECRET_BYTES
        or algorithm != "HS256"
    ):
        raise RuntimeError(
            "Production startup failed because JWT_SECRET is not a usable HS256 signing secret."
        )
