import httpx


async def test_health_ok(client: httpx.AsyncClient) -> None:
    res = await client.get("/api/v1/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "version": "0.1.0", "db": "ok", "redis": "ok"}
    assert res.headers["x-request-id"]


async def test_request_id_is_echoed_when_well_formed(client: httpx.AsyncClient) -> None:
    res = await client.get("/api/v1/health", headers={"X-Request-ID": "req-12345678"})
    assert res.headers["x-request-id"] == "req-12345678"


async def test_malformed_request_id_is_replaced(client: httpx.AsyncClient) -> None:
    res = await client.get("/api/v1/health", headers={"X-Request-ID": "bad id\x01"})
    assert res.headers["x-request-id"] != "bad id\x01"


async def test_not_found_uses_error_envelope_and_locale(client: httpx.AsyncClient) -> None:
    res = await client.get("/api/v1/nope", headers={"Accept-Language": "en-US,en;q=0.9"})
    assert res.status_code == 404
    body = res.json()["error"]
    assert body["code"] == "NOT_FOUND"
    assert body["message"] == "The requested resource was not found."
    assert body["request_id"] == res.headers["x-request-id"]


async def test_api_responses_are_not_cacheable(client: httpx.AsyncClient) -> None:
    res = await client.get("/api/v1/health")
    assert res.headers["cache-control"] == "no-store"
