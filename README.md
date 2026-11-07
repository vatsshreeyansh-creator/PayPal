# TradePoint Watchlist MVP

A small Flask + SQLAlchemy + SQLite demo. The market data provider is deterministic mock data; **every returned quote is simulated, not live**. No Kite credentials or trading functions are used.

## Run locally

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
py app.py
```

Open <http://127.0.0.1:5000>. The SQLite database is created as `tradepoint.db` beside `app.py`.

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

The Flask routes validate JSON with Pydantic and call `services.py`. The service talks to the provider through `MarketDataProvider` and persists instruments and watchlist membership through SQLAlchemy. The local instrument table is initialized from the mock provider at startup; watchlist membership and the instrument cache persist in SQLite. The template uses fetch/AJAX without full-page reloads.

To replace the mock provider later, implement `search_stocks` and `get_quotes` behind the same interface and provide normalized `InstrumentData`/`QuoteData`. Keep Kite field mapping inside that adapter; this MVP deliberately contains no Kite response-field assumptions.

## Contract checks

Install the JS development tool once with `npm install`, then run `npm run check` before merging. This regenerates `openapi.json` from Pydantic models, regenerates `static/api-types.d.ts`, and runs Python contract/integration tests. Do not edit generated artifacts by hand. The OpenAPI paths list only implemented watchlist routes; account, portfolio, trading, news, summaries, and research currently have reusable schema components only and no live endpoints.
