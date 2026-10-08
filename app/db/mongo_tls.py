"""MongoDB TLS policy.

Certificate validation stays on unless a development process explicitly opts in.
Production cannot enable tlsAllowInvalidCertificates, including when that option
is present on the connection string.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlparse

_INSECURE_TRUE = {"true", "1", "yes"}
_INSECURE_QUERY_KEYS = {
    "tlsallowinvalidcertificates",
    "tlsallowinvalidhostnames",
    "tlsinsecure",
}


def _query(uri: str) -> list[tuple[str, str]]:
    return parse_qsl(urlparse(uri).query, keep_blank_values=True)


def uri_uses_tls(uri: str) -> bool:
    if uri.lower().startswith("mongodb+srv://"):
        return True
    values = {key.lower(): value.lower() for key, value in _query(uri)}
    return values.get("tls") == "true" or values.get("ssl") == "true"


def uri_requests_insecure_tls(uri: str) -> bool:
    return any(
        key.lower() in _INSECURE_QUERY_KEYS and value.lower() in _INSECURE_TRUE
        for key, value in _query(uri)
    )


def tls_allow_invalid_certificates(*, app_env: str, allow_invalid_certificates: bool, uri: str) -> bool:
    """Return whether this process may skip certificate validation.

    The bypass is development-only and requires MONGODB_TLS_ALLOW_INVALID_CERTIFICATES.
    A connection-string flag is not enough. Any other environment refuses to start
    if an insecure TLS option was requested.
    """
    environment = (app_env or "").strip().lower()
    requested = bool(allow_invalid_certificates) or uri_requests_insecure_tls(uri)
    if environment != "development":
        if requested:
            raise ValueError(
                "MongoDB TLS certificate validation cannot be disabled unless "
                "APP_ENV=development and MONGODB_TLS_ALLOW_INVALID_CERTIFICATES=true."
            )
        return False
    return bool(allow_invalid_certificates)


def mongo_client_options(settings) -> dict:
    """Client options for the configured environment. Does not include the URI."""
    allow_invalid = tls_allow_invalid_certificates(
        app_env=settings.app_env,
        allow_invalid_certificates=settings.mongodb_tls_allow_invalid_certificates,
        uri=settings.mongodb_uri,
    )
    options = {
        "serverSelectionTimeoutMS": 5000,
        "connectTimeoutMS": 5000,
    }
    if uri_uses_tls(settings.mongodb_uri):
        options["tlsAllowInvalidCertificates"] = allow_invalid
    return options
