import {
  StockSummary,
  WatchlistItem,
  PortfolioSummary,
  AccountSummary,
  Order,
  Transaction,
  NewsArticle,
  ResearchSuggestion,
} from '../types/api';

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const headers = {
    'Content-Type': 'application/json',
    ...(options.headers || {}),
  };

  const response = await fetch(endpoint, {
    ...options,
    headers,
  });

  let data: any;
  try {
    data = await response.json();
  } catch (err) {
    throw new Error('Invalid JSON response from server');
  }

  if (!response.ok) {
    const errorMsg = data?.error?.message || `Request failed with status ${response.status}`;
    const error = new Error(errorMsg);
    (error as any).code = data?.error?.code;
    (error as any).field = data?.error?.field;
    throw error;
  }

  return data as T;
}

export const api = {
  // Stocks & Search
  searchStocks: async (query: string, limit = 20): Promise<StockSummary[]> => {
    const data = await request<{ results: StockSummary[] }>('/api/stocks/search', {
      method: 'POST',
      body: JSON.stringify({ query, limit }),
    });
    return data.results;
  },

  // Watchlist
  getWatchlist: async (): Promise<WatchlistItem[]> => {
    const data = await request<{ items: WatchlistItem[] }>('/api/watchlist');
    return data.items;
  },

  addToWatchlist: async (symbol: string): Promise<{ item: WatchlistItem; created: boolean }> => {
    return request<{ item: WatchlistItem; created: boolean }>('/api/watchlist', {
      method: 'POST',
      body: JSON.stringify({ symbol }),
    });
  },

  removeFromWatchlist: async (symbol: string): Promise<{ symbol: string; removed: boolean }> => {
    return request<{ symbol: string; removed: boolean }>(`/api/watchlist/${encodeURIComponent(symbol)}`, {
      method: 'DELETE',
    });
  },

  // Account & Portfolio
  getAccount: async (): Promise<AccountSummary> => {
    return request<AccountSummary>('/api/account');
  },

  getPortfolio: async (): Promise<PortfolioSummary> => {
    return request<PortfolioSummary>('/api/portfolio');
  },

  // Orders & Trading
  placeOrder: async (data: {
    symbol: string;
    side: 'BUY' | 'SELL';
    quantity: number;
    order_type?: 'MARKET';
    idempotency_key?: string;
  }): Promise<{ order: Order; holding: any; account: AccountSummary; transaction: Transaction | null }> => {
    return request<any>('/api/orders', {
      method: 'POST',
      body: JSON.stringify({
        ...data,
        order_type: data.order_type || 'MARKET',
        idempotency_key:
          data.idempotency_key || `react-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
      }),
    });
  },

  getOrders: async (): Promise<Order[]> => {
    const data = await request<{ items: Order[] }>('/api/orders');
    return data.items;
  },

  getTransactions: async (): Promise<Transaction[]> => {
    const data = await request<{ items: Transaction[] }>('/api/transactions');
    return data.items;
  },

  // News & AI Research
  getNews: async (scope: 'personal' | 'market' = 'personal', query = ''): Promise<NewsArticle[]> => {
    const params = new URLSearchParams({ scope });
    if (query.trim()) params.append('query', query.trim());
    params.append('page_size', '20');

    const data = await request<{ items: NewsArticle[] }>(`/api/news?${params.toString()}`);
    return data.items;
  },

  summarizeArticle: async (articleId: string): Promise<any> => {
    return request<any>(`/api/news/${encodeURIComponent(articleId)}/summary`, {
      method: 'POST',
    });
  },

  getResearch: async (symbol: string): Promise<ResearchSuggestion> => {
    return request<ResearchSuggestion>('/api/research/suggestions', {
      method: 'POST',
      body: JSON.stringify({ symbol }),
    });
  },
};

