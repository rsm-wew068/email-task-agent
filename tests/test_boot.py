"""Boot resilience: the app factory must never block or crash on the database.

Boot wires a lazy store and prepare_database() retries migrate+seed in the
background; pages show the offline banner until it lands.
"""

from __future__ import annotations

import psycopg
import pytest

from email_task_agent import db
from email_task_agent.app.main import prepare_database
from email_task_agent.memory import MemoryStore


def _patch_db(monkeypatch, fail_times: int, *, migrate_calls: list[int], seed_calls: list[int]):
    """connect() fails `fail_times` times then hands a sentinel to no-op
    migrate/seed (the SQL paths are covered by the real-Postgres tests)."""
    calls = []

    def flaky_connect():
        calls.append(1)
        if len(calls) <= fail_times:
            raise psycopg.OperationalError("tenant/user not found")
        return "sentinel-connection"

    def fake_migrate(_conn):
        migrate_calls.append(1)

    def fake_seed(_store, *, owner_email):
        seed_calls.append(1)

    monkeypatch.setattr(db, "connect", flaky_connect)
    monkeypatch.setattr(db, "migrate", fake_migrate)
    from email_task_agent.demo import seed as seed_module

    monkeypatch.setattr(seed_module, "seed_demo_instance", fake_seed)


def test_prepare_database_rides_out_transient_failures(monkeypatch):
    store = MemoryStore()
    migrates: list[int] = []
    seeds: list[int] = []
    _patch_db(monkeypatch, fail_times=2, migrate_calls=migrates, seed_calls=seeds)

    sleeps: list[float] = []
    prepare_database(store, owner_email="a@x", _sleep=sleeps.append)

    assert migrates == [1] and seeds == [1]
    assert sleeps == [2.0, 4.0]  # exponential backoff


def test_prepare_database_raises_after_finite_attempts(monkeypatch):
    store = MemoryStore()
    _patch_db(monkeypatch, fail_times=99, migrate_calls=[], seed_calls=[])

    with pytest.raises(RuntimeError, match="unreachable"):
        prepare_database(store, owner_email="a@x", attempts=3, _sleep=lambda _s: None)


def test_build_default_app_boots_without_a_reachable_database(monkeypatch):
    """A bogus DATABASE_URL must not crash or block boot: the app serves
    healthz while the background prepare loop keeps retrying."""
    from fastapi.testclient import TestClient

    from email_task_agent.app.main import build_default_app
    from email_task_agent.config import Settings

    monkeypatch.setattr(
        "email_task_agent.config.settings",
        lambda: Settings(database_url="postgresql://x:x@127.0.0.1:1/none", instance_mode="demo"),
    )
    app = build_default_app()  # must not raise despite an unreachable DB
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["mode"] == "demo"
