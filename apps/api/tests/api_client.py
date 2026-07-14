import asyncio
from typing import Any

from httpx import ASGITransport, AsyncClient, Response


async def _request(app, method: str, url: str, **kwargs: Any) -> Response:
    # [Design Intent] Starlette TestClient hangs with the current
    # FastAPI/Starlette stack, so tests call the ASGI app through
    # httpx's in-process transport directly.
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        return await client.request(method, url, **kwargs)


def get(app, url: str, **kwargs: Any) -> Response:
    return asyncio.run(_request(app, "GET", url, **kwargs))


def post(app, url: str, **kwargs: Any) -> Response:
    return asyncio.run(_request(app, "POST", url, **kwargs))
