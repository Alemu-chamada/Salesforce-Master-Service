import pytest

from src.app import main


@pytest.mark.asyncio
async def test_startup_detects_stale_jobs(monkeypatch):
    class FakeSession:
        def close(self):
            return None

    class FakeJobService:
        detected = None

        def __init__(self, session):
            assert isinstance(session, FakeSession)

        def detect_crashed_jobs(self):
            FakeJobService.detected = True
            return ["scan-stale"]

    monkeypatch.setattr(main.Base.metadata, "create_all", lambda bind: None)
    monkeypatch.setattr(main, "get_engine", lambda: object())
    monkeypatch.setattr(main, "get_session_factory", lambda: lambda: FakeSession())
    monkeypatch.setattr(main, "JobService", FakeJobService)

    async with main.lifespan(None):
        pass

    assert FakeJobService.detected is True