import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from './api';
import { createOrderIntentKey } from '../utils/orderIntent';
import type {
  AccountSummary, NewsArticle, NewsSearchResponse, OrderRequest, OrderResponse,
  PortfolioSummary, ResearchResponse, SummaryResponse,
} from '../types/api';

const stock = { symbol: 'TCS', name: 'Tata Consultancy Services', exchange: 'NSE', instrument_token: 123 } as const;
const account: AccountSummary = { account_id: 'demo', currency: 'INR', cash_balance: '1000000.00' };
const portfolio: PortfolioSummary = { account, holdings: [], total_portfolio_value: '1000000.00' };
const filledOrder: OrderResponse = {
  order_id: 'order-1', symbol: 'TCS', side: 'BUY', quantity: 2, order_type: 'MARKET',
  status: 'FILLED', execution_price: '3865.25', rejection_reason: null, currency: 'INR',
  created_at: '2026-11-08T10:00:00Z',
};
const rejectedOrder: OrderResponse = {
  ...filledOrder, order_id: 'order-2', status: 'REJECTED', execution_price: null,
  rejection_reason: 'INSUFFICIENT_CASH',
};
const article: NewsArticle = {
  article_id: 'article-1', title: 'TCS update', source: 'Mock News', url: 'https://example.test/tcs',
  published_at: '2026-11-08T09:00:00Z', summary: null, symbols: ['TCS'], content: null,
};
const news: NewsSearchResponse = { articles: [article], scope: 'personal', next_page_token: 'page-2' };
const summary: SummaryResponse = {
  article_id: article.article_id, summary: 'A concise summary.', key_developments: ['A reported change'],
  reported_facts: ['The article reports a new contract.'], positive_implications: ['Potential revenue growth.'],
  negative_implications: ['Execution risk.'], disclaimer: 'Informational only.', provider: 'mock-llm',
};
const research: ResearchResponse = {
  suggestions: [{ symbol: 'TCS', provider: 'mock-llm', thesis: 'A cautious thesis.', risks: ['Competition'],
    evidence_article_ids: ['article-1'], generated_at: '2026-11-08T10:00:00Z',
    reported_facts: ['A reported fact'], positive_implications: ['Potential benefit'],
    negative_implications: ['Potential downside'], uncertainty: 'Evidence is limited.', informational_only: true }],
  disclaimer: 'Not investment advice.',
};
const conversation = {
  conversation_id: 'conversation-1', context_type: 'article' as const, context_reference: 'article-1',
  context_title: 'TCS update', created_at: '2026-11-10T10:00:00Z',
  messages: [{ role: 'user' as const, content: 'Why did margins decline?', provider: null, created_at: '2026-11-10T10:01:00Z' },
    { role: 'assistant' as const, content: 'The report says costs rose.', provider: 'mock-llm', created_at: '2026-11-10T10:01:01Z' }],
};
function stubJson(body: unknown, status = 200) {
  const fetchMock = vi.fn<typeof fetch>().mockImplementation(async () => new Response(JSON.stringify(body), {
    status, headers: { 'Content-Type': 'application/json' },
  }));
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe('React API contract', () => {
  it('parses the actual search, watchlist add, and delete schemas', async () => {
    stubJson({ results: [stock] });
    expect(await api.searchStocks('Tata')).toEqual([stock]);

    stubJson({ items: [{ stock, quote: null }] });
    expect(await api.getWatchlist()).toEqual([{ stock, quote: null }]);
    stubJson({ item: { stock, quote: null }, created: true });
    expect((await api.addToWatchlist('TCS')).created).toBe(true);
    stubJson({ symbol: 'TCS', deleted: true });
    expect(await api.removeFromWatchlist('TCS')).toEqual({ symbol: 'TCS', deleted: true });
  });

  it('parses backend account and portfolio fields including nullable values', async () => {
    stubJson(account);
    expect(await api.getAccount()).toEqual(account);
    stubJson({ ...portfolio, total_portfolio_value: null, holdings: [{
      symbol: 'TCS', name: stock.name, quantity: '2', average_purchase_price: '3865.25',
      current_price: null, market_value: null, realized_pnl: '0.00', unrealized_pnl: null, currency: 'INR',
    }] });
    const result = await api.getPortfolio();
    expect(result.total_portfolio_value).toBeNull();
    expect(result.holdings[0].current_price).toBeNull();
  });

  it('parses both successful and business-rejected order responses', async () => {
    stubJson(filledOrder, 201);
    expect(await api.placeOrder({ symbol: 'TCS', side: 'BUY', quantity: 2, order_type: 'MARKET', idempotency_key: 'intent-1' })).toEqual(filledOrder);
    stubJson(rejectedOrder, 201);
    const result = await api.placeOrder({ symbol: 'TCS', side: 'BUY', quantity: 2, order_type: 'MARKET', idempotency_key: 'intent-2' });
    expect(result.status).toBe('REJECTED');
    expect(result.execution_price).toBeNull();
    expect(result.rejection_reason).toBe('INSUFFICIENT_CASH');
  });

  it('reuses the caller-provided idempotency key for an identical retry', async () => {
    const fetchMock = stubJson(filledOrder);
    const request: OrderRequest = { symbol: 'TCS', side: 'BUY', quantity: 2, order_type: 'MARKET', idempotency_key: 'same-intent-key' };
    await api.placeOrder(request);
    await api.placeOrder(request);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    for (const [, init] of fetchMock.mock.calls) {
      const body: unknown = JSON.parse(String(init?.body));
      expect(body).toEqual(request);
    }
  });

  it('generates a distinct idempotency key for a new order intent', () => {
    expect(createOrderIntentKey()).not.toBe(createOrderIntentKey());
  });

  it('accepts empty raw order and transaction arrays', async () => {
    stubJson([]);
    expect(await api.getOrders()).toEqual([]);
    stubJson([]);
    expect(await api.getTransactions()).toEqual([]);
  });

  it('consumes the news envelope and handles missing article content', async () => {
    stubJson(news);
    expect(await api.getNews('personal')).toEqual(news);
    stubJson(article);
    const articleDetails = await api.getArticle(article.article_id);
    expect(articleDetails).toEqual(article);
    expect(articleDetails.content).toBeNull();
  });

  it('parses the full summary and research response structures', async () => {
    stubJson(summary);
    expect(await api.summarizeArticle(article.article_id)).toEqual(summary);
    stubJson(research);
    const result = await api.getResearch('TCS');
    expect(result.suggestions[0].evidence_article_ids).toEqual(['article-1']);
    expect(result.disclaimer).toBe('Not investment advice.');
  });

  it('creates, restores, and continues a context-pinned conversation', async () => {
    const fetchMock = stubJson(conversation, 201);
    const created = await api.createConversation({ context_type: 'article', article_id: 'article-1', symbol: null, research_context: null });
    expect(created).toEqual(conversation);
    expect(fetchMock.mock.calls[0][0]).toBe('/api/conversations');
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({ context_type: 'article', article_id: 'article-1', symbol: null, research_context: null });

    stubJson(conversation);
    expect(await api.getConversation(conversation.conversation_id)).toEqual(conversation);
    const messageFetch = stubJson({ ...conversation, messages: [...conversation.messages,
      { role: 'user', content: 'Is that serious?', provider: null, created_at: '2026-11-10T10:02:00Z' }] });
    await api.sendConversationMessage(conversation.conversation_id, '00000000-0000-4000-8000-000000000007', 'Is that serious?');
    expect(messageFetch.mock.calls[0][0]).toBe('/api/conversations/conversation-1/messages');
    expect(JSON.parse(String(messageFetch.mock.calls[0][1]?.body))).toEqual({
      request_id: '00000000-0000-4000-8000-000000000007', content: 'Is that serious?',
    });
  });

  it('surfaces standardized API failures and rejects malformed success payloads', async () => {
    stubJson({ error: { code: 'NEWS_PROVIDER_UNAVAILABLE', message: 'News unavailable.', field: null } }, 503);
    await expect(api.getNews()).rejects.toMatchObject({ name: 'ApiError', code: 'NEWS_PROVIDER_UNAVAILABLE', message: 'News unavailable.' });
    stubJson({ items: [] });
    await expect(api.getNews()).rejects.toThrow('does not match the API contract');
  });
});

