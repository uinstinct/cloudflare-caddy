import httpx
import pytest
import respx

from cf_setup.cloudflare import API_BASE, CloudflareClient, CloudflareError

ZONE = "zone123"


def ok(result):
    return httpx.Response(
        200, json={"success": True, "errors": [], "messages": [], "result": result}
    )


def fail(code=1003, message="bad", status=400):
    return httpx.Response(
        status,
        json={"success": False, "errors": [{"code": code, "message": message}], "result": None},
    )


def client():
    return CloudflareClient("tok", httpx.Client())


@respx.mock
def test_verify_token():
    route = respx.get(f"{API_BASE}/user/tokens/verify").mock(return_value=ok({"status": "active"}))
    assert client().verify_token()["status"] == "active"
    assert route.calls.last.request.headers["authorization"] == "Bearer tok"


@respx.mock
def test_get_zone_id():
    respx.get(f"{API_BASE}/zones").mock(return_value=ok([{"id": ZONE}]))
    assert client().get_zone_id("example.com") == ZONE


@respx.mock
def test_get_zone_id_missing_raises():
    respx.get(f"{API_BASE}/zones").mock(return_value=ok([]))
    with pytest.raises(CloudflareError, match="not found"):
        client().get_zone_id("example.com")


@respx.mock
def test_api_failure_envelope_raises():
    respx.get(f"{API_BASE}/zones").mock(return_value=fail(code=9109, message="invalid token"))
    with pytest.raises(CloudflareError, match="9109: invalid token"):
        client().get_zone_id("example.com")


@respx.mock
def test_ensure_dns_record_created_when_missing():
    respx.get(f"{API_BASE}/zones/{ZONE}/dns_records").mock(return_value=ok([]))
    post = respx.post(f"{API_BASE}/zones/{ZONE}/dns_records").mock(
        return_value=ok({"id": "rec1", "name": "*.example.com", "content": "1.2.3.4"})
    )
    action, _ = client().ensure_dns_record(ZONE, "*.example.com", "1.2.3.4")
    assert action == "created"
    assert post.called


@respx.mock
def test_ensure_dns_record_unchanged_when_identical():
    respx.get(f"{API_BASE}/zones/{ZONE}/dns_records").mock(
        return_value=ok([{"id": "rec1", "type": "A", "content": "1.2.3.4", "proxied": True}])
    )
    post = respx.post(f"{API_BASE}/zones/{ZONE}/dns_records")
    put = respx.put(f"{API_BASE}/zones/{ZONE}/dns_records/rec1")
    action, _ = client().ensure_dns_record(ZONE, "*.example.com", "1.2.3.4", proxied=True)
    assert action == "unchanged"
    assert not post.called and not put.called


@respx.mock
def test_ensure_dns_record_updated_when_content_differs():
    respx.get(f"{API_BASE}/zones/{ZONE}/dns_records").mock(
        return_value=ok([{"id": "rec1", "type": "A", "content": "9.9.9.9", "proxied": True}])
    )
    put = respx.put(f"{API_BASE}/zones/{ZONE}/dns_records/rec1").mock(
        return_value=ok({"id": "rec1", "content": "1.2.3.4"})
    )
    action, _ = client().ensure_dns_record(ZONE, "*.example.com", "1.2.3.4", proxied=True)
    assert action == "updated"
    assert put.called


@respx.mock
def test_ensure_dns_record_updated_when_proxy_differs():
    respx.get(f"{API_BASE}/zones/{ZONE}/dns_records").mock(
        return_value=ok([{"id": "rec1", "type": "A", "content": "1.2.3.4", "proxied": False}])
    )
    put = respx.put(f"{API_BASE}/zones/{ZONE}/dns_records/rec1").mock(
        return_value=ok({"id": "rec1", "content": "1.2.3.4", "proxied": True})
    )
    action, _ = client().ensure_dns_record(ZONE, "*.example.com", "1.2.3.4", proxied=True)
    assert action == "updated"
    assert put.called


@respx.mock
def test_ensure_ssl_mode_unchanged():
    respx.get(f"{API_BASE}/zones/{ZONE}/settings/ssl").mock(return_value=ok({"value": "strict"}))
    patch = respx.patch(f"{API_BASE}/zones/{ZONE}/settings/ssl")
    action, value = client().ensure_ssl_mode(ZONE, "strict")
    assert action == "unchanged" and value == "strict"
    assert not patch.called


@respx.mock
def test_ensure_ssl_mode_updated():
    respx.get(f"{API_BASE}/zones/{ZONE}/settings/ssl").mock(return_value=ok({"value": "flexible"}))
    patch = respx.patch(f"{API_BASE}/zones/{ZONE}/settings/ssl").mock(
        return_value=ok({"value": "strict"})
    )
    action, value = client().ensure_ssl_mode(ZONE, "strict")
    assert action == "updated" and value == "strict"
    assert patch.called


@respx.mock
def test_create_origin_cert():
    route = respx.post(f"{API_BASE}/certificates").mock(
        return_value=ok(
            {"id": "c1", "certificate": "-----BEGIN CERTIFICATE-----", "expires_on": "2040"}
        )
    )
    result = client().create_origin_cert(["example.com", "*.example.com"], "CSR", 5475)
    assert result["certificate"].startswith("-----BEGIN CERTIFICATE-----")
    body = route.calls.last.request.content
    assert b'"request_type":"origin-rsa"' in body
    assert b'"requested_validity":5475' in body
