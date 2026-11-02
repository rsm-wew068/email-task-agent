"""Export the OpenAPI schema for the Next.js typed client (migration §3.3).

Writes web/openapi.json from create_app(Deps(MemoryStore(), ...)) — routes are
registered unconditionally, so the schema doesn't depend on wiring. Keys are
sorted so diffs stay stable (CI drift check regenerates and diffs this file).

  uv run python scripts/export_openapi.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from email_task_agent.app.main import Deps, create_app
from email_task_agent.memory import MemoryStore

OUT = Path(__file__).resolve().parents[1] / "web" / "openapi.json"


def main() -> int:
    app = create_app(Deps(store=MemoryStore(), mode="demo", owner_email="alex@fernwoodlabs.com"))
    schema = app.openapi()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUT} ({len(schema.get('paths', {}))} paths)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
