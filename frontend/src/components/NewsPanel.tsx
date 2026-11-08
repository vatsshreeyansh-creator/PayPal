import React, { useState } from 'react';
import { Newspaper, Sparkles, ExternalLink, ChevronDown, ChevronUp, Loader2, Filter } from 'lucide-react';
import { NewsArticle } from '../types/api';
import { formatRelativeTime } from '../utils/format';
import { api } from '../services/api';

interface NewsPanelProps {
  news: NewsArticle[];
  loading: boolean;
  scope: 'personal' | 'market';
  onScopeChange: (scope: 'personal' | 'market') => void;
  onFilterChange: (query: string) => void;
  onResearchStock: (symbol: string) => void;
}

export const NewsPanel: React.FC<NewsPanelProps> = ({
  news,
  loading,
  scope,
  onScopeChange,
  onFilterChange,
  onResearchStock,
}) => {
  const [filterQuery, setFilterQuery] = useState('');
  const [summaries, setSummaries] = useState<Record<string, { summary: string; loading: boolean }>>({});
  const [expandedArticleId, setExpandedArticleId] = useState<string | null>(null);

  const handleFilterSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onFilterChange(filterQuery);
  };

  const handleToggleSummary = async (article: NewsArticle) => {
    if (expandedArticleId === article.article_id) {
      setExpandedArticleId(null);
      return;
    }

    setExpandedArticleId(article.article_id);

    if (!summaries[article.article_id]) {
      setSummaries((prev) => ({
        ...prev,
        [article.article_id]: { summary: '', loading: true },
      }));

      try {
        const res = await api.summarizeArticle(article.article_id);
        setSummaries((prev) => ({
          ...prev,
          [article.article_id]: { summary: res.summary || 'Summary unavailable.', loading: false },
        }));
      } catch (err: any) {
        setSummaries((prev) => ({
          ...prev,
          [article.article_id]: {
            summary: err.message || 'Failed to generate summary.',
            loading: false,
          },
        }));
      }
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-2xl backdrop-blur-md">
      {/* Header and Scope Selector */}
      <div className="flex flex-wrap items-center justify-between gap-4 pb-4 border-b border-slate-800 mb-4">
        <div className="flex items-center gap-2">
          <Newspaper className="w-5 h-5 text-indigo-400" />
          <h2 className="text-lg font-bold text-white">Market Intelligence & News</h2>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {/* Scope Pills */}
          <div className="flex items-center gap-1 bg-slate-950 p-1 rounded-xl border border-slate-800">
            <button
              onClick={() => onScopeChange('personal')}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                scope === 'personal'
                  ? 'bg-indigo-600 text-white shadow'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              My Stocks
            </button>
            <button
              onClick={() => onScopeChange('market')}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                scope === 'market'
                  ? 'bg-indigo-600 text-white shadow'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              Indian Equities
            </button>
          </div>

          {/* Filter Form */}
          <form onSubmit={handleFilterSubmit} className="flex items-center gap-1.5">
            <input
              type="text"
              value={filterQuery}
              onChange={(e) => setFilterQuery(e.target.value)}
              placeholder="Filter headlines..."
              className="bg-slate-950 border border-slate-800 rounded-xl px-3 py-1.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
            />
            <button
              type="submit"
              className="p-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl transition-colors"
              title="Apply filter"
            >
              <Filter className="w-3.5 h-3.5" />
            </button>
          </form>
        </div>
      </div>

      {/* News List */}
      <div className="space-y-3">
        {loading ? (
          <div className="py-12 text-center text-slate-500 flex items-center justify-center gap-2">
            <Loader2 className="w-4 h-4 animate-spin text-indigo-400" />
            <span className="text-xs">Fetching latest market feed...</span>
          </div>
        ) : news.length === 0 ? (
          <div className="py-12 text-center text-slate-500">
            <Newspaper className="w-8 h-8 mx-auto mb-2 opacity-30" />
            <p className="text-xs">No articles found matching this filter.</p>
          </div>
        ) : (
          news.map((item) => {
            const isExpanded = expandedArticleId === item.article_id;
            const summaryState = summaries[item.article_id];

            return (
              <div
                key={item.article_id}
                className="bg-slate-950/80 border border-slate-800/80 hover:border-slate-700 rounded-xl p-4 transition-all"
              >
                <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-500 mb-1.5">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-slate-300">{item.source}</span>
                    <span>•</span>
                    <span>{formatRelativeTime(item.published_at)}</span>
                  </div>

                  {item.sentiment && (
                    <span
                      className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${
                        item.sentiment === 'bullish'
                          ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                          : item.sentiment === 'bearish'
                          ? 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                          : 'bg-slate-800 text-slate-300'
                      }`}
                    >
                      {item.sentiment}
                    </span>
                  )}
                </div>

                <h4 className="text-sm font-semibold text-white leading-snug hover:text-indigo-300 transition-colors">
                  {item.title}
                </h4>

                {/* Stock Mentions and Actions */}
                <div className="flex flex-wrap items-center justify-between gap-3 mt-3 pt-3 border-t border-slate-800/60">
                  <div className="flex items-center gap-1.5">
                    {item.stocks?.map((sym) => (
                      <button
                        key={sym}
                        type="button"
                        onClick={() => onResearchStock(sym)}
                        className="px-2 py-0.5 bg-slate-800 hover:bg-indigo-600/80 text-slate-300 hover:text-white rounded-md text-[10px] font-bold transition-colors"
                        title={`AI Research for ${sym}`}
                      >
                        ${sym}
                      </button>
                    ))}
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => handleToggleSummary(item)}
                      className="px-2.5 py-1 bg-indigo-500/10 hover:bg-indigo-500/20 border border-indigo-500/30 text-indigo-300 rounded-lg text-xs font-semibold flex items-center gap-1 transition-colors"
                    >
                      <Sparkles className="w-3.5 h-3.5" />
                      {isExpanded ? 'Hide AI Summary' : 'AI Summary'}
                      {isExpanded ? (
                        <ChevronUp className="w-3.5 h-3.5" />
                      ) : (
                        <ChevronDown className="w-3.5 h-3.5" />
                      )}
                    </button>

                    {item.url && (
                      <a
                        href={item.url}
                        target="_blank"
                        rel="noreferrer"
                        className="p-1 text-slate-500 hover:text-slate-300 transition-colors"
                        title="Open Source"
                      >
                        <ExternalLink className="w-3.5 h-3.5" />
                      </a>
                    )}
                  </div>
                </div>

                {/* Expanded AI Summary View */}
                {isExpanded && (
                  <div className="mt-3 p-3.5 bg-slate-900 border border-indigo-500/30 rounded-xl text-xs text-slate-300 leading-relaxed animate-in fade-in duration-200">
                    <div className="flex items-center gap-1.5 text-indigo-400 font-bold mb-1.5 text-[11px]">
                      <Sparkles className="w-3.5 h-3.5" /> AI Executive Brief
                    </div>
                    {summaryState?.loading ? (
                      <div className="flex items-center gap-2 py-2 text-slate-400">
                        <Loader2 className="w-3.5 h-3.5 animate-spin text-indigo-400" />
                        Generating grounded summary...
                      </div>
                    ) : (
                      <p>{summaryState?.summary}</p>
                    )}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};

