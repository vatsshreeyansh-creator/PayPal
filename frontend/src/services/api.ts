import type {
  AccountSummary,
  AddWatchlistResponse,
  DeleteWatchlistResponse,
  ErrorResponse,
  NewsArticle,
  NewsSearchResponse,
  OrderRequest,
  OrderResponse,
  PortfolioSummary,
  ResearchResponse,
  SearchResponse,
  StockSummary,
  SummaryResponse,
  Transaction,
  WatchlistItem,
} from '../types/api';

export class ApiError extends Error {
  constructor(message: string, readonly code?: string, readonly field?: string | null) {
    super(message);
    this.name = 'ApiError';
  }
}

type Guard<T> = (value: unknown) => value is T;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isString(value: unknown): value is string {
  return typeof value === 'string';
}

function isNullableString(value: unknown): value is string | null {
  return value === null || isString(value);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isString);
}

function isMoney(value: unknown): value is string {
  return isString(value) && /^(?:0|[1-9]\d*)\.\d{2}$/.test(value);
}

function isSignedMoney(value: unknown): value is string {
  return isString(value) && /^-?(?:0|[1-9]\d*)\.\d{2}$/.test(value);
}

function isStock(value: unknown): value is StockSummary {
  return isRecord(value) && isString(value.symbol) && isString(value.name) &&
    value.exchange === 'NSE' && Number.isInteger(value.instrument_token) &&
    Number(value.instrument_token) > 0;
}

function isQuote(value: unknown): boolean {
  return isRecord(value) && isMoney(value.price) && value.price !== '0.00' && value.currency === 'INR' &&
    isString(value.as_of) && typeof value.simulated === 'boolean';
}

function isWatchlistItem(value: unknown): value is WatchlistItem {
  return isRecord(value) && isStock(value.stock) &&
    (value.quote === null || isQuote(value.quote));
}

function isAccount(value: unknown): value is AccountSummary {
  return isRecord(value) && isString(value.account_id) && value.currency === 'INR' &&
    isMoney(value.cash_balance);
}

function isHolding(value: unknown): boolean {
  return isRecord(value) && isString(value.symbol) && isString(value.name) &&
    isString(value.quantity) && /^[1-9]\d*$/.test(value.quantity) && isMoney(value.average_purchase_price) &&
    (value.current_price === null || (isMoney(value.current_price) && value.current_price !== '0.00')) &&
    (value.market_value === null || isMoney(value.market_value)) &&
    isSignedMoney(value.realized_pnl) && (value.unrealized_pnl === null || isSignedMoney(value.unrealized_pnl)) &&
    value.currency === 'INR';
}

function isPortfolio(value: unknown): value is PortfolioSummary {
  return isRecord(value) && isAccount(value.account) && Array.isArray(value.holdings) &&
    value.holdings.every(isHolding) && (value.total_portfolio_value === null || isMoney(value.total_portfolio_value));
}

function isOrder(value: unknown): value is OrderResponse {
  if (!isRecord(value) || !isString(value.order_id) || !isString(value.symbol) ||
    (value.side !== 'BUY' && value.side !== 'SELL') || !Number.isInteger(value.quantity) ||
    value.order_type !== 'MARKET' || (value.status !== 'FILLED' && value.status !== 'REJECTED') ||
    (value.execution_price !== null && !isMoney(value.execution_price)) ||
    (value.rejection_reason !== null && value.rejection_reason !== 'INSUFFICIENT_CASH' &&
      value.rejection_reason !== 'INSUFFICIENT_SHARES' && value.rejection_reason !== 'QUOTE_UNAVAILABLE') ||
    value.currency !== 'INR' || !isString(value.created_at)) return false;
  return value.status === 'FILLED'
    ? value.execution_price !== null && value.rejection_reason === null
    : value.execution_price === null && value.rejection_reason !== null;
}

function isTransaction(value: unknown): value is Transaction {
  return isRecord(value) && isString(value.transaction_id) && isString(value.order_id) &&
    isString(value.symbol) && (value.side === 'BUY' || value.side === 'SELL') &&
    isString(value.quantity) && /^[1-9]\d*$/.test(value.quantity) && isMoney(value.price) && isMoney(value.gross_amount) &&
    value.currency === 'INR' && isString(value.occurred_at);
}

function isArticle(value: unknown): value is NewsArticle {
  return isRecord(value) && isString(value.article_id) && isString(value.title) &&
    isString(value.source) && isString(value.url) && isString(value.published_at) &&
    isNullableString(value.summary) && isStringArray(value.symbols) &&
    isNullableString(value.content);
}

function isNewsResponse(value: unknown): value is NewsSearchResponse {
  return isRecord(value) && Array.isArray(value.articles) && value.articles.every(isArticle) &&
    (value.scope === 'personal' || value.scope === 'market') &&
    isNullableString(value.next_page_token);
}

function isSummary(value: unknown): value is SummaryResponse {
  return isRecord(value) && isString(value.article_id) && isString(value.summary) &&
    isStringArray(value.key_developments) && isStringArray(value.reported_facts) &&
    isStringArray(value.positive_implications) && isStringArray(value.negative_implications) &&
    isString(value.disclaimer) && isString(value.provider);
}

function isResearch(value: unknown): value is ResearchResponse {
  if (!isRecord(value) || !Array.isArray(value.suggestions) || !isString(value.disclaimer)) return false;
  return value.suggestions.every((suggestion) => isRecord(suggestion) &&
    isString(suggestion.symbol) && isString(suggestion.thesis) && isStringArray(suggestion.risks) &&
    isStringArray(suggestion.evidence_article_ids) && isString(suggestion.generated_at) &&
    isStringArray(suggestion.reported_facts) && isStringArray(suggestion.positive_implications) &&
    isStringArray(suggestion.negative_implications) && isString(suggestion.uncertainty) &&
    suggestion.informational_only === true);
}

function isSearch(value: unknown): value is SearchResponse {
  return isRecord(value) && Array.isArray(value.results) && value.results.every(isStock);
}

function isWatchlist(value: unknown): value is { items: WatchlistItem[] } {
  return isRecord(value) && Array.isArray(value.items) && value.items.every(isWatchlistItem);
}

function isAddWatchlist(value: unknown): value is AddWatchlistResponse {
  return isRecord(value) && isWatchlistItem(value.item) && typeof value.created === 'boolean';
}

function isDeleteWatchlist(value: unknown): value is DeleteWatchlistResponse {
  return isRecord(value) && isString(value.symbol) && value.deleted === true;
}

function isErrorResponse(value: unknown): value is ErrorResponse {
  return isRecord(value) && isRecord(value.error) && isString(value.error.code) &&
    isString(value.error.message) && isNullableString(value.error.field);
}

async function request<T>(endpoint: string, guard: Guard<T>, options: RequestInit = {}): Promise<T> {
  const response = await fetch(endpoint, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  });

  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new ApiError('Invalid JSON response from server');
  }

  if (!response.ok) {
    if (isErrorResponse(data)) {
      throw new ApiError(data.error.message, data.error.code, data.error.field);
    }
    throw new ApiError(`Request failed with status ${response.status}`);
  }
  if (!guard(data)) throw new ApiError('The server returned a response that does not match the API contract.');
  return data;
}

const isOrderList: Guard<OrderResponse[]> = (value): value is OrderResponse[] =>
  Array.isArray(value) && value.every(isOrder);
const isTransactionList: Guard<Transaction[]> = (value): value is Transaction[] =>
  Array.isArray(value) && value.every(isTransaction);

export const api = {
  searchStocks: async (query: string, limit = 20): Promise<StockSummary[]> =>
    (await request('/api/stocks/search', isSearch, {
      method: 'POST', body: JSON.stringify({ query, limit }),
    })).results,

  getWatchlist: async (): Promise<WatchlistItem[]> =>
    (await request('/api/watchlist', isWatchlist)).items,

  addToWatchlist: (symbol: string): Promise<AddWatchlistResponse> =>
    request('/api/watchlist', isAddWatchlist, { method: 'POST', body: JSON.stringify({ symbol }) }),

  removeFromWatchlist: (symbol: string): Promise<DeleteWatchlistResponse> =>
    request(`/api/watchlist/${encodeURIComponent(symbol)}`, isDeleteWatchlist, { method: 'DELETE' }),

  getAccount: (): Promise<AccountSummary> => request('/api/account', isAccount),
  getPortfolio: (): Promise<PortfolioSummary> => request('/api/portfolio', isPortfolio),

  placeOrder: (data: OrderRequest): Promise<OrderResponse> =>
    request('/api/orders', isOrder, { method: 'POST', body: JSON.stringify(data) }),

  getOrders: (): Promise<OrderResponse[]> => request('/api/orders', isOrderList),
  getTransactions: (): Promise<Transaction[]> => request('/api/transactions', isTransactionList),

  getNews: (scope: 'personal' | 'market' = 'personal', query = '', pageToken?: string): Promise<NewsSearchResponse> => {
    const params = new URLSearchParams({ scope, page_size: '20' });
    if (query.trim()) params.set('query', query.trim());
    if (pageToken) params.set('page_token', pageToken);
    return request(`/api/news?${params.toString()}`, isNewsResponse);
  },

  getArticle: (articleId: string): Promise<NewsArticle> =>
    request(`/api/news/${encodeURIComponent(articleId)}`, isArticle),

  summarizeArticle: (articleId: string): Promise<SummaryResponse> =>
    request(`/api/news/${encodeURIComponent(articleId)}/summary`, isSummary, { method: 'POST' }),

  getResearch: (symbol: string): Promise<ResearchResponse> =>
    request('/api/research/suggestions', isResearch, { method: 'POST', body: JSON.stringify({ symbol }) }),
};

