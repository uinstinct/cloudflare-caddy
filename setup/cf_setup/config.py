"""Configuration loaded from environment variables.

Kept as a pure ``from_env`` factory so it is trivial to unit test with a fake
environment mapping instead of mutating ``os.environ``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# Validity values accepted by the Cloudflare Origin CA API (in days).
ALLOWED_VALIDITY = (7, 30, 90, 365, 730, 1095, 5475)
DEFAULT_VALIDITY = 5475  # ~15 years, the longest Origin CA allows.

ALLOWED_SSL_MODES = ("off", "flexible", "full", "strict")


class ConfigError(Exception):
    """Raised when the supplied environment is invalid or incomplete."""


def _bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = env.get(key)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"{key} must be an integer, got {raw!r}") from exc


@dataclass(frozen=True)
class Config:
    domain: str
    api_token: str | None
    server_ip: str | None
    offline: bool
    proxied: bool
    ssl_mode: str
    manage_apex: bool
    cert_validity_days: int
    cert_hostnames: list[str]
    renew_before_days: int
    dns_ttl: int
    certs_dir: Path

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Config:
        env = os.environ if env is None else env

        domain = (env.get("CF_DOMAIN") or "").strip().lower()
        if not domain:
            raise ConfigError("CF_DOMAIN is required (your Cloudflare zone apex, e.g. example.com)")

        offline = _bool(env, "CF_OFFLINE", False)
        api_token = (env.get("CF_API_TOKEN") or "").strip() or None
        if not offline and not api_token:
            raise ConfigError(
                "CF_API_TOKEN is required "
                "(or set CF_OFFLINE=true to generate a self-signed cert without Cloudflare)"
            )

        ssl_mode = (env.get("SSL_MODE") or "strict").strip().lower()
        if ssl_mode not in ALLOWED_SSL_MODES:
            raise ConfigError(f"SSL_MODE must be one of {ALLOWED_SSL_MODES}, got {ssl_mode!r}")

        validity = _int(env, "CERT_VALIDITY_DAYS", DEFAULT_VALIDITY)
        if validity not in ALLOWED_VALIDITY:
            raise ConfigError(
                f"CERT_VALIDITY_DAYS must be one of {ALLOWED_VALIDITY}, got {validity}"
            )

        hostnames_raw = (env.get("CERT_HOSTNAMES") or "").strip()
        if hostnames_raw:
            cert_hostnames = [h.strip() for h in hostnames_raw.split(",") if h.strip()]
        else:
            cert_hostnames = [domain, f"*.{domain}"]

        return cls(
            domain=domain,
            api_token=api_token,
            server_ip=(env.get("SERVER_IP") or "").strip() or None,
            offline=offline,
            proxied=_bool(env, "DNS_PROXIED", True),
            ssl_mode=ssl_mode,
            manage_apex=_bool(env, "MANAGE_APEX", False),
            cert_validity_days=validity,
            cert_hostnames=cert_hostnames,
            renew_before_days=_int(env, "RENEW_BEFORE_DAYS", 30),
            dns_ttl=_int(env, "DNS_TTL", 1),
            certs_dir=Path(env.get("CERTS_DIR") or "/certs"),
        )
