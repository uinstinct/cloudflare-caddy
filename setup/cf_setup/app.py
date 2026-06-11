"""Entry point: bring Cloudflare and the local origin certificate to the
desired state, idempotently. Safe to run on every ``docker compose up``."""

from __future__ import annotations

import httpx

from . import certs, log
from .cloudflare import CloudflareClient, CloudflareError
from .config import Config, ConfigError

# Plain-text IP echo services, tried in order, used only when SERVER_IP is unset.
_IP_LOOKUP_URLS = (
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
    "https://icanhazip.com",
)


def detect_public_ip(client: httpx.Client) -> str:
    for url in _IP_LOOKUP_URLS:
        try:
            resp = client.get(url, timeout=10)
            resp.raise_for_status()
            ip = resp.text.strip()
            if ip:
                return ip
        except httpx.HTTPError as exc:
            log.warn(f"public IP lookup via {url} failed: {exc}")
    raise RuntimeError("could not auto-detect the public IP; set SERVER_IP in your .env")


def _log_action(action: str, what: str) -> None:
    if action == "created":
        log.ok(f"created {what}")
    elif action == "updated":
        log.ok(f"updated {what}")
    else:
        log.skip(f"already correct: {what}")


def _ensure_origin_cert(cfg: Config, cf: CloudflareClient) -> None:
    usable, reason = certs.evaluate_local_cert(
        cfg.certs_dir, cfg.cert_hostnames, cfg.renew_before_days
    )
    if usable:
        log.skip(f"origin certificate {reason}")
        return
    log.action(f"requesting a new origin certificate ({reason})")
    key = certs.generate_private_key()
    csr_pem = certs.build_csr(key, cfg.cert_hostnames).decode()
    result = cf.create_origin_cert(cfg.cert_hostnames, csr_pem, cfg.cert_validity_days)
    certs.write_cert_files(
        cfg.certs_dir, result["certificate"].encode(), certs.private_key_pem(key)
    )
    log.ok(
        f"origin certificate saved (expires {result.get('expires_on', 'n/a')}); "
        f"covers {', '.join(cfg.cert_hostnames)}"
    )


def _run_offline(cfg: Config) -> None:
    log.step("offline mode: generating a self-signed certificate (no Cloudflare calls)")
    usable, reason = certs.evaluate_local_cert(
        cfg.certs_dir, cfg.cert_hostnames, cfg.renew_before_days
    )
    if usable:
        log.skip(f"self-signed certificate {reason}")
        return
    log.action(f"minting a self-signed certificate ({reason})")
    key = certs.generate_private_key()
    cert_pem = certs.self_signed_cert(key, cfg.cert_hostnames, cfg.cert_validity_days)
    certs.write_cert_files(cfg.certs_dir, cert_pem, certs.private_key_pem(key))
    log.ok(f"self-signed certificate saved; covers {', '.join(cfg.cert_hostnames)}")


def _run_online(cfg: Config) -> None:
    with httpx.Client(timeout=30) as client:
        cf = CloudflareClient(cfg.api_token, client)

        log.step("verifying the Cloudflare API token")
        info = cf.verify_token()
        log.ok(f"token is valid (status: {info.get('status')})")

        log.step(f"looking up the zone for {cfg.domain}")
        zone_id = cf.get_zone_id(cfg.domain)
        log.ok(f"zone id {zone_id}")

        if cfg.server_ip:
            server_ip = cfg.server_ip
            log.ok(f"using SERVER_IP={server_ip}")
        else:
            log.step("auto-detecting the public IP")
            server_ip = detect_public_ip(client)
            log.ok(f"detected public IP {server_ip}")

        log.step("ensuring DNS records")
        targets = [(f"*.{cfg.domain}", "wildcard record")]
        if cfg.manage_apex:
            targets.append((cfg.domain, "apex record"))
        for name, label in targets:
            action, _ = cf.ensure_dns_record(
                zone_id, name, server_ip, "A", cfg.proxied, cfg.dns_ttl
            )
            _log_action(action, f"{label} {name} -> {server_ip} (proxied={cfg.proxied})")

        log.step(f"ensuring SSL/TLS mode = {cfg.ssl_mode}")
        action, _ = cf.ensure_ssl_mode(zone_id, cfg.ssl_mode)
        _log_action(action, f"SSL/TLS mode {cfg.ssl_mode}")

        log.step("ensuring the origin certificate")
        _ensure_origin_cert(cfg, cf)


def main() -> int:
    try:
        cfg = Config.from_env()
    except ConfigError as exc:
        log.error(str(exc))
        return 2

    log.banner(f"Cloudflare + Caddy bootstrap for {cfg.domain}")
    try:
        if cfg.offline:
            _run_offline(cfg)
        else:
            _run_online(cfg)
    except (CloudflareError, RuntimeError) as exc:
        log.error(str(exc))
        return 1
    except httpx.HTTPError as exc:
        log.error(f"network error talking to Cloudflare: {exc}")
        return 1

    log.banner("setup complete")
    return 0
