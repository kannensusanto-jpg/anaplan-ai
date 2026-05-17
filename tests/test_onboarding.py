import pytest


@pytest.mark.asyncio
async def test_create_tenant(client, admin_headers):
    resp = await client.post("/v1/admin/tenants", headers=admin_headers, json={
        "company_name":       "Test Corp",
        "client_id":          "test-corp",
        "workspace_id":       "ws-test",
        "model_id":           "m-test",
        "config_module_id":   "cfg-test",
        "target_module_id":   "tgt-test",
        "import_action_id":   "imp-test",
        "commentary_file_id": "file-test",
        "client_secret":      "mysecret",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["client_id"] == "test-corp"
    assert "api_key" in data
    assert len(data["api_key"]) > 20


@pytest.mark.asyncio
async def test_duplicate_client_id_rejected(client, admin_headers):
    payload = {
        "company_name":       "Dup Corp",
        "client_id":          "dup-corp",
        "workspace_id":       "ws",
        "model_id":           "m",
        "config_module_id":   "c",
        "target_module_id":   "t",
        "import_action_id":   "i",
        "commentary_file_id": "f",
        "client_secret":      "s",
    }
    await client.post("/v1/admin/tenants", headers=admin_headers, json=payload)
    resp = await client.post("/v1/admin/tenants", headers=admin_headers, json=payload)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_invalid_admin_key_rejected(client):
    resp = await client.post(
        "/v1/admin/tenants",
        headers={"X-Admin-Key": "wrong-key"},
        json={"company_name": "X", "client_id": "x", "workspace_id": "w",
              "model_id": "m", "config_module_id": "c", "target_module_id": "t",
              "import_action_id": "i", "commentary_file_id": "f", "client_secret": "s"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_client_me(client, tenant_and_key):
    client_id, api_key = tenant_and_key
    resp = await client.get("/v1/client/me", headers={"X-API-Key": api_key})
    assert resp.status_code == 200
    assert resp.json()["client_id"] == client_id


@pytest.mark.asyncio
async def test_invalid_api_key_rejected(client):
    resp = await client.get("/v1/client/me", headers={"X-API-Key": "bad-key"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_key_rotation(client, admin_headers, tenant_and_key):
    client_id, old_key = tenant_and_key
    resp = await client.post(
        f"/v1/admin/tenants/{client_id}/rotate-key",
        headers=admin_headers,
    )
    assert resp.status_code == 200
    new_key = resp.json()["api_key"]
    assert new_key != old_key

    # old key no longer works
    r1 = await client.get("/v1/client/me", headers={"X-API-Key": old_key})
    assert r1.status_code == 401

    # new key works
    r2 = await client.get("/v1/client/me", headers={"X-API-Key": new_key})
    assert r2.status_code == 200


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
