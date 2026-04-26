"""Tests for CPClient — HTTP layer is mocked with respx."""
import pytest
import respx
import httpx

from polara.broker.cp_client import CPAuthError, CPClient

BASE = "https://cp-gateway:5000/v1/api"


@pytest.fixture
def client():
    return CPClient(base_url=BASE)


@respx.mock
@pytest.mark.asyncio
async def test_start_fetches_account_id(client):
    respx.get(f"{BASE}/portfolio/accounts").mock(
        return_value=httpx.Response(200, json=[{"accountId": "DU123456", "type": "individual"}])
    )
    await client.start()
    assert client.account_id == "DU123456"
    await client.stop()


@respx.mock
@pytest.mark.asyncio
async def test_auth_status_returns_dict(client):
    # pre-set account so start() isn't needed
    client._account_id = "DU123456"
    client._http = httpx.AsyncClient(verify=False)
    respx.get(f"{BASE}/iserver/auth/status").mock(
        return_value=httpx.Response(200, json={"authenticated": True, "connected": True})
    )
    status = await client.auth_status()
    assert status["authenticated"] is True
    await client.stop()


@respx.mock
@pytest.mark.asyncio
async def test_get_conid_caches_result(client):
    respx.post(f"{BASE}/iserver/secdef/search").mock(
        return_value=httpx.Response(200, json=[{"conid": "488867728", "symbol": "PLTR"}])
    )
    respx.get(f"{BASE}/portfolio/accounts").mock(
        return_value=httpx.Response(200, json=[{"accountId": "DU123456"}])
    )
    await client.start()
    conid = await client.get_conid("PLTR")
    assert conid == 488867728
    # Second call hits cache — mock only registered once but that's fine with respx
    conid2 = await client.get_conid("PLTR")
    assert conid2 == 488867728
    await client.stop()


@respx.mock
@pytest.mark.asyncio
async def test_place_orders_handles_confirmation(client):
    acc = "DU123456"
    client._account_id = acc
    client._http = httpx.AsyncClient(verify=False)
    respx.post(f"{BASE}/iserver/account/{acc}/orders").mock(
        return_value=httpx.Response(200, json=[{"id": "reply123", "message": ["Confirm?"]}])
    )
    respx.post(f"{BASE}/iserver/reply/reply123").mock(
        return_value=httpx.Response(
            200, json=[{"order_id": "987", "order_status": "PreSubmitted"}]
        )
    )
    result = await client.place_orders(
        [{"conid": 488867728, "orderType": "MKT", "side": "BUY", "quantity": 1, "tif": "DAY"}]
    )
    assert result[0]["order_id"] == "987"
    await client.stop()


@respx.mock
@pytest.mark.asyncio
async def test_start_raises_when_no_accounts(client):
    respx.get(f"{BASE}/portfolio/accounts").mock(
        return_value=httpx.Response(200, json=[])
    )
    with pytest.raises(CPAuthError):
        await client.start()
    await client.stop()


def test_account_id_raises_when_not_authenticated():
    client = CPClient(base_url=BASE)
    with pytest.raises(CPAuthError):
        _ = client.account_id
