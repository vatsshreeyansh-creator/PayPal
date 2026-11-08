"""Smoke-test the production React build through Flask's same-origin routes."""
import os
import re
import sys
import tempfile
import atexit
from pathlib import Path


_database = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_database.close()
os.environ["TRADEPOINT_DATABASE_URL"] = "sqlite:///" + _database.name.replace("\\", "/")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app  # noqa: E402  (configuration must be set before import)
from database import engine  # noqa: E402


def cleanup_database() -> None:
    engine.dispose()
    if os.path.exists(_database.name):
        os.unlink(_database.name)


atexit.register(cleanup_database)


def main() -> None:
    app = create_app(serve_react=True)
    client = app.test_client()

    page = client.get("/")
    assert page.status_code == 200, page.status_code
    assert page.mimetype == "text/html", page.mimetype
    html = page.get_data(as_text=True)
    assert '<div id="root"></div>' in html, "React mount point is missing"

    javascript = re.search(r'<script[^>]+src="([^"]+\.js)"', html)
    stylesheet = re.search(r'<link[^>]+href="([^"]+\.css)"', html)
    assert javascript is not None, "Built JavaScript bundle is not linked"
    assert stylesheet is not None, "Built stylesheet is not linked"

    js_response = client.get(javascript.group(1))
    css_response = client.get(stylesheet.group(1))
    assert js_response.status_code == 200, "Built JavaScript bundle was not served"
    assert css_response.status_code == 200, "Built stylesheet was not served"
    bundle = js_response.get_data(as_text=True)
    assert "/api/account" in bundle, "React bundle does not contain the same-origin API client"

    # These calls use the same origin/base path as React's relative fetch URLs.
    for endpoint in ("/api/account", "/api/portfolio", "/api/watchlist"):
        response = client.get(endpoint)
        assert response.status_code == 200, f"{endpoint} returned {response.status_code}"
        assert response.is_json, f"{endpoint} did not return JSON"

    search = client.post("/api/stocks/search", json={"query": "Tata", "limit": 5})
    assert search.status_code == 200 and search.get_json().get("results") is not None
    unknown_api = client.get("/api/no-such-route")
    assert unknown_api.status_code == 404 and unknown_api.is_json
    assert unknown_api.get_json().get("error", {}).get("code") == "NOT_FOUND"
    print("React production assets and Flask API routes are available from one origin.")
    engine.dispose()


if __name__ == "__main__":
    main()

