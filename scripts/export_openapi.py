"""Export the current HTTP API and all shared Pydantic schemas to OpenAPI."""
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from schemas import (AddWatchlistRequest, AddWatchlistResponse, DeleteWatchlistResponse,
                     ErrorResponse, GetWatchlistResponse, SearchRequest, SearchResponse,
                     AccountSummary, Holding, PortfolioSummary, OrderRequest, OrderResponse,
                     Transaction, NewsArticle, NewsSearchResponse, NewsFeedRequest,
                     SummaryResponse, ResearchSuggestion, ResearchResponse, ResearchRequest)

MODELS = [AddWatchlistRequest, AddWatchlistResponse, DeleteWatchlistResponse, ErrorResponse,
          GetWatchlistResponse, SearchRequest, SearchResponse, AccountSummary, Holding,
          PortfolioSummary, OrderRequest, OrderResponse, Transaction, NewsArticle,
          NewsSearchResponse, NewsFeedRequest, SummaryResponse, ResearchSuggestion, ResearchResponse, ResearchRequest]


def make_spec():
    components = {}
    for model in MODELS:
        generated = model.model_json_schema(ref_template="#/components/schemas/{model}")
        definitions = generated.pop("$defs", {})
        components.update(definitions)
        components[model.__name__] = generated
    ref = lambda name: {"$ref": f"#/components/schemas/{name}"}
    json_content = lambda name: {"application/json": {"schema": ref(name)}}
    error_response = lambda desc: {"description": desc, "content": json_content("ErrorResponse")}
    def responses(success, errors=()):
        # Every live handler can produce the common unexpected-error response;
        # Flask can also reject unsupported methods before entering a handler.
        result = dict(success)
        result["405"] = error_response("Method not allowed")
        result["500"] = error_response("Unexpected server or persistence error")
        for status, description in errors:
            result[str(status)] = error_response(description)
        return result
    paths = {
        "/api/stocks/search": {"post": {
            "operationId": "searchStocks",
            "requestBody": {"required": True, "content": json_content("SearchRequest")},
            "responses": responses({"200": {"description": "Search results", "content": json_content("SearchResponse")}},
                                   [(400, "Invalid request"), (503, "Market-data provider unavailable")])}},
        "/api/watchlist": {
            "get": {"operationId": "getWatchlist", "responses": responses({"200": {"description": "Watchlist", "content": json_content("GetWatchlistResponse")}})},
            "post": {"operationId": "addWatchlist", "requestBody": {"required": True, "content": json_content("AddWatchlistRequest")},
                     "responses": responses({"201": {"description": "Added", "content": json_content("AddWatchlistResponse")},
                                   "200": {"description": "Already present", "content": json_content("AddWatchlistResponse")}},
                                   [(400, "Invalid request"), (404, "Unknown stock"), (503, "Market-data provider unavailable")])}},
        "/api/watchlist/{symbol}": {"delete": {
            "operationId": "removeWatchlist",
            "parameters": [{"name": "symbol", "in": "path", "required": True, "schema": {"type": "string", "minLength": 1, "maxLength": 32}}],
            "responses": responses({"200": {"description": "Deleted", "content": json_content("DeleteWatchlistResponse")}},
                                    [(400, "Invalid symbol"), (404, "Not saved")])}}
    }
    paths.update({
        "/api/account": {"get": {
            "operationId": "getAccount",
            "responses": responses({"200": {"description": "Account summary", "content": json_content("AccountSummary")}})}},
        "/api/portfolio": {"get": {
            "operationId": "getPortfolio",
            "responses": responses({"200": {"description": "Portfolio", "content": json_content("PortfolioSummary")}})}},
        "/api/orders": {
            "post": {"operationId": "placeOrder",
                "requestBody": {"required": True, "content": json_content("OrderRequest")},
                "responses": responses({"201": {"description": "Order processed", "content": json_content("OrderResponse")},
                              "200": {"description": "Idempotent replay", "content": json_content("OrderResponse")},
                              }, [(400, "Invalid order"), (404, "Unknown stock"), (409, "Idempotency key conflict")])},
            "get": {"operationId": "listOrders",
                "responses": responses({"200": {"description": "Order history", "content": {"application/json": {"schema": {"type": "array", "items": ref("OrderResponse")}}}}})}},
        "/api/orders/{order_id}": {"get": {"operationId": "getOrder",
            "parameters": [{"name": "order_id", "in": "path", "required": True, "schema": {"type": "string"}}],
            "responses": responses({"200": {"description": "Order", "content": json_content("OrderResponse")}}, [(404, "Order not found")])}},
        "/api/transactions": {"get": {"operationId": "listTransactions",
            "responses": responses({"200": {"description": "Transactions", "content": {"application/json": {"schema": {"type": "array", "items": ref("Transaction")}}}}})}},
        "/api/news": {"get": {"operationId": "searchNews",
            "parameters": [{"name": "scope", "in": "query", "required": False, "schema": {"type": "string", "enum": ["personal", "market"], "default": "personal"}},
                           {"name": "query", "in": "query", "required": False, "schema": {"type": "string", "maxLength": 200}},
                           {"name": "symbols", "in": "query", "required": False, "schema": {"type": "array", "items": {"type": "string"}}},
                           {"name": "page_token", "in": "query", "required": False, "schema": {"type": "string"}},
                           {"name": "page_size", "in": "query", "required": False, "schema": {"type": "integer", "default": 20, "minimum": 1, "maximum": 50}}],
            "responses": responses({"200": {"description": "News results", "content": json_content("NewsSearchResponse")}},
                                   [(400, "Invalid query"), (503, "News provider unavailable")])}},
        "/api/news/{article_id}": {"get": {"operationId": "getNewsArticle",
            "parameters": [{"name": "article_id", "in": "path", "required": True, "schema": {"type": "string"}}],
            "responses": responses({"200": {"description": "Article; content may be null", "content": json_content("NewsArticle")}}, [(404, "Article not found")])}},
        "/api/news/{article_id}/summary": {"post": {"operationId": "summarizeArticle",
            "parameters": [{"name": "article_id", "in": "path", "required": True, "schema": {"type": "string"}}],
            "responses": responses({"200": {"description": "Summary", "content": json_content("SummaryResponse")}},
                                   [(404, "Article not found"), (422, "Article content unavailable"), (503, "LLM unavailable")])}},
        "/api/research/suggestions": {"post": {"operationId": "getResearchSuggestions",
            "requestBody": {"required": True, "content": json_content("ResearchRequest")},
            "responses": responses({"200": {"description": "Research suggestions", "content": json_content("ResearchResponse")}},
                                   [(400, "Invalid request"), (404, "Unknown stock"), (503, "News or LLM provider unavailable")])}}
    })
    return {"openapi": "3.1.0", "info": {"title": "TradePoint API", "version": "0.1.0"},
            "paths": paths, "components": {"schemas": components}}


if __name__ == "__main__":
    (ROOT / "openapi.json").write_text(json.dumps(make_spec(), indent=2) + "\n", encoding="utf-8")
