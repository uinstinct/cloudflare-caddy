"""Minimal Cloudflare API v4 client covering exactly what the bootstrap needs.

Every mutating call is expressed as an ``ensure_*`` method that first reads the
current state and only writes when it differs, so the whole run is idempotent
and safe to repeat.
"""

from __future__ import annotations

from typing import Any

import httpx

API_BASE = "https://api.cloudflare.com/client/v4"


class CloudflareError(Exception):
    """Raised when the Cloudflare API reports a failure."""


class CloudflareClient:
    def __init__(self, token: str, client: httpx.Client, base_url: str = API_BASE) -> None:
        self._client = client
        self._base = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        resp = self._client.request(method, f"{self._base}{path}", headers=self._headers, **kwargs)
        try:
            data = resp.json()
        except ValueError as exc:
            raise CloudflareError(
                f"{method} {path}: non-JSON response (HTTP {resp.status_code})"
            ) from exc
        if not data.get("success", False):
            errors = data.get("errors") or []
            detail = (
                "; ".join(f"{e.get('code')}: {e.get('message')}" for e in errors)
                or f"HTTP {resp.status_code}"
            )
            raise CloudflareError(f"{method} {path} failed: {detail}")
        return data

    # -- account / zone ----------------------------------------------------

    def verify_token(self) -> dict[str, Any]:
        return self._request("GET", "/user/tokens/verify")["result"]

    def get_zone_id(self, name: str) -> str:
        result = self._request("GET", "/zones", params={"name": name})["result"]
        if not result:
            raise CloudflareError(
                f"zone {name!r} not found on this account "
                "(check CF_DOMAIN and that the token has Zone:Read for it)"
            )
        return result[0]["id"]

    # -- DNS ---------------------------------------------------------------

    def find_dns_record(
        self, zone_id: str, name: str, record_type: str = "A"
    ) -> dict[str, Any] | None:
        result = self._request(
            "GET",
            f"/zones/{zone_id}/dns_records",
            params={"name": name, "type": record_type},
        )["result"]
        return result[0] if result else None

    def ensure_dns_record(
        self,
        zone_id: str,
        name: str,
        content: str,
        record_type: str = "A",
        proxied: bool = True,
        ttl: int = 1,
    ) -> tuple[str, dict[str, Any]]:
        """Create / update an A record, returning ``(action, record)``.

        ``action`` is one of ``created``, ``updated`` or ``unchanged``.
        """
        existing = self.find_dns_record(zone_id, name, record_type)
        body = {
            "type": record_type,
            "name": name,
            "content": content,
            "proxied": proxied,
            "ttl": ttl,
        }
        if existing is None:
            created = self._request("POST", f"/zones/{zone_id}/dns_records", json=body)["result"]
            return "created", created
        if (
            existing.get("type") == record_type
            and existing.get("content") == content
            and bool(existing.get("proxied")) == proxied
        ):
            return "unchanged", existing
        updated = self._request("PUT", f"/zones/{zone_id}/dns_records/{existing['id']}", json=body)[
            "result"
        ]
        return "updated", updated

    # -- SSL/TLS mode ------------------------------------------------------

    def get_ssl_mode(self, zone_id: str) -> str:
        return self._request("GET", f"/zones/{zone_id}/settings/ssl")["result"]["value"]

    def ensure_ssl_mode(self, zone_id: str, mode: str) -> tuple[str, str]:
        current = self.get_ssl_mode(zone_id)
        if current == mode:
            return "unchanged", current
        self._request("PATCH", f"/zones/{zone_id}/settings/ssl", json={"value": mode})
        return "updated", mode

    # -- Origin CA certificates -------------------------------------------

    def create_origin_cert(
        self,
        hostnames: list[str],
        csr_pem: str,
        validity_days: int,
        request_type: str = "origin-rsa",
    ) -> dict[str, Any]:
        body = {
            "hostnames": hostnames,
            "csr": csr_pem,
            "request_type": request_type,
            "requested_validity": validity_days,
        }
        return self._request("POST", "/certificates", json=body)["result"]
