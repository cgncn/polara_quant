"""Tests for IBClient (CPClient-backed shim)."""
import pytest
import respx
import httpx

from polara.broker.client import IBClient

BASE = "https://cp-gateway:5000/v1/api"


@pytest.fixture
def client():
    return IBClient(cp_gateway_url=BASE)


@respx.mock
@pytest.mark.asyncio
async def test_connect_fetches_account(client):
    respx.get(f"{BASE}/portfolio/accounts").mock(
        return_value=httpx.Response(200, json=[{"accountId": "DU999", "type": "individual"}])
    )
    await client.connect()
    assert client.connected is True
    assert client.cp.account_id == "DU999"
    await client.disconnect()


@respx.mock
@pytest.mark.asyncio
async def test_disconnect_stops_client(client):
    respx.get(f"{BASE}/portfolio/accounts").mock(
        return_value=httpx.Response(200, json=[{"accountId": "DU999", "type": "individual"}])
    )
    await client.connect()
    await client.disconnect()
    assert client.connected is False


@respx.mock
@pytest.mark.asyncio
async def test_connect_sets_connected_false_on_auth_error(client):
    """connect() does not raise if gateway is unauthenticated — server starts anyway."""
    respx.get(f"{BASE}/portfolio/accounts").mock(
        return_value=httpx.Response(200, json=[])  # no accounts = not authenticated
    )
    # connect() swallows CPAuthError so the API server can still start
    await client.connect()
    assert client.connected is False
