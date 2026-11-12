import React, { useEffect, useState } from 'react';
import { Sparkles, AlertTriangle, TrendingUp, Search, Loader2, ArrowUpRight, BookOpen } from 'lucide-react';
import type { ResearchResponse } from '../types/api';
import { api } from '../services/api';
import { ConversationPanel } from './ConversationPanel';

interface AiResearchHubProps { initialSymbol?: string; onTradeStock: (symbol: string) => void; }

export const AiResearchHub: React.FC<AiResearchHubProps> = ({ initialSymbol = '', onTradeStock }) => {
  const [symbol, setSymbol] = useState(initialSymbol);
  const [research, setResearch] = useState<ResearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchResearch = async (stockSymbol: string) => {
    if (!stockSymbol.trim()) return;
    setLoading(true); setError(null);
    try { setResearch(await api.getResearch(stockSymbol.trim().toUpperCase())); }
    catch (requestError: unknown) { setResearch(null); setError(requestError instanceof Error ? requestError.message : 'Research request failed.'); }
    finally { setLoading(false); }
  };

  useEffect(() => { setSymbol(initialSymbol); if (initialSymbol) void fetchResearch(initialSymbol); }, [initialSymbol]);

  return <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-2xl">
    <div className="flex flex-wrap items-center justify-between gap-4 pb-4 border-b border-slate-800 mb-5">
      <div><div className="flex items-center gap-2"><Sparkles className="w-5 h-5 text-indigo-400" /><h2 className="text-lg font-bold text-white">AI Research &amp; Grounded Analysis</h2></div><p className="text-xs text-slate-400 mt-1">Generated research is informational and may be uncertain.</p></div>
      <form onSubmit={(event) => { event.preventDefault(); void fetchResearch(symbol); }} className="flex gap-2">
        <input value={symbol} onChange={(event) => setSymbol(event.target.value.toUpperCase())} placeholder="Enter NSE symbol" className="bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs font-bold text-white" />
        <button type="submit" disabled={loading || !symbol.trim()} className="px-3 py-2 bg-indigo-600 text-white rounded-xl text-xs disabled:opacity-50">{loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <><Search className="inline w-3.5 h-3.5 mr-1" />Analyze</>}</button>
      </form>
    </div>
    {loading && <p role="status" className="py-10 text-center text-slate-400">Loading research…</p>}
    {error && <p role="alert" className="py-8 text-center text-rose-300"><AlertTriangle className="inline w-4 h-4 mr-2" />{error}</p>}
    {!loading && !error && research?.suggestions.length === 0 && <p className="py-8 text-center text-slate-400">No research suggestions were returned.</p>}
    {research?.suggestions.map((suggestion) => <section key={`${suggestion.symbol}-${suggestion.generated_at}`} className="space-y-4 mb-6">
      <div className="bg-slate-950 p-5 rounded-xl border border-slate-800">
        <div className="flex items-center justify-between gap-4 mb-3"><strong className="text-white">{suggestion.symbol} research</strong><button onClick={() => onTradeStock(suggestion.symbol)} className="px-3 py-1.5 bg-emerald-600 text-white rounded-lg text-xs"><ArrowUpRight className="inline w-3.5 h-3.5 mr-1" />Trade {suggestion.symbol}</button></div>
        <p className="text-[10px] text-slate-500 mb-2">Provider: {suggestion.provider}</p>
        <p className="text-sm text-slate-200">{suggestion.thesis}</p>
        <p className="text-xs text-amber-300 mt-3"><strong>Uncertainty:</strong> {suggestion.uncertainty}</p>
        <p className="text-[10px] text-slate-500 mt-2">Generated {new Date(suggestion.generated_at).toLocaleString()} · Informational only</p>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <ResearchList title="Reported facts" values={suggestion.reported_facts} />
        <ResearchList title="Positive implications" values={suggestion.positive_implications} positive />
        <ResearchList title="Negative implications" values={suggestion.negative_implications} />
        <ResearchList title="Risks" values={suggestion.risks} />
      </div>
      <div className="bg-slate-950 rounded-xl border border-slate-800 p-4 text-xs text-slate-300">
        <div className="flex items-center gap-2 font-bold mb-2"><BookOpen className="w-4 h-4 text-indigo-400" />Supporting article IDs</div>
        {suggestion.evidence_article_ids.length ? <ul className="list-disc pl-5">{suggestion.evidence_article_ids.map((id) => <li key={id}>{id}</li>)}</ul> : <p>No article references were returned.</p>}
      </div>
      <ConversationPanel key={`${suggestion.symbol}:${suggestion.generated_at}`} context={{ context_type: 'research', article_id: null, symbol: suggestion.symbol, research_context: suggestion }} />
    </section>)}
    {research && <p className="text-[11px] text-slate-400 border-t border-slate-800 pt-3"><TrendingUp className="inline w-3.5 h-3.5 mr-1" />{research.disclaimer}</p>}
  </div>;
};

function ResearchList({ title, values, positive = false }: { title: string; values: string[]; positive?: boolean }) {
  return <div className="bg-slate-950/70 p-4 rounded-xl border border-slate-800"><h3 className={`font-bold text-xs mb-2 ${positive ? 'text-emerald-300' : 'text-slate-200'}`}>{title}</h3>{values.length ? <ul className="list-disc pl-5 space-y-1 text-xs text-slate-300">{values.map((value, index) => <li key={`${title}-${index}`}>{value}</li>)}</ul> : <p className="text-xs text-slate-500">None returned.</p>}</div>;
}

