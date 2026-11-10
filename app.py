"""TradePoint Watchlist Flask API entry point."""
from pathlib import Path
from typing import Any

from flask import Flask, abort, jsonify, request, send_from_directory
from pydantic import ValidationError
from werkzeug.exceptions import BadRequest, HTTPException
from config import DEMO_USER_ID, INITIAL_CASH, SECRET_KEY
from database import SessionLocal, initialize_database
from provider import (
    MarketDataProvider,
    MockMarketDataProvider,
    LiveMarketDataProvider,
    ProviderUnavailable,
    get_default_market_provider,
)
from schemas import (AddWatchlistRequest, AddWatchlistResponse, DeleteWatchlistResponse,
                     ErrorResponse, GetWatchlistResponse, SearchRequest, SearchResponse)
from services import StockNotFound, WatchlistItemNotFound, add, list_items, remove, search, seed_instruments
from portfolio_service import ensure_demo_account, get_account, get_portfolio
from schemas import AccountSummary, PortfolioSummary, OrderRequest, OrderResponse, Transaction
from trading_service import (IdempotencyConflict, OrderNotFound, StockNotFound as TradingStockNotFound,
                             get_order, list_orders, list_transactions, place_order)
from news_provider import NewsProvider, get_default_news_provider
from llm_provider import LLMProvider, get_default_llm_provider
from mock_research_providers import MockLLMProvider, MockNewsProvider
from provider import MarketDataProvider
from schemas import NewsFeedRequest, ResearchRequest
from news_research_service import (ArticleContentUnavailable, ArticleNotFound, NewsUnavailable,
                                   ResearchStockNotFound, ResearchUnavailable, get_article, research_stock, search_news,
                                   summarize_article)


def create_app(provider: MarketDataProvider | None = None,
               news_provider: NewsProvider | None = None,
               llm_provider: LLMProvider | None = None):
    app = Flask(__name__)
    app.config["SECRET_KEY"] = SECRET_KEY
    frontend_dist = Path(__file__).resolve().parent / "frontend" / "dist"
    frontend_index = frontend_dist / "index.html"
    market_data = provider or get_default_market_provider()
    news_data = news_provider or get_default_news_provider()
    llm_data = llm_provider or get_default_llm_provider()
    initialize_database()
    with SessionLocal() as session:
        seed_instruments(session, market_data)
        ensure_demo_account(session, DEMO_USER_ID, INITIAL_CASH)

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
        if not frontend_index.is_file():
            return "React production build is missing. Run `npm run frontend:build` before serving the application.", 503
        return send_from_directory(frontend_dist, "index.html")

    @app.get("/assets/<path:filename>")
    def react_assets(filename):
        return send_from_directory(frontend_dist / "assets", filename)

    @app.get("/<path:filename>")
    def react_public_asset(filename):
        # Only built files are served here. Unknown paths still reach the
        # common 404 handler, so unknown /api paths stay JSON errors.
        if (frontend_dist / filename).is_file():
            return send_from_directory(frontend_dist, filename)
        abort(404)

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

    @app.get("/api/account")
    def get_account_route():
        try:
            with SessionLocal() as session:
                response = AccountSummary.model_validate(get_account(session, DEMO_USER_ID))
            return jsonify(response.model_dump(mode="json"))
        except Exception:
            app.logger.exception("Could not load demo account")
            return error("INTERNAL_ERROR", "The account could not be loaded.", 500)

    @app.get("/api/portfolio")
    def get_portfolio_route():
        try:
            with SessionLocal() as session:
                response = PortfolioSummary.model_validate(get_portfolio(session, market_data, DEMO_USER_ID))
            return jsonify(response.model_dump(mode="json"))
        except Exception:
            app.logger.exception("Could not load portfolio")
            return error("INTERNAL_ERROR", "The portfolio could not be loaded.", 500)

    @app.post("/api/orders")
    def create_order():
        try:
            body = json_body(OrderRequest)
        except (ValidationError, ValueError):
            return error("VALIDATION_ERROR", "Order request fields are invalid.", 400)
        try:
            with SessionLocal() as session:
                result, created = place_order(session, market_data, DEMO_USER_ID, body)
            return jsonify(result.model_dump(mode="json")), 201 if created else 200
        except TradingStockNotFound:
            return error("STOCK_NOT_FOUND", "No matching NSE equity was found.", 404, "symbol")
        except IdempotencyConflict:
            return error("IDEMPOTENCY_CONFLICT", "The idempotency key was already used for a different order.", 409, "idempotency_key")
        except Exception:
            app.logger.exception("Order processing failed")
            return error("INTERNAL_ERROR", "The order could not be processed.", 500)

    @app.get("/api/orders")
    def get_orders():
        try:
            with SessionLocal() as session:
                result = list_orders(session, DEMO_USER_ID)
            return jsonify([item.model_dump(mode="json") for item in result])
        except Exception:
            app.logger.exception("Order history retrieval failed")
            return error("INTERNAL_ERROR", "Orders could not be loaded.", 500)

    @app.get("/api/orders/<order_id>")
    def get_order_route(order_id):
        try:
            with SessionLocal() as session:
                result = get_order(session, DEMO_USER_ID, order_id)
            return jsonify(result.model_dump(mode="json"))
        except OrderNotFound:
            return error("ORDER_NOT_FOUND", "The order was not found.", 404, "order_id")
        except Exception:
            app.logger.exception("Order retrieval failed")
            return error("INTERNAL_ERROR", "The order could not be loaded.", 500)

    @app.get("/api/transactions")
    def get_transactions():
        try:
            with SessionLocal() as session:
                result = list_transactions(session, DEMO_USER_ID)
            return jsonify([item.model_dump(mode="json") for item in result])
        except Exception:
            app.logger.exception("Transaction history retrieval failed")
            return error("INTERNAL_ERROR", "Transactions could not be loaded.", 500)

    @app.get("/api/news")
    def news_feed():
        try:
            params: dict[str, Any] = dict(request.args.to_dict())
            if "symbols" in request.args:
                params["symbols"] = request.args.getlist("symbols")
            feed_request = NewsFeedRequest.model_validate(params)
        except ValidationError:
            return error("VALIDATION_ERROR", "News query parameters are invalid.", 400)
        try:
            with SessionLocal() as session:
                result = search_news(session, news_data, DEMO_USER_ID, feed_request)
            return jsonify(result.model_dump(mode="json"))
        except NewsUnavailable:
            return error("NEWS_PROVIDER_UNAVAILABLE", "News is temporarily unavailable.", 503)
        except Exception:
            app.logger.exception("News feed retrieval failed")
            return error("INTERNAL_ERROR", "News could not be loaded.", 500)

    @app.get("/api/news/<article_id>")
    def news_article(article_id):
        try:
            with SessionLocal() as session:
                result = get_article(session, news_data, article_id)
            return jsonify(result.model_dump(mode="json"))
        except ArticleNotFound:
            return error("ARTICLE_NOT_FOUND", "The article was not found.", 404, "article_id")
        except Exception:
            app.logger.exception("Article retrieval failed")
            return error("INTERNAL_ERROR", "The article could not be loaded.", 500)

    @app.post("/api/news/<article_id>/summary")
    def article_summary(article_id):
        try:
            with SessionLocal() as session:
                result = summarize_article(session, news_data, llm_data, article_id)
            return jsonify(result.model_dump(mode="json"))
        except ArticleNotFound:
            return error("ARTICLE_NOT_FOUND", "The article was not found.", 404, "article_id")
        except ArticleContentUnavailable:
            return error("ARTICLE_CONTENT_UNAVAILABLE", "No article text or summary is available.", 422, "article_id")
        except ResearchUnavailable:
            return error("LLM_PROVIDER_UNAVAILABLE", "Article summarization is temporarily unavailable.", 503)
        except Exception:
            app.logger.exception("Article summary failed")
            return error("INTERNAL_ERROR", "The article could not be summarized.", 500)

    @app.post("/api/research/suggestions")
    def research_suggestions():
        try:
            body = json_body(ResearchRequest)
        except (ValidationError, ValueError):
            return error("VALIDATION_ERROR", "Research request fields are invalid.", 400)
        try:
            with SessionLocal() as session:
                result = research_stock(session, news_data, llm_data, market_data, body)
            return jsonify(result.model_dump(mode="json"))
        except ResearchStockNotFound:
            return error("STOCK_NOT_FOUND", "No matching NSE equity was found.", 404, "symbol")
        except NewsUnavailable:
            return error("NEWS_PROVIDER_UNAVAILABLE", "News evidence is temporarily unavailable.", 503)
        except ResearchUnavailable:
            return error("LLM_PROVIDER_UNAVAILABLE", "Research generation is temporarily unavailable.", 503)
        except Exception:
            app.logger.exception("Research suggestion generation failed")
            return error("INTERNAL_ERROR", "Research suggestions could not be generated.", 500)

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
