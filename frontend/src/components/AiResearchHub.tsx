import React, { useState, useEffect } from 'react';
import { Sparkles, AlertTriangle, TrendingUp, CheckCircle, Search, Loader2, ArrowUpRight, BookOpen } from 'lucide-react';
import { ResearchSuggestion } from '../types/api';
import { api } from '../services/api';

interface AiResearchHubProps {
  initialSymbol?: string;
  onTradeStock: (symbol: string) => void;
}

export const AiResearchHub: React.FC<AiResearchHubProps> = ({
  initialSymbol = 'TCS',
  onTradeStock,
}) => {
  const [symbol, setSymbol] = useState(initialSymbol);
  const [research, setResearch] = useState<ResearchSuggestion | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchResearch = async (stockSymbol: string) => {
    if (!stockSymbol.trim()) return;
    setLoading(true);
    setError(null);

    try {
      const data = await api.getResearch(stockSymbol.trim().toUpperCase());
      setResearch(data);
    } catch (err: any) {
      setError(err.message || 'Failed to fetch AI research for this stock.');
      setResearch(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (initialSymbol) {
      setSymbol(initialSymbol);
      fetchResearch(initialSymbol);
    }
  }, [initialSymbol]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    fetchResearch(symbol);
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-2xl backdrop-blur-md">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 pb-4 border-b border-slate-800 mb-6">
        <div>
          <div className="flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-indigo-400" />
            <h2 className="text-lg font-bold text-white">AI Research & Grounded Analysis</h2>
          </div>
          <p className="text-xs text-slate-400 mt-0.5">
            Real-time synthesis of market filings, news, and sentiment indicators
          </p>
        </div>

        {/* Symbol Search Form */}
        <form onSubmit={handleSubmit} className="flex items-center gap-2">
          <div className="relative">
            <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              type="text"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
              placeholder="Enter symbol (e.g. INFY)..."
              className="bg-slate-950 border border-slate-800 rounded-xl pl-8 pr-3 py-1.5 text-xs font-bold text-white uppercase placeholder-slate-500 focus:outline-none focus:border-indigo-500"
            />
          </div>
          <button
            type="submit"
            disabled={loading || !symbol.trim()}
            className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 text-white rounded-xl text-xs font-semibold flex items-center gap-1.5 transition-colors"
          >
            {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
            Analyze
          </button>
        </form>
      </div>

      {/* Main Content Area */}
      {loading ? (
        <div className="py-16 text-center text-slate-400 flex flex-col items-center justify-center gap-3">
          <div className="w-10 h-10 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
          <p className="text-sm font-semibold text-slate-300">
            Synthesizing intelligence for {symbol}...
          </p>
          <p className="text-xs text-slate-500">
            Analyzing recent news, market sentiment, and key risk factors
          </p>
        </div>
      ) : error ? (
        <div className="py-12 text-center text-slate-400">
          <AlertTriangle className="w-8 h-8 text-amber-400 mx-auto mb-2 opacity-80" />
          <p className="text-sm font-semibold text-white">{error}</p>
          <p className="text-xs text-slate-500 mt-1">
            Ensure the symbol exists in the NSE instruments cache.
          </p>
        </div>
      ) : research ? (
        <div className="space-y-6">
          {/* Executive Overview Card */}
          <div className="bg-slate-950 p-5 rounded-xl border border-slate-800 relative overflow-hidden">
            <div className="flex items-center justify-between gap-4 mb-3">
              <div className="flex items-center gap-2">
                <span className="text-base font-bold text-white tracking-wide">
                  {research.symbol} Overview
                </span>
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 font-bold">
                  AI SYNTHESIZED
                </span>
              </div>
              <button
                type="button"
                onClick={() => onTradeStock(research.symbol)}
                className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-slate-950 font-bold rounded-lg text-xs flex items-center gap-1 transition-colors shadow-lg shadow-emerald-950/40"
              >
                <ArrowUpRight className="w-3.5 h-3.5" /> Trade {research.symbol}
              </button>
            </div>
            <p className="text-xs text-slate-300 leading-relaxed font-sans">{research.summary}</p>
          </div>

          {/* Catalysts & Risks Split Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Key Catalysts */}
            <div className="bg-slate-950/70 p-4 rounded-xl border border-slate-800">
              <div className="flex items-center gap-1.5 text-emerald-400 font-bold text-xs mb-3">
                <TrendingUp className="w-4 h-4" /> Key Growth Catalysts
              </div>
              <ul className="space-y-2 text-xs text-slate-300">
                {research.key_catalysts?.map((catalyst, idx) => (
                  <li key={idx} className="flex items-start gap-2">
                    <CheckCircle className="w-3.5 h-3.5 text-emerald-500 shrink-0 mt-0.5" />
                    <span>{catalyst}</span>
                  </li>
                ))}
              </ul>
            </div>

            {/* Uncertainty Notes & Risks */}
            <div className="bg-slate-950/70 p-4 rounded-xl border border-slate-800">
              <div className="flex items-center gap-1.5 text-amber-400 font-bold text-xs mb-3">
                <AlertTriangle className="w-4 h-4" /> Uncertainty & Risk Factors
              </div>
              <ul className="space-y-2 text-xs text-slate-300">
                {research.uncertainty_notes?.map((risk, idx) => (
                  <li key={idx} className="flex items-start gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0 mt-1.5" />
                    <span>{risk}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          {/* Grounded Sources */}
          {research.sources && research.sources.length > 0 && (
            <div className="pt-2">
              <div className="flex items-center gap-1.5 text-slate-400 font-semibold text-xs mb-2">
                <BookOpen className="w-3.5 h-3.5 text-indigo-400" /> Grounded Source Citations (
                {research.sources.length})
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {research.sources.map((src, idx) => (
                  <div
                    key={idx}
                    className="p-2.5 bg-slate-950 rounded-lg border border-slate-800/80 text-[11px]"
                  >
                    <div className="font-semibold text-slate-300 line-clamp-1">{src.title}</div>
                    <div className="text-[10px] text-slate-500 mt-0.5">
                      {src.source} • {new Date(src.published_at).toLocaleDateString()}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
};

