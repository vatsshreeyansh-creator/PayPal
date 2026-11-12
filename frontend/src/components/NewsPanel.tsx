import React, { useState } from 'react';
import { Newspaper, Sparkles, ExternalLink, ChevronDown, ChevronUp, Loader2, Filter, FileText } from 'lucide-react';
import type { NewsArticle, NewsSearchResponse, SummaryResponse } from '../types/api';
import { formatRelativeTime } from '../utils/format';
import { api } from '../services/api';
import { ConversationPanel } from './ConversationPanel';

interface NewsPanelProps {
  news: NewsSearchResponse | null;
  loading: boolean;
  error: string | null;
  scope: 'personal' | 'market';
  onScopeChange: (scope: 'personal' | 'market') => void;
  onFilterChange: (query: string) => void;
  onLoadMore: (pageToken: string) => void;
  onResearchStock: (symbol: string) => void;
}

type SummaryState = { loading: boolean; data?: SummaryResponse; error?: string };
type ArticleState = { loading: boolean; data?: NewsArticle; error?: string };

export const NewsPanel: React.FC<NewsPanelProps> = ({ news, loading, error, scope, onScopeChange, onFilterChange, onLoadMore, onResearchStock }) => {
  const [filterQuery, setFilterQuery] = useState('');
  const [summaries, setSummaries] = useState<Record<string, SummaryState>>({});
  const [articles, setArticles] = useState<Record<string, ArticleState>>({});
  const [expandedSummary, setExpandedSummary] = useState<string | null>(null);
  const [expandedArticle, setExpandedArticle] = useState<string | null>(null);

  const toggleSummary = async (articleId: string) => {
    if (expandedSummary === articleId) { setExpandedSummary(null); return; }
    setExpandedSummary(articleId);
    if (summaries[articleId]?.data || summaries[articleId]?.loading) return;
    setSummaries((previous) => ({ ...previous, [articleId]: { loading: true } }));
    try {
      const data = await api.summarizeArticle(articleId);
      setSummaries((previous) => ({ ...previous, [articleId]: { loading: false, data } }));
    } catch (requestError: unknown) {
      setSummaries((previous) => ({ ...previous, [articleId]: { loading: false, error: requestError instanceof Error ? requestError.message : 'Summary request failed.' } }));
    }
  };

  const toggleArticle = async (articleId: string) => {
    if (expandedArticle === articleId) { setExpandedArticle(null); return; }
    setExpandedArticle(articleId);
    if (articles[articleId]?.data || articles[articleId]?.loading) return;
    setArticles((previous) => ({ ...previous, [articleId]: { loading: true } }));
    try {
      const data = await api.getArticle(articleId);
      setArticles((previous) => ({ ...previous, [articleId]: { loading: false, data } }));
    } catch (requestError: unknown) {
      setArticles((previous) => ({ ...previous, [articleId]: { loading: false, error: requestError instanceof Error ? requestError.message : 'Article request failed.' } }));
    }
  };

  const articlesInFeed = news?.articles ?? [];
  const summary = expandedSummary ? summaries[expandedSummary] : undefined;
  const articleDetail = expandedArticle ? articles[expandedArticle] : undefined;

  return <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-2xl">
    <div className="flex flex-wrap items-center justify-between gap-4 pb-4 border-b border-slate-800 mb-4">
      <div className="flex items-center gap-2"><Newspaper className="w-5 h-5 text-indigo-400" /><h2 className="text-lg font-bold text-white">Market Intelligence &amp; News</h2></div>
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex gap-1 bg-slate-950 p-1 rounded-xl border border-slate-800">
          {(['personal', 'market'] as const).map((value) => <button key={value} onClick={() => onScopeChange(value)} className={`px-3 py-1.5 rounded-lg text-xs font-semibold ${scope === value ? 'bg-indigo-600 text-white' : 'text-slate-400'}`}>{value === 'personal' ? 'My Stocks' : 'Indian Equities'}</button>)}
        </div>
        <form onSubmit={(event) => { event.preventDefault(); onFilterChange(filterQuery); }} className="flex gap-1.5">
          <input value={filterQuery} onChange={(event) => setFilterQuery(event.target.value)} placeholder="Filter headlines…" className="bg-slate-950 border border-slate-800 rounded-xl px-3 py-1.5 text-xs text-white" />
          <button type="submit" className="p-2 bg-slate-800 text-slate-300 rounded-xl" title="Apply filter"><Filter className="w-3.5 h-3.5" /></button>
        </form>
      </div>
    </div>
    {loading && <p role="status" className="py-8 text-center text-slate-400"><Loader2 className="inline w-4 h-4 animate-spin mr-2" />Fetching news…</p>}
    {error && <p role="alert" className="mb-4 p-3 rounded-xl bg-rose-500/10 text-rose-300 text-sm">{error}</p>}
    {!loading && !error && articlesInFeed.length === 0 && <p className="py-8 text-center text-slate-400">No articles found.</p>}
    <div className="space-y-3">{articlesInFeed.map((item) => <article key={item.article_id} className="bg-slate-950/80 border border-slate-800 rounded-xl p-4">
      <div className="text-[11px] text-slate-500 mb-1">{item.source} · {formatRelativeTime(item.published_at)}</div>
      <h3 className="text-sm font-semibold text-white">{item.title}</h3>
      {item.summary && <p className="mt-2 text-xs text-slate-300">{item.summary}</p>}
      <div className="flex flex-wrap items-center justify-between gap-3 mt-3 pt-3 border-t border-slate-800/60">
        <div className="flex gap-1.5">{item.symbols.map((symbol) => <button key={symbol} onClick={() => onResearchStock(symbol)} className="px-2 py-0.5 bg-slate-800 text-slate-300 rounded text-[10px] font-bold">{symbol}</button>)}</div>
        <div className="flex gap-2">
          <button onClick={() => void toggleArticle(item.article_id)} className="px-2.5 py-1 bg-slate-800 text-slate-200 rounded-lg text-xs"><FileText className="inline w-3.5 h-3.5 mr-1" />{expandedArticle === item.article_id ? 'Hide article' : 'Article details'}</button>
          <button onClick={() => void toggleSummary(item.article_id)} className="px-2.5 py-1 bg-indigo-500/10 border border-indigo-500/30 text-indigo-300 rounded-lg text-xs"><Sparkles className="inline w-3.5 h-3.5 mr-1" />{expandedSummary === item.article_id ? 'Hide summary' : 'AI Summary'} {expandedSummary === item.article_id ? <ChevronUp className="inline w-3.5 h-3.5" /> : <ChevronDown className="inline w-3.5 h-3.5" />}</button>
          <a href={item.url} target="_blank" rel="noreferrer" className="p-1 text-slate-500 hover:text-slate-300" title="Open source"><ExternalLink className="w-3.5 h-3.5" /></a>
        </div>
      </div>
      {expandedArticle === item.article_id && <div className="mt-3 p-3 bg-slate-900 rounded-xl text-xs text-slate-300" aria-live="polite">{articleDetail?.loading ? 'Loading article…' : articleDetail?.error ? <span role="alert">{articleDetail.error}</span> : articleDetail?.data?.content ?? 'Article content is unavailable.'}</div>}
      {expandedSummary === item.article_id && <div className="mt-3 p-3 bg-slate-900 border border-indigo-500/20 rounded-xl text-xs text-slate-300 space-y-2" aria-live="polite">
        {summary?.loading && <span>Generating summary…</span>}
        {summary?.error && <span role="alert" className="text-rose-300">{summary.error}</span>}
        {summary?.data && <><p className="text-[10px] text-slate-500">Provider: {summary.data.provider}</p><p><strong>Summary:</strong> {summary.data.summary}</p><SummaryList title="Key developments" values={summary.data.key_developments} /><SummaryList title="Reported facts" values={summary.data.reported_facts} /><SummaryList title="Positive implications" values={summary.data.positive_implications} /><SummaryList title="Negative implications / risks" values={summary.data.negative_implications} /><p className="text-slate-400"><strong>Disclaimer:</strong> {summary.data.disclaimer}</p></>}
        {summary?.data && <ConversationPanel key={item.article_id} context={{ context_type: 'article', article_id: item.article_id, symbol: null, research_context: null }} />}
      </div>}
    </article>)}</div>
    {news?.next_page_token && <button onClick={() => { const token = news?.next_page_token; if (token) onLoadMore(token); }} disabled={loading} className="mt-4 px-3 py-2 bg-slate-800 text-white rounded-lg text-xs disabled:opacity-50">Load more</button>}
    {news && <p className="mt-3 text-[10px] text-slate-500">Showing {news.scope} news</p>}
  </div>;
};

function SummaryList({ title, values }: { title: string; values: string[] }) {
  return <div><strong>{title}:</strong>{values.length ? <ul className="list-disc pl-5 mt-1">{values.map((value, index) => <li key={`${title}-${index}`}>{value}</li>)}</ul> : <span> None reported.</span>}</div>;
}

