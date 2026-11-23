from pathlib import Path
import sys
import pytest
from httpx import ASGITransport, AsyncClient

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.main import app


@pytest.mark.asyncio
async def test_spa_single_port_serving():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Root should serve index.html
        res = await client.get("/")
        assert res.status_code == 200
        assert "<!doctype html>" in res.text.lower()
        assert "ClipForge" in res.text

        # 2. Client-side SPA route should also fallback to index.html
        spa_res = await client.get("/settings/advanced")
        assert spa_res.status_code == 200
        assert "<!doctype html>" in spa_res.text.lower()

        # 3. API routes must NOT be intercepted by the SPA fallback
        api_res = await client.get("/api/diagnostics")
        assert api_res.status_code == 200
        assert "gpu" in api_res.json()
