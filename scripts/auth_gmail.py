#!/usr/bin/env python
"""One-time Gmail OAuth flow for the PRIVATE instance (run locally only).

  1. Download OAuth client credentials from Google Cloud Console
     (Desktop app type) and save as ./credentials.json — gitignored.
  2. uv run python scripts/auth_gmail.py   # opens a browser for consent
  3. token.json (gitignored) now holds the refresh token. Keep it out of the
     repo and out of any deployed image (plan §6: local file, secret manager
     if deployed).
"""

from __future__ import annotations

import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from email_task_agent.gmail.client import SCOPES  # noqa: E402


def main() -> int:
    if not Path("credentials.json").exists():
        print("credentials.json not found — download OAuth client credentials first.")
        return 1
    flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
    creds = flow.run_local_server(port=0)
    Path("token.json").write_text(creds.to_json())
    print("Saved token.json (gitignored).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
