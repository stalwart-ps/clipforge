from pathlib import Path
import sys
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.core.config import settings
from app.core.db import Base, engine
from app.main import app


@pytest_asyncio.fixture(autouse=True)
async def init_test_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest.mark.asyncio
async def test_settings_lifecycle():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Fetch default settings
        res = await client.get("/api/settings")
        assert res.status_code == 200
        data = res.json()
        assert data["hardwarePreset"] in ["lite", "balanced", "pro", "custom"]
        assert "whisperModel" in data
        assert "ollamaModel" in data

        # 2. Update to 'lite' preset
        res_lite = await client.put(
            "/api/settings",
            json={"hardwarePreset": "lite"},
        )
        assert res_lite.status_code == 200
        lite_data = res_lite.json()
        assert lite_data["hardwarePreset"] == "lite"
        assert lite_data["whisperModel"] == "base"
        assert lite_data["encoder"] == "libx264"

        # 3. Update cookies and PO-token
        res_cookies = await client.put(
            "/api/settings",
            json={
                "cookiesBrowser": "chrome",
                "poToken": "test_po_token_123",
            },
        )
        assert res_cookies.status_code == 200
        cookies_data = res_cookies.json()
        assert cookies_data["cookiesBrowser"] == "chrome"
        assert cookies_data["poToken"] == "test_po_token_123"


@pytest.mark.asyncio
async def test_cache_stats_and_clean():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Create a dummy temp file
        dummy_file = settings.temp_dir / "test_scratch.tmp"
        dummy_file.write_text("dummy cache bytes" * 100)

        # 1. Get cache stats
        res = await client.get("/api/cache/stats")
        assert res.status_code == 200
        stats = res.json()
        assert stats["totalBytes"] > 0
        assert stats["fileCount"] >= 1

        # 2. Clean cache
        clean_res = await client.post("/api/cache/clean")
        assert clean_res.status_code == 200
        clean_data = clean_res.json()
        assert clean_data["filesDeleted"] >= 1
        assert not dummy_file.exists()
