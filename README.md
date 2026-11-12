# TradePoint Research Workspace

TradePoint is a Flask/SQLAlchemy/SQLite backend with a React/TypeScript frontend. The backend owns account, portfolio, order, watchlist, news, and research data. Market and news providers default to deterministic mocks; the LLM defaults to Groq outside automated tests. Orders update only the local paper account and never submit broker orders.

## Development startup

Install the Python and frontend dependencies once:

```powershell
py -m pip install -r requirements.txt
npm ci --prefix frontend
```

For local secrets and provider selection, copy `.env.example` to `.env.local` and set `GROQ_API_KEY`. Flask loads `.env.local` from the repository directory at startup without overriding variables already supplied by the shell or deployment host. The example file contains placeholders only; never commit `.env.local`.

Run these in separate terminals from the repository root:

```powershell
py app.py
```

```powershell
npm run frontend:dev
```

Open <http://localhost:5173>. Vite serves the React application with hot reload and proxies relative `/api/...` requests to Flask at `http://127.0.0.1:5000`.

## Production startup

Build the React application, install the Python dependencies, and start Flask through Waitress:

```powershell
npm ci --prefix frontend
npm run frontend:build
py -m pip install -r requirements.txt
waitress-serve --call --listen=0.0.0.0:5000 app:create_app
```

Flask serves `frontend/dist/index.html` at `/` and the built files (including `/assets/...`) from that directory. The React app calls relative `/api/...` URLs, so the browser uses the same Flask origin in production; no Vite proxy or CORS configuration is needed. If the build is missing, `/` returns an actionable 503 response instructing you to run `npm run frontend:build`.

For a deployment, configure a persistent `TRADEPOINT_DATABASE_URL`, a non-development `TRADEPOINT_SECRET_KEY`, and an HTTPS reverse proxy in front of Waitress. The included command is a WSGI application server, but TLS termination, domain/DNS, process supervision, and database backups are deployment responsibilities.

Configuration variables include `TRADEPOINT_DATABASE_URL`, `TRADEPOINT_DEMO_USER_ID`, `TRADEPOINT_INITIAL_CASH` (default `1000000.00` INR), and `TRADEPOINT_SECRET_KEY`. Initial cash is used only when the account is first created; changing the setting does not reset an existing account. Authentication and multiple user accounts are not implemented.

AI uses the configured server-side provider for summaries, stock research and conversations. The default outside tests is `TRADEPOINT_LLM_PROVIDER=groq` with `GROQ_API_KEY`; `TRADEPOINT_GROQ_MODEL` defaults to `openai/gpt-oss-20b`. Production judges should receive these values from the host's secret/configuration settings, not from a checked-in file. The Groq adapter is initialized at Flask startup and makes requests when an AI operation is requested. Missing credentials or provider/model/API failures produce the existing AI-unavailable API error rather than silently substituting heuristic text. `TRADEPOINT_LLM_PROVIDER=composite` is an explicit option that may fall back to configured external providers and then the heuristic provider; every generated result identifies which provider actually answered. `mock` and `heuristic` are explicit non-production modes. Invalid provider names fail during startup.

## Frontend/backend architecture

React/Vite is the primary product frontend. It calls Flask JSON endpoints only; it does not access SQLAlchemy or providers directly. Flask validates API requests with Pydantic, calls module-level services, and reads/writes through SQLAlchemy. Market/news/LLM adapters sit behind normalized provider interfaces. In development, Vite proxies `/api` to Flask; in production, Flask serves the Vite build and those same relative API calls return to Flask on the same origin.

Vite's production output is `frontend/dist/` (ignored by Git and recreated by `npm run frontend:build`). React is the sole frontend and Flask serves the build in production. The Markets view searches NSE equities and obtains available quote information through the existing watchlist API; the order ticket remains embedded in the dashboard and quick-order modal.

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
- `POST /api/conversations` — start article- or research-context AI chat; `GET /api/conversations/{conversation_id}` restores it; `POST /api/conversations/{conversation_id}/messages` adds a follow-up.

Conversation messages require a client-generated UUID `request_id`. Reuse it only for retries of the same question in the same conversation; generate a new UUID for a new question. Replayed requests do not call the LLM again. The backend serializes SQLite conversation writes and sends a bounded prompt: up to 12,000 characters of source context, up to 8,000 characters of recent prior turns, and the latest question in full up to 4,000 characters. Omitted content is marked for the model; complete history remains stored. SQLite writes may wait up to 45 seconds while another provider request generates a response.

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

Historical pricing and daily portfolio performance remain placeholders because no historical-price API exists. Production Kite and news integrations remain deployment-specific; the Groq LLM adapter is available and requires host-provided credentials for live responses.
