import React from 'react';
import { Briefcase, ArrowUpRight, ArrowDownRight, RefreshCw, AlertCircle, ShoppingBag, Sparkles } from 'lucide-react';
import { PortfolioSummary, Holding } from '../types/api';
import { formatINR } from '../utils/format';

interface PortfolioPanelProps {
  portfolio: PortfolioSummary | null;
  loading: boolean;
  onRefresh: () => void;
  onTrade: (symbol: string, currentPrice: number, holdingQty: number) => void;
  onResearch: (symbol: string) => void;
}

export const PortfolioPanel: React.FC<PortfolioPanelProps> = ({
  portfolio,
  loading,
  onRefresh,
  onTrade,
  onResearch,
}) => {
  const holdings: any[] = portfolio?.holdings || [];
  const cash = parseFloat(
    (portfolio as any)?.account?.cash_balance || portfolio?.cash || '0'
  );
  const totalValuation = (portfolio as any)?.total_portfolio_value
    ? parseFloat((portfolio as any).total_portfolio_value)
    : portfolio?.total_valuation
    ? parseFloat(portfolio.total_valuation)
    : null;
  const totalNetWorth = totalValuation !== null ? totalValuation : cash;

  // Calculate total unrealized P&L
  let totalPnl = 0;
  holdings.forEach((h) => {
    if (h.unrealized_pnl) {
      totalPnl += parseFloat(h.unrealized_pnl);
    }
  });

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-2xl backdrop-blur-md">
      {/* Top Banner / Metrics */}
      <div className="flex flex-wrap items-center justify-between gap-4 pb-6 border-b border-slate-800">
        <div>
          <div className="flex items-center gap-2">
            <Briefcase className="w-5 h-5 text-indigo-400" />
            <h2 className="text-lg font-bold text-white">Portfolio & Account Holdings</h2>
            <button
              onClick={onRefresh}
              disabled={loading}
              className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
              title="Refresh Portfolio"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
          <p className="text-xs text-slate-400 mt-0.5">
            Paper trading account valuation and open positions
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-6">
          <div className="bg-slate-950 px-4 py-2.5 rounded-xl border border-slate-800">
            <span className="text-[10px] text-slate-400 font-medium block">Total Net Worth</span>
            <div className="text-base font-bold font-mono-nums text-white">
              {totalNetWorth !== null ? formatINR(totalNetWorth) : '—'}
            </div>
          </div>

          <div className="bg-slate-950 px-4 py-2.5 rounded-xl border border-slate-800">
            <span className="text-[10px] text-slate-400 font-medium block">Available Cash</span>
            <div className="text-base font-bold font-mono-nums text-emerald-400">
              {formatINR(cash)}
            </div>
          </div>

          <div className="bg-slate-950 px-4 py-2.5 rounded-xl border border-slate-800">
            <span className="text-[10px] text-slate-400 font-medium block">Unrealized P&L</span>
            <div
              className={`text-base font-bold font-mono-nums flex items-center gap-1 ${
                totalPnl >= 0 ? 'text-emerald-400' : 'text-rose-400'
              }`}
            >
              {totalPnl >= 0 ? (
                <ArrowUpRight className="w-4 h-4" />
              ) : (
                <ArrowDownRight className="w-4 h-4" />
              )}
              {formatINR(totalPnl)}
            </div>
          </div>
        </div>
      </div>

      {portfolio?.incomplete && (
        <div className="mt-4 p-3 bg-amber-500/10 border border-amber-500/20 rounded-xl text-xs text-amber-300 flex items-center gap-2">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>Some asset quotes are currently unavailable; total valuation reflects available assets.</span>
        </div>
      )}

      {/* Asset Allocation Segmented Bar */}
      {totalNetWorth !== null && totalNetWorth > 0 && (
        <div className="mt-6 p-4 bg-slate-950/70 rounded-2xl border border-slate-800 space-y-3">
          <div className="flex items-center justify-between text-xs">
            <span className="font-semibold text-slate-300">Portfolio Capital Allocation</span>
            <span className="text-[11px] text-slate-500">
              {holdings.length} equities + cash reserve
            </span>
          </div>

          {/* Segmented bar */}
          <div className="h-3 w-full bg-slate-800 rounded-full overflow-hidden flex">
            {/* Cash segment */}
            <div
              style={{ width: `${Math.min(100, Math.max(1, (cash / totalNetWorth) * 100))}%` }}
              className="h-full bg-emerald-500 transition-all"
              title={`Cash: ${((cash / totalNetWorth) * 100).toFixed(1)}%`}
            />
            {/* Holdings segments */}
            {holdings.map((h: any, i) => {
              const sym = h.symbol || h.stock?.symbol || 'STOCK';
              const val = h.market_value ? parseFloat(h.market_value) : 0;
              const pct = (val / totalNetWorth) * 100;
              const colors = ['bg-indigo-500', 'bg-violet-500', 'bg-sky-500', 'bg-amber-500', 'bg-pink-500'];
              return (
                <div
                  key={sym}
                  style={{ width: `${Math.max(1, pct)}%` }}
                  className={`h-full ${colors[i % colors.length]} transition-all`}
                  title={`${sym}: ${pct.toFixed(1)}%`}
                />
              );
            })}
          </div>

          {/* Legend chips */}
          <div className="flex flex-wrap items-center gap-3 text-[11px] pt-1">
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-emerald-500" />
              <span className="text-slate-400">Cash:</span>
              <span className="font-bold text-white font-mono-nums">
                {((cash / totalNetWorth) * 100).toFixed(1)}%
              </span>
            </div>
            {holdings.slice(0, 5).map((h: any, i) => {
              const sym = h.symbol || h.stock?.symbol || 'STOCK';
              const val = h.market_value ? parseFloat(h.market_value) : 0;
              const pct = (val / totalNetWorth) * 100;
              const dotColors = ['bg-indigo-500', 'bg-violet-500', 'bg-sky-500', 'bg-amber-500', 'bg-pink-500'];
              return (
                <div key={sym} className="flex items-center gap-1.5">
                  <span className={`w-2 h-2 rounded-full ${dotColors[i % dotColors.length]}`} />
                  <span className="text-slate-400">{sym}:</span>
                  <span className="font-bold text-white font-mono-nums">
                    {pct.toFixed(1)}%
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Holdings Table */}
      <div className="mt-6 overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="border-b border-slate-800 text-slate-400 font-semibold uppercase tracking-wider text-[10px]">
              <th className="pb-3 pl-2">Asset / Symbol</th>
              <th className="pb-3 text-right">Shares</th>
              <th className="pb-3 text-right">Avg Cost</th>
              <th className="pb-3 text-right">Market Price</th>
              <th className="pb-3 text-right">Market Value</th>
              <th className="pb-3 text-right">Unrealized P&L</th>
              <th className="pb-3 text-center pr-2">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60 font-mono-nums">
            {holdings.length === 0 ? (
              <tr>
                <td colSpan={7} className="py-12 text-center text-slate-500 font-sans">
                  <ShoppingBag className="w-8 h-8 mx-auto mb-2 opacity-30" />
                  <p>You have no active holdings.</p>
                  <p className="text-[11px] text-slate-600 mt-0.5">
                    Execute a simulated buy order to open a position.
                  </p>
                </td>
              </tr>
            ) : (
              holdings.map((h: any) => {
                const sym = h.symbol || h.stock?.symbol || 'STOCK';
                const name = h.name || h.stock?.name || sym;
                const quotePrice = h.current_price
                  ? parseFloat(h.current_price)
                  : h.quote
                  ? parseFloat(h.quote.price)
                  : 0;
                const avgCost = h.average_purchase_price || h.average_buy_price || '0';
                const pnl = h.unrealized_pnl ? parseFloat(h.unrealized_pnl) : 0;
                const qty = parseInt(h.quantity) || 0;
                const isPositive = pnl >= 0;

                return (
                  <tr key={sym} className="hover:bg-slate-800/40 transition-colors">
                    <td className="py-3.5 pl-2 font-sans">
                      <div className="font-bold text-white text-xs">{sym}</div>
                      <div className="text-[11px] text-slate-400 line-clamp-1">{name}</div>
                    </td>
                    <td className="py-3.5 text-right font-bold text-white">{qty}</td>
                    <td className="py-3.5 text-right text-slate-300">
                      {formatINR(avgCost)}
                    </td>
                    <td className="py-3.5 text-right font-bold text-white">
                      {quotePrice ? formatINR(quotePrice) : '—'}
                    </td>
                    <td className="py-3.5 text-right font-bold text-slate-200">
                      {h.market_value ? formatINR(h.market_value) : '—'}
                    </td>
                    <td className="py-3.5 text-right">
                      <span
                        className={`inline-flex items-center gap-0.5 px-2 py-0.5 rounded-lg text-xs font-bold ${
                          isPositive
                            ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                            : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                        }`}
                      >
                        {isPositive ? '+' : ''}
                        {formatINR(pnl)}
                      </span>
                    </td>
                    <td className="py-3.5 text-center pr-2 font-sans">
                      <div className="flex items-center justify-center gap-1.5">
                        <button
                          type="button"
                          onClick={() => onTrade(sym, quotePrice, qty)}
                          className="px-2.5 py-1 bg-indigo-600/80 hover:bg-indigo-600 text-white rounded-lg text-xs font-semibold transition-colors"
                        >
                          Trade
                        </button>
                        <button
                          type="button"
                          onClick={() => onResearch(sym)}
                          title="AI Research"
                          className="p-1 bg-slate-800 hover:bg-slate-700 text-indigo-400 rounded-lg transition-colors"
                        >
                          <Sparkles className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

