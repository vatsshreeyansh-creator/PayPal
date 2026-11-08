# TradePoint Research Workspace

TradePoint is a Flask/SQLAlchemy/SQLite backend with a React/TypeScript frontend. The backend owns account, portfolio, order, watchlist, news, and research data. Market, news, and LLM providers default to deterministic mocks; orders update only the local paper account and never submit broker orders.

## Development startup

Install the Python and frontend dependencies once:

```powershell
py -m pip install -r requirements.txt
npm ci --prefix frontend
```

Run these in separate terminals from the repository root:

```powershell
py app.py
```

```powershell
npm run frontend:dev
```

Open <http://localhost:5173>. Vite serves React with hot reload and proxies relative `/api/...` requests to Flask at `http://127.0.0.1:5000`. Flask's `/` remains the legacy Jinja page during development; it is also available at `/legacy`.

## Production startup

Build the React application, install the Python dependencies, and start Flask through Waitress:

```powershell
npm ci --prefix frontend
npm run frontend:build
py -m pip install -r requirements.txt
$env:TRADEPOINT_SERVE_REACT = "true"
waitress-serve --call --listen=0.0.0.0:5000 app:create_app
```

Flask serves `frontend/dist/index.html` at `/` and the built files (including `/assets/...`) from that directory. The React app calls relative `/api/...` URLs, so the browser uses the same Flask origin in production; no Vite proxy or CORS configuration is needed. Startup fails with a clear error if React serving is enabled but `frontend/dist/index.html` is missing. Set `TRADEPOINT_SERVE_REACT=false` to use the legacy Jinja page instead.

For a deployment, configure a persistent `TRADEPOINT_DATABASE_URL`, a non-development `TRADEPOINT_SECRET_KEY`, and an HTTPS reverse proxy in front of Waitress. The included command is a WSGI application server, but TLS termination, domain/DNS, process supervision, and database backups are deployment responsibilities.

Configuration variables include `TRADEPOINT_DATABASE_URL`, `TRADEPOINT_DEMO_USER_ID`, `TRADEPOINT_INITIAL_CASH` (default `1000000.00` INR), `TRADEPOINT_SECRET_KEY`, and `TRADEPOINT_SERVE_REACT`. Initial cash is used only when the account is first created; changing the setting does not reset an existing account. Authentication and multiple user accounts are not implemented.

## Frontend/backend architecture

React/Vite is the primary product frontend. It calls Flask JSON endpoints only; it does not access SQLAlchemy or providers directly. Flask validates API requests with Pydantic, calls module-level services, and reads/writes through SQLAlchemy. Market/news/LLM adapters sit behind normalized provider interfaces. In development, Vite proxies `/api` to Flask; in production, Flask serves the Vite build and those same relative API calls return to Flask on the same origin.

Vite's production output is `frontend/dist/` (ignored by Git and recreated by `npm run frontend:build`). The legacy Jinja implementation remains available at `/legacy` and at `/` when `TRADEPOINT_SERVE_REACT` is false.

## JSON API

- `POST /api/stocks/search` — `{"query":"Tata","limit":20}`
- `POST /api/watchlist` — `{"symbol":"TCS"}` (201 new, 200 duplicate)
- `GET /api/watchlist`
- `DELETE /api/watchlist/TCS`
- `GET /api/account`
- `GET /api/portfolio`
- `POST /api/orders` — immediate simulated MARKET buy/sell
- `GET /api/orders` and `GET /api/orders/{order_id}`
- `GET /api/transactions`
- `GET /api/news?scope=personal&page_size=20` — paginated stock-relevant feed; use `scope=market` for general news
- `GET /api/news/{article_id}`
- `POST /api/news/{article_id}/summary`
- `POST /api/research/suggestions` — `{"symbol":"TCS"}`

Errors use `{"error":{"code":"...","message":"...","field":null}}`. Monetary API values are decimal strings with two fractional digits. Unavailable quotes and article content are represented as `null`.

## Verification and CI

Run from the repository root after installing both npm lockfiles and Python requirements:

```powershell
npm run frontend:build
npm run check
npm run frontend:test
npm run frontend:lint
py scripts/check_frontend_runtime.py
```

`npm run check` checks generated OpenAPI/TypeScript artifacts and runs backend contract/integration tests. The frontend test command runs API response fixtures; the build type-checks and bundles React; lint runs Oxlint. The runtime smoke check verifies Flask serves the built page and assets and that the Flask API remains reachable at the same origin. GitHub Actions runs these checks on pushes and pull requests. Use `npm run contracts:types` only to intentionally regenerate API artifacts after an approved contract change; CI checks them without rewriting committed files.

Historical pricing and daily portfolio performance remain placeholders because no historical-price API exists. Production Kite, news, and LLM adapters are not included.
