"""Gmail credential loading: file, env-var fallback, and the missing case."""

from __future__ import annotations

import json

import pytest

from email_task_agent.gmail.client import load_credentials

CREDS = {"token": "t", "refresh_token": "r", "client_id": "c", "client_secret": "s", "scopes": ["x"]}


def test_load_from_file(tmp_path, monkeypatch):
    monkeypatch.delenv("GMAIL_TOKEN_JSON", raising=False)
    path = tmp_path / "token.json"
    path.write_text(json.dumps(CREDS))
    creds = load_credentials(str(path))
    assert creds.token == "t"


def test_load_from_env_when_no_file(tmp_path, monkeypatch):
    monkeypatch.setenv("GMAIL_TOKEN_JSON", json.dumps(CREDS))
    creds = load_credentials(str(tmp_path / "missing.json"))
    assert creds.token == "t"


def test_missing_everywhere_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("GMAIL_TOKEN_JSON", raising=False)
    with pytest.raises(RuntimeError, match="auth_gmail.py"):
        load_credentials(str(tmp_path / "missing.json"))
