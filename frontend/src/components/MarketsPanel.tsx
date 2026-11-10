import React, { useMemo, useState } from 'react';
import { Search, Loader2, Plus } from 'lucide-react';
import { api } from '../services/api';
import type { StockSummary, WatchlistItem } from '../types/api';
import { formatINR } from '../utils/format';

interface MarketsPanelProps {
  watchlist: WatchlistItem[];
  watchlistError: string | null;
  onWatchlistChange: () => Promise<void>;
}

export const MarketsPanel: React.FC<MarketsPanelProps> = ({ watchlist, watchlistError, onWatchlistChange }) => {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<StockSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [adding, setAdding] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);
  const quotesBySymbol = useMemo(() => new Map(watchlist.map((item) => [item.stock.symbol, item.quote])), [watchlist]);

  const search = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    setSearched(true);
    try {
      setResults(await api.searchStocks(query.trim(), 20));
    } catch (requestError: unknown) {
      setResults([]);
      setError(requestError instanceof Error ? requestError.message : 'Stock search failed.');
    } finally {
      setLoading(false);
    }
  };

  const addToWatchlist = async (symbol: string) => {
    setAdding(symbol);
    setError(null);
    try {
      await api.addToWatchlist(symbol);
      await onWatchlistChange();
    } catch (requestError: unknown) {
      setError(requestError instanceof Error ? requestError.message : 'Could not add stock to watchlist.');
    } finally {
      setAdding(null);
    }
  };

  return (
    <section className="max-w-5xl mx-auto space-y-6" aria-labelledby="markets-title">
      <header>
        <p className="text-[10px] uppercase font-bold tracking-widest text-indigo-400">DISCOVER</p>
        <h1 id="markets-title" className="text-2xl font-bold text-white">Markets</h1>
        <p className="text-sm text-slate-400 mt-1">Search eligible NSE equities. Quotes are available for stocks in your watchlist.</p>
      </header>

      <form onSubmit={search} className="flex gap-2 rounded-2xl border border-slate-800 bg-slate-900/90 p-4">
        <label className="sr-only" htmlFor="markets-query">Company name or symbol</label>
        <div className="flex flex-1 items-center gap-3 rounded-xl border border-slate-700 px-3">
          <Search className="h-4 w-4 text-slate-500" />
          <input id="markets-query" value={query} onChange={(event) => setQuery(event.target.value)}
            placeholder="Company name or symbol" maxLength={100} required
            className="w-full bg-transparent py-3 text-sm text-white outline-none placeholder:text-slate-500" />
        </div>
        <button className="rounded-xl bg-indigo-600 px-4 text-sm font-semibold text-white hover:bg-indigo-500 disabled:opacity-60" disabled={loading}>
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Search'}
        </button>
      </form>

      {error && <p role="alert" className="rounded-xl border border-rose-900 bg-rose-950/40 p-3 text-sm text-rose-300">{error}</p>}
      {watchlistError && <p role="alert" className="rounded-xl border border-amber-900 bg-amber-950/30 p-3 text-sm text-amber-200">{watchlistError} Quotes may be unavailable until the watchlist loads.</p>}
      {loading && <p role="status" className="text-sm text-slate-400">Searching NSE equities…</p>}
      {!loading && searched && results.length === 0 && !error && <p className="rounded-xl border border-slate-800 p-6 text-center text-sm text-slate-400">No matching NSE equities were found.</p>}

      {results.length > 0 && <div className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/90">
        <div className="grid grid-cols-12 gap-3 border-b border-slate-800 px-4 py-3 text-[10px] uppercase tracking-wider text-slate-500">
          <span className="col-span-5">Company</span><span className="col-span-2">Symbol</span><span className="col-span-2">Quote</span><span className="col-span-3 text-right">Action</span>
        </div>
        {results.map((stock) => {
          const quote = quotesBySymbol.get(stock.symbol);
          const alreadyWatched = watchlist.some((item) => item.stock.symbol === stock.symbol);
          return <article key={stock.symbol} className="grid grid-cols-12 items-center gap-3 border-b border-slate-800/70 px-4 py-4 last:border-0">
            <div className="col-span-5 min-w-0"><div className="truncate text-sm font-semibold text-white">{stock.name}</div><div className="text-xs text-slate-500">{stock.exchange} equity</div></div>
            <div className="col-span-2 font-mono text-sm text-slate-300">{stock.symbol}</div>
            <div className="col-span-2 text-sm text-slate-200">{quote ? formatINR(quote.price) : <span className="text-xs text-slate-500">Unavailable</span>}
              {quote && <div className="text-[10px] text-slate-500">{quote.simulated ? 'Simulated' : 'Provider quote'}</div>}
            </div>
            <div className="col-span-3 flex justify-end">
              <button type="button" onClick={() => void addToWatchlist(stock.symbol)} disabled={alreadyWatched || adding !== null}
                className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-800 disabled:cursor-default disabled:opacity-50">
                {adding === stock.symbol ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : !alreadyWatched && <Plus className="h-3.5 w-3.5" />}
                {alreadyWatched ? 'In watchlist' : 'Add to watchlist'}
              </button>
            </div>
          </article>;
        })}
      </div>}
    </section>
  );
};
