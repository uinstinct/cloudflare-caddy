from pathlib import Path

import pytest

from cf_setup.config import Config, ConfigError


def base_env(**overrides):
    env = {"CF_DOMAIN": "example.com", "CF_API_TOKEN": "tok"}
    env.update(overrides)
    return env


def test_domain_is_required():
    with pytest.raises(ConfigError, match="CF_DOMAIN"):
        Config.from_env({})


def test_token_required_when_online():
    with pytest.raises(ConfigError, match="CF_API_TOKEN"):
        Config.from_env({"CF_DOMAIN": "example.com"})


def test_token_optional_when_offline():
    cfg = Config.from_env({"CF_DOMAIN": "example.com", "CF_OFFLINE": "true"})
    assert cfg.offline is True
    assert cfg.api_token is None


def test_default_cert_hostnames_cover_apex_and_wildcard():
    cfg = Config.from_env(base_env())
    assert cfg.cert_hostnames == ["example.com", "*.example.com"]


def test_custom_cert_hostnames_are_parsed():
    cfg = Config.from_env(base_env(CERT_HOSTNAMES="a.example.com, *.example.com ,b.example.com"))
    assert cfg.cert_hostnames == ["a.example.com", "*.example.com", "b.example.com"]


def test_domain_is_lowercased():
    cfg = Config.from_env(base_env(CF_DOMAIN="Example.COM"))
    assert cfg.domain == "example.com"
    assert cfg.cert_hostnames == ["example.com", "*.example.com"]


def test_invalid_validity_rejected():
    with pytest.raises(ConfigError, match="CERT_VALIDITY_DAYS"):
        Config.from_env(base_env(CERT_VALIDITY_DAYS="100"))


def test_valid_validity_accepted():
    cfg = Config.from_env(base_env(CERT_VALIDITY_DAYS="90"))
    assert cfg.cert_validity_days == 90


def test_invalid_ssl_mode_rejected():
    with pytest.raises(ConfigError, match="SSL_MODE"):
        Config.from_env(base_env(SSL_MODE="bogus"))


def test_non_integer_renew_rejected():
    with pytest.raises(ConfigError, match="RENEW_BEFORE_DAYS"):
        Config.from_env(base_env(RENEW_BEFORE_DAYS="soon"))


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("true", True),
        ("1", True),
        ("YES", True),
        ("on", True),
        ("false", False),
        ("0", False),
        ("no", False),
        ("", True),
    ],
)
def test_dns_proxied_bool_parsing(raw, expected):
    # empty string falls back to the default (True)
    cfg = Config.from_env(base_env(DNS_PROXIED=raw))
    assert cfg.proxied is expected


def test_defaults():
    cfg = Config.from_env(base_env())
    assert cfg.proxied is True
    assert cfg.ssl_mode == "strict"
    assert cfg.manage_apex is False
    assert cfg.cert_validity_days == 5475
    assert cfg.renew_before_days == 30
    assert cfg.dns_ttl == 1
    assert cfg.certs_dir == Path("/certs")
