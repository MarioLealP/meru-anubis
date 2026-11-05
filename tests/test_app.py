import httpx2

from anubis.app import app


async def test_heartbeat():
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://app") as http:
        response = await http.get("/heartbeat")
    assert response.status_code == 200
    assert response.text == "ok"
