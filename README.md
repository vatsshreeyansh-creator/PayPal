# TradePoint Research Workspace

A Flask + SQLAlchemy + SQLite demo with a Jinja/Bootstrap/vanilla-JavaScript frontend. Market data defaults to deterministic mock prices. Orders update only the TradePoint paper account; no broker execution or Kite credentials are used.

## Run locally

### 1. Start the Flask Backend
```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
py app.py
```
Open <http://127.0.0.1:5000>. The SQLite database is created as `tradepoint.db` beside `app.py`.

### 2. Run the Modern React + Vite Frontend
```powershell
npm run frontend:dev
```
Open <http://localhost:5173>. It proxies all `/api/*` calls automatically to the Flask backend running on port 5000.


Configuration: `TRADEPOINT_DATABASE_URL`, `TRADEPOINT_DEMO_USER_ID`, `TRADEPOINT_INITIAL_CASH` (default `1000000.00` INR), and `TRADEPOINT_SECRET_KEY` are optional environment variables. The initial cash value is used only when the account row is first created; changing the environment variable does not reset an existing account. One demo user is used; there is no authentication.

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
- `GET /api/news?scope=personal&page_size=20` — paginated watchlist/holdings news; use `scope=market` for general news
- `GET /api/news/{article_id}`
- `POST /api/news/{article_id}/summary`
- `POST /api/research/suggestions` — `{"symbol":"TCS"}`

Errors use `{"error":{"code":"...","message":"...","field":null}}`. A missing quote is represented by `quote: null`; saved membership remains available if quote retrieval fails. `quote.simulated` is always `true` for the mock provider.

## Data flow

The Flask routes validate API data with Pydantic and call the module-level services. Services use normalized provider interfaces and persist domain data through SQLAlchemy. The frontend is a navigable Jinja-rendered shell and uses fetch/AJAX without full-page reloads. Watchlist, account, portfolio, trading, orders, news, summaries, and research use existing APIs. Historical charts and daily P&L are placeholders because no historical price API exists.

To replace the mock provider later, implement `search_stocks` and `get_quotes` behind the same interface and provide normalized `InstrumentData`/`QuoteData`. Keep Kite field mapping inside that adapter; this MVP deliberately contains no Kite response-field assumptions.

## Contract checks

Install the JS development tool once with `npm install`, then run `npm run check` before merging. It verifies that committed `openapi.json` and `static/api-types.d.ts` match generated output and runs Python contract/integration tests without rewriting files. Use `npm run contracts:types` to intentionally regenerate those artifacts after an agreed API contract change. Do not edit generated artifacts by hand.
