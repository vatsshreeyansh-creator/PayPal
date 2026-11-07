"""TradePoint Watchlist Flask API entry point."""
from flask import Flask, jsonify, render_template, request
from pydantic import ValidationError
from werkzeug.exceptions import BadRequest, HTTPException
from config import DEMO_USER_ID, SECRET_KEY
from database import SessionLocal, initialize_database
from provider import MockMarketDataProvider, ProviderUnavailable
from schemas import (AddWatchlistRequest, AddWatchlistResponse, DeleteWatchlistResponse,
                     ErrorResponse, GetWatchlistResponse, SearchRequest, SearchResponse)
from services import StockNotFound, WatchlistItemNotFound, add, list_items, remove, search, seed_instruments


def create_app(provider=None):
    app = Flask(__name__)
    app.config["SECRET_KEY"] = SECRET_KEY
    market_data = provider or MockMarketDataProvider()
    initialize_database()
    with SessionLocal() as session:
        seed_instruments(session, market_data)

    def error(code, message, status, field=None):
        payload = ErrorResponse(error={"code": code, "message": message, "field": field})
        return jsonify(payload.model_dump(mode="json")), status

    def json_body(model):
        if not request.is_json:
            raise ValueError("Request body must be JSON")
        try:
            data = request.get_json()
        except BadRequest as exc:
            raise ValueError("Malformed JSON") from exc
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return model.model_validate(data)

    @app.errorhandler(HTTPException)
    def http_error(exc):
        code, status, message = {
            404: ("NOT_FOUND", 404, "The requested resource was not found."),
            405: ("METHOD_NOT_ALLOWED", 405, "This method is not allowed."),
        }.get(exc.code, ("INTERNAL_ERROR", exc.code or 500, "The request could not be completed."))
        return error(code, message, status)

    @app.errorhandler(Exception)
    def unexpected_error(exc):
        app.logger.exception("Unhandled request error")
        return error("INTERNAL_ERROR", "The request could not be completed.", 500)

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.post("/api/stocks/search")
    def search_stocks():
        try:
            body = json_body(SearchRequest)
        except ValidationError as exc:
            field = str(exc.errors()[0].get("loc", [None])[0]) if exc.errors() else None
            msg = "query must not be empty" if field == "query" else "Search request fields are invalid."
            return error("VALIDATION_ERROR", msg, 400, field)
        except ValueError:
            return error("VALIDATION_ERROR", "Request must be a valid JSON object.", 400)
        try:
            with SessionLocal() as session:
                result = SearchResponse(results=search(session, market_data, body.query, body.limit))
            return jsonify(result.model_dump(mode="json"))
        except ProviderUnavailable:
            return error("PROVIDER_UNAVAILABLE", "Stock search is temporarily unavailable.", 503)
        except Exception:
            app.logger.exception("Stock search failed")
            return error("INTERNAL_ERROR", "The request could not be completed.", 500)

    @app.post("/api/watchlist")
    def add_stock():
        try:
            body = json_body(AddWatchlistRequest)
        except ValidationError as exc:
            field = None
            if exc.errors():
                field = str(exc.errors()[0].get("loc", [None])[0])
            message = "symbol must not be empty" if field == "symbol" else "Add request must contain a valid symbol."
            return error("VALIDATION_ERROR", message, 400, field)
        except ValueError:
            return error("VALIDATION_ERROR", "Request must be a valid JSON object.", 400)
        try:
            with SessionLocal() as session:
                item, created = add(session, market_data, DEMO_USER_ID, body.symbol)
            return jsonify(AddWatchlistResponse(item=item, created=created).model_dump(mode="json")), 201 if created else 200
        except StockNotFound:
            return error("STOCK_NOT_FOUND", "No matching NSE equity was found.", 404, "symbol")
        except ProviderUnavailable:
            return error("PROVIDER_UNAVAILABLE", "Stock lookup is temporarily unavailable.", 503)
        except Exception:
            app.logger.exception("Could not add watchlist stock")
            return error("INTERNAL_ERROR", "The stock could not be added.", 500)

    @app.get("/api/watchlist")
    def get_watchlist():
        try:
            with SessionLocal() as session:
                result = GetWatchlistResponse(items=list_items(session, market_data, DEMO_USER_ID))
            return jsonify(result.model_dump(mode="json"))
        except Exception:
            app.logger.exception("Could not load watchlist")
            return error("INTERNAL_ERROR", "The watchlist could not be loaded.", 500)

    @app.delete("/api/watchlist/<symbol>")
    def delete_stock(symbol):
        symbol = symbol.strip().upper()
        if not 1 <= len(symbol) <= 32:
            return error("VALIDATION_ERROR", "symbol must contain 1 to 32 characters.", 400, "symbol")
        try:
            with SessionLocal() as session:
                remove(session, DEMO_USER_ID, symbol)
            return jsonify(DeleteWatchlistResponse(symbol=symbol).model_dump(mode="json"))
        except WatchlistItemNotFound:
            return error("WATCHLIST_ITEM_NOT_FOUND", "The symbol is not in this watchlist.", 404, "symbol")
        except Exception:
            app.logger.exception("Could not remove watchlist stock")
            return error("INTERNAL_ERROR", "The stock could not be removed.", 500)

    return app


if __name__ == "__main__":
    create_app().run(debug=True)
