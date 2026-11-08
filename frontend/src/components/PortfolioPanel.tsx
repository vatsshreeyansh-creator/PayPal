import React from 'react';
import { Briefcase, RefreshCw, ShoppingBag, Sparkles } from 'lucide-react';
import type { PortfolioSummary } from '../types/api';
import { formatINR } from '../utils/format';

interface PortfolioPanelProps {
  portfolio: PortfolioSummary | null;
  loading: boolean;
  error?: string | null;
  onRefresh: () => void;
  onTrade: (symbol: string, currentPrice: string | null, holdingQty: string) => void;
  onResearch: (symbol: string) => void;
}

export const PortfolioPanel: React.FC<PortfolioPanelProps> = ({ portfolio, loading, error, onRefresh, onTrade, onResearch }) => (
  <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-2xl">
    <div className="flex flex-wrap items-center justify-between gap-4 pb-5 border-b border-slate-800">
      <div>
        <div className="flex items-center gap-2"><Briefcase className="w-5 h-5 text-indigo-400" /><h2 className="text-lg font-bold text-white">Portfolio & Account Holdings</h2>
          <button onClick={onRefresh} disabled={loading} title="Refresh portfolio" className="p-1 text-slate-400 hover:text-white"><RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} /></button>
        </div>
        <p className="text-xs text-slate-400 mt-1">Paper trading account valuation and open positions</p>
      </div>
      <div className="flex gap-6 text-right">
        <div><span className="block text-[10px] text-slate-400">Total portfolio value</span><strong className="text-white">{portfolio?.total_portfolio_value === null || !portfolio ? 'Unavailable' : formatINR(portfolio.total_portfolio_value)}</strong></div>
        <div><span className="block text-[10px] text-slate-400">Available cash</span><strong className="text-emerald-400">{portfolio ? formatINR(portfolio.account.cash_balance) : 'Unavailable'}</strong></div>
      </div>
    </div>
    {loading && <p role="status" className="py-4 text-xs text-slate-400">Loading portfolio…</p>}
    {error && <p role="alert" className="mt-4 text-xs text-rose-300">{error}</p>}
    {!loading && !error && !portfolio && <p className="py-6 text-sm text-slate-400">Portfolio data is unavailable.</p>}
    {portfolio?.holdings.some((holding) => holding.current_price === null) && <p className="mt-4 text-xs text-amber-300">One or more quotes are unavailable; affected values are shown as unavailable.</p>}
    <div className="mt-5 overflow-x-auto">
      <table className="w-full text-left text-xs">
        <thead><tr className="border-b border-slate-800 text-slate-400 uppercase text-[10px]"><th className="pb-3">Asset / symbol</th><th className="pb-3 text-right">Shares</th><th className="pb-3 text-right">Average cost</th><th className="pb-3 text-right">Current price</th><th className="pb-3 text-right">Market value</th><th className="pb-3 text-right">Unrealized P&amp;L</th><th className="pb-3 text-right">Actions</th></tr></thead>
        <tbody className="divide-y divide-slate-800/60">
          {!portfolio?.holdings.length ? <tr><td colSpan={7} className="py-10 text-center text-slate-500"><ShoppingBag className="w-7 h-7 mx-auto mb-2 opacity-40" />No active holdings.</td></tr> : portfolio.holdings.map((holding) => (
            <tr key={holding.symbol} className="hover:bg-slate-800/40">
              <td className="py-3"><strong className="block text-white">{holding.symbol}</strong><span className="text-slate-400">{holding.name}</span></td>
              <td className="py-3 text-right text-white">{holding.quantity}</td>
              <td className="py-3 text-right text-slate-300">{formatINR(holding.average_purchase_price)}</td>
              <td className="py-3 text-right text-white">{holding.current_price === null ? 'Unavailable' : formatINR(holding.current_price)}</td>
              <td className="py-3 text-right text-slate-200">{holding.market_value === null ? 'Unavailable' : formatINR(holding.market_value)}</td>
              <td className="py-3 text-right text-slate-200">{holding.unrealized_pnl === null ? 'Unavailable' : formatINR(holding.unrealized_pnl)}</td>
              <td className="py-3 text-right"><button onClick={() => onTrade(holding.symbol, holding.current_price, holding.quantity)} className="px-2 py-1 bg-indigo-600 rounded mr-1">Trade</button><button onClick={() => onResearch(holding.symbol)} title="AI Research" className="p-1 text-indigo-300"><Sparkles className="w-3.5 h-3.5" /></button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  </div>
);

