export interface StockSummary {
  symbol: string;
  name: string;
  exchange?: string;
  isin?: string;
  eligible?: boolean;
}

export interface Quote {
  price: string;
  currency: string;
  as_of: string;
  simulated: boolean;
}

export interface WatchlistItem {
  stock: StockSummary;
  quote: Quote | null;
  created_at: string;
}

export interface Holding {
  stock: StockSummary;
  quantity: number;
  average_buy_price: string;
  quote: Quote | null;
  market_value: string | null;
  unrealized_pnl: string | null;
}

export interface PortfolioSummary {
  user_id: string;
  currency: string;
  as_of: string;
  cash: string;
  total_valuation: string | null;
  incomplete: boolean;
  holdings: Holding[];
}

export interface AccountSummary {
  user_id: string;
  cash: string;
  currency: string;
  created_at: string;
  updated_at: string;
}

export interface Order {
  order_id: string;
  user_id: string;
  symbol: string;
  side: 'BUY' | 'SELL';
  quantity: number;
  order_type: 'MARKET';
  status: 'FILLED' | 'REJECTED';
  execution_price: string | null;
  requested_at: string;
  executed_at: string | null;
  failure_code: string | null;
  failure_reason: string | null;
}

export interface Transaction {
  transaction_id: string;
  order_id: string;
  user_id: string;
  symbol: string;
  side: 'BUY' | 'SELL';
  quantity: number;
  price: string;
  gross_amount: string;
  executed_at: string;
}

export interface NewsArticle {
  article_id: string;
  title: string;
  source: string;
  published_at: string;
  url?: string;
  summary?: string;
  sentiment?: 'bullish' | 'bearish' | 'neutral';
  stocks?: string[];
  relevance_reason?: string;
}

export interface ResearchSuggestion {
  symbol: string;
  summary: string;
  key_catalysts: string[];
  uncertainty_notes: string[];
  sources: { title: string; source: string; published_at: string; url?: string }[];
}

export interface ApiError {
  code: string;
  message: string;
  field?: string | null;
}

