import React, { useState, useEffect } from 'react';
import { Search, ArrowRight, Star, Briefcase, History, Newspaper, Sparkles, X, Loader2 } from 'lucide-react';
import { api } from '../services/api';
import { StockSummary } from '../types/api';

interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
  onNavigate: (view: 'dashboard' | 'watchlist' | 'portfolio' | 'orders' | 'news' | 'research') => void;
  onSelectStock: (stock: StockSummary) => void;
}

const quickViews = [
  { label: 'Market Dashboard', view: 'dashboard', icon: Sparkles },
  { label: 'Watchlist & Discovery', view: 'watchlist', icon: Star },
  { label: 'Holdings & Portfolio', view: 'portfolio', icon: Briefcase },
  { label: 'Orders & Transactions', view: 'orders', icon: History },
  { label: 'Market Intelligence & News', view: 'news', icon: Newspaper },
  { label: 'AI Grounded Research', view: 'research', icon: Sparkles },
] as const;

export const CommandPalette: React.FC<CommandPaletteProps> = ({
  isOpen,
  onClose,
  onNavigate,
  onSelectStock,
}) => {
  const [query, setQuery] = useState('');
  const [stocks, setStocks] = useState<StockSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        if (isOpen) onClose();
        else {
          // Open
          setQuery('');
        }
      }
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  useEffect(() => {
    setSearchError(null);
    if (!query.trim()) {
      setStocks([]);
      return;
    }

    const timer = setTimeout(async () => {
      setLoading(true);
      try {
        const results = await api.searchStocks(query.trim(), 5);
        setStocks(results);
      } catch (err: unknown) {
        setSearchError(err instanceof Error ? err.message : 'Stock search failed.');
      } finally {
        setLoading(false);
      }
    }, 200);

    return () => clearTimeout(timer);
  }, [query]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-20 px-4 bg-slate-950/80 backdrop-blur-sm animate-in fade-in duration-150">
      <div
        className="w-full max-w-xl bg-slate-900 border border-slate-800 rounded-2xl shadow-2xl overflow-hidden animate-in zoom-in-95 duration-150"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search Input */}
        <div className="flex items-center gap-3 px-4 py-3.5 border-b border-slate-800">
          <Search className="w-5 h-5 text-indigo-400" />
          <input
            type="text"
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Type a stock name, symbol, or command..."
            className="w-full bg-transparent text-sm text-white placeholder-slate-500 focus:outline-none"
          />
          {loading && <Loader2 className="w-4 h-4 animate-spin text-indigo-400" />}
          <button
            onClick={onClose}
            className="p-1 rounded-lg text-slate-500 hover:text-white transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Results / Navigation Suggestions */}
        <div className="p-2 max-h-80 overflow-y-auto space-y-1">
          {searchError && <p role="alert" className="px-3 py-2 text-xs text-rose-300">{searchError}</p>}
          {stocks.length > 0 && (
            <div className="mb-2">
              <div className="text-[10px] uppercase font-bold text-slate-500 px-3 py-1">
                Stocks
              </div>
              {stocks.map((stock) => (
                <button
                  key={stock.symbol}
                  onClick={() => {
                    onSelectStock(stock);
                    onClose();
                  }}
                  className="w-full flex items-center justify-between p-2.5 hover:bg-slate-800 rounded-xl transition-colors text-left group"
                >
                  <div>
                    <span className="font-bold text-xs text-white group-hover:text-indigo-400 transition-colors">
                      {stock.symbol}
                    </span>
                    <span className="text-xs text-slate-400 ml-2">{stock.name}</span>
                  </div>
                  <ArrowRight className="w-3.5 h-3.5 text-slate-500 group-hover:text-indigo-400 group-hover:translate-x-0.5 transition-all" />
                </button>
              ))}
            </div>
          )}

          <div>
            <div className="text-[10px] uppercase font-bold text-slate-500 px-3 py-1">
              Quick Views
            </div>
            {quickViews.map((item) => {
              const Icon = item.icon;
              return (
                <button
                  key={item.view}
                  onClick={() => {
                    onNavigate(item.view);
                    onClose();
                  }}
                  className="w-full flex items-center justify-between p-2.5 hover:bg-slate-800 rounded-xl transition-colors text-left group text-xs text-slate-300"
                >
                  <div className="flex items-center gap-2.5">
                    <Icon className="w-4 h-4 text-indigo-400" />
                    <span>{item.label}</span>
                  </div>
                  <span className="text-[10px] text-slate-500 group-hover:text-slate-300">
                    Jump to view
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Footer */}
        <div className="px-4 py-2 bg-slate-950 border-t border-slate-800/80 text-[10px] text-slate-500 flex items-center justify-between">
          <span>Use ESC to exit</span>
          <span>TradePoint Terminal v2.0</span>
        </div>
      </div>
    </div>
  );
};

