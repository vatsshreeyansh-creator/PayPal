"""Fail when committed OpenAPI differs from the Pydantic/path generator."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.export_openapi import make_spec  # noqa: E402

expected = json.dumps(make_spec(), indent=2) + "\n"
actual = (ROOT / "openapi.json").read_text(encoding="utf-8")
if actual != expected:
    raise SystemExit("openapi.json is stale; run `npm run contracts:openapi` and commit the result")
print("openapi.json is up to date")
