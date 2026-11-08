import React, { useState } from 'react';
import { Search, Star, Trash2, ArrowUpRight, Sparkles, Loader2, Plus } from 'lucide-react';
import { WatchlistItem, StockSummary } from '../types/api';
import { formatINR } from '../utils/format';
import { api } from '../services/api';

interface WatchlistPanelProps {
  watchlist: WatchlistItem[];
  loading?: boolean;
  error?: string | null;
  onSelectStock: (symbol: string, name: string, price: string | null, simulated: boolean | null) => void;
  onTradeStock: (symbol: string, price: string | null) => void;
  onResearchStock: (symbol: string) => void;
  onRefresh: () => void;
}

export const WatchlistPanel: React.FC<WatchlistPanelProps> = ({
  watchlist,
  loading = false,
  error = null,
  onSelectStock,
  onTradeStock,
  onResearchStock,
  onRefresh,
}) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<StockSummary[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchQuery.trim()) return;
    setSearching(true);
    setSearchError(null);

    try {
      const results = await api.searchStocks(searchQuery.trim());
      setSearchResults(results);
      if (results.length === 0) {
        setSearchError('No matching NSE equities found.');
      }
    } catch (err: unknown) {
      setSearchError(err instanceof Error ? err.message : 'Search failed.');
    } finally {
      setSearching(false);
    }
  };

  const handleAdd = async (stock: StockSummary) => {
    setActionError(null);
    try {
      await api.addToWatchlist(stock.symbol);
      setSearchResults([]);
      setSearchQuery('');
      onRefresh();
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Failed to add stock to watchlist.');
    }
  };

  const handleRemove = async (symbol: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setActionError(null);
    try {
      await api.removeFromWatchlist(symbol);
      onRefresh();
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Failed to remove stock from watchlist.');
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-2xl backdrop-blur-md flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between pb-3 border-b border-slate-800 mb-4">
        <div className="flex items-center gap-2">
          <Star className="w-5 h-5 text-amber-400 fill-amber-400/20" />
          <h3 className="font-bold text-white text-base">Watchlist & Discovery</h3>
        </div>
        <span className="text-xs text-slate-400 font-medium">
          {watchlist.length} {watchlist.length === 1 ? 'asset' : 'assets'}
        </span>
      </div>

      {/* Stock Search Input */}
      <form onSubmit={handleSearch} className="relative mb-3">
        <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search NSE equities (e.g. Tata, Infosys)..."
          className="w-full bg-slate-950 border border-slate-800 rounded-xl pl-9 pr-20 py-2 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 transition-colors"
        />
        <button
          type="submit"
          disabled={searching || !searchQuery.trim()}
          className="absolute right-1.5 top-1/2 -translate-y-1/2 px-2.5 py-1 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 text-white rounded-lg text-xs font-semibold transition-colors flex items-center gap-1"
        >
          {searching ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Search'}
        </button>
      </form>

      {/* Search Results Dropdown List */}
      {searchResults.length > 0 && (
        <div className="mb-4 bg-slate-950 border border-slate-800 rounded-xl p-2 max-h-48 overflow-y-auto space-y-1 divide-y divide-slate-800/40">
          <div className="text-[11px] font-semibold text-slate-400 px-2 py-1">
            Search Results ({searchResults.length})
          </div>
          {searchResults.map((stock) => {
            const isSaved = watchlist.some((item) => item.stock.symbol === stock.symbol);
            return (
              <div
                key={stock.symbol}
                className="flex items-center justify-between p-2 hover:bg-slate-900 rounded-lg transition-colors"
              >
                <div>
                  <div className="font-bold text-xs text-white flex items-center gap-1.5">
                    {stock.symbol}
                    <span className="text-[10px] text-slate-400 font-normal">
                      {stock.exchange}
                    </span>
                  </div>
                  <div className="text-[11px] text-slate-400 line-clamp-1">{stock.name}</div>
                </div>
                <button
                  type="button"
                  onClick={() => handleAdd(stock)}
                  disabled={isSaved}
                  className={`px-2.5 py-1 rounded-lg text-xs font-semibold transition-all flex items-center gap-1 ${
                    isSaved
                      ? 'bg-slate-800 text-slate-500 cursor-default'
                      : 'bg-emerald-600 hover:bg-emerald-500 text-white'
                  }`}
                >
                  {isSaved ? 'Saved' : <><Plus className="w-3 h-3" /> Add</>}
                </button>
              </div>
            );
          })}
        </div>
      )}

      {searchError && (
        <div className="text-xs text-rose-400 px-2 mb-3">{searchError}</div>
      )}
      {error && <div role="alert" className="text-xs text-rose-300 px-2 mb-3">{error}</div>}
      {actionError && <div role="alert" className="text-xs text-rose-300 px-2 mb-3">{actionError}</div>}

      {/* Watchlist Items */}
      <div className="flex-1 overflow-y-auto space-y-2 pr-1">
        {loading ? <p role="status" className="py-8 text-center text-xs text-slate-400">Loading watchlist…</p> : watchlist.length === 0 ? (
          <div className="py-12 text-center text-slate-500">
            <Star className="w-8 h-8 mx-auto mb-2 opacity-30" />
            <p className="text-xs">Your watchlist is currently empty.</p>
            <p className="text-[11px] text-slate-600 mt-0.5">Search above to add NSE stocks.</p>
          </div>
        ) : (
          watchlist.map((item) => {
            const price = item.quote?.price ?? null;
            return (
              <div
                key={item.stock.symbol}
                onClick={() => onSelectStock(item.stock.symbol, item.stock.name, price, item.quote?.simulated ?? null)}
                className="group p-3 bg-slate-950/70 hover:bg-slate-800/80 border border-slate-800/80 hover:border-indigo-500/40 rounded-xl transition-all cursor-pointer flex items-center justify-between"
              >
                <div className="flex-1 min-w-0 pr-2">
                  <div className="flex items-center gap-1.5">
                    <span className="font-bold text-xs text-white group-hover:text-indigo-400 transition-colors">
                      {item.stock.symbol}
                    </span>
                    {item.quote?.simulated && (
                      <span className="text-[9px] px-1.5 py-0.2 bg-slate-800 text-slate-400 rounded">
                        MOCK
                      </span>
                    )}
                  </div>
                  <p className="text-[11px] text-slate-400 truncate mt-0.5">
                    {item.stock.name}
                  </p>
                </div>

                <div className="text-right flex items-center gap-3">
                  <div>
                    <div className="text-xs font-bold font-mono-nums text-white">
                      {item.quote ? formatINR(item.quote.price) : '—'}
                    </div>
                    <div className="text-[10px] text-slate-500">{item.quote ? (item.quote.simulated ? 'Simulated quote' : 'Provider quote') : 'Unavailable'}</div>
                  </div>

                  {/* Quick actions on hover */}
                  <div className="flex items-center gap-1 opacity-80 group-hover:opacity-100 transition-opacity">
                    <button
                      type="button"
                      title="Quick Trade"
                      onClick={(e) => {
                        e.stopPropagation();
                        onTradeStock(item.stock.symbol, price);
                      }}
                      className="p-1.5 bg-slate-800 hover:bg-emerald-600 text-slate-300 hover:text-white rounded-lg transition-colors"
                    >
                      <ArrowUpRight className="w-3.5 h-3.5" />
                    </button>
                    <button
                      type="button"
                      title="AI Research"
                      onClick={(e) => {
                        e.stopPropagation();
                        onResearchStock(item.stock.symbol);
                      }}
                      className="p-1.5 bg-slate-800 hover:bg-indigo-600 text-slate-300 hover:text-white rounded-lg transition-colors"
                    >
                      <Sparkles className="w-3.5 h-3.5" />
                    </button>
                    <button
                      type="button"
                      title="Remove"
                      onClick={(e) => handleRemove(item.stock.symbol, e)}
                      className="p-1.5 bg-slate-800 hover:bg-rose-600 text-slate-400 hover:text-white rounded-lg transition-colors"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};

