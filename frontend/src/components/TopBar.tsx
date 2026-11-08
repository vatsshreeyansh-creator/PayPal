import React from 'react';
import { Search, Shield, Zap, TrendingUp, TrendingDown, Wallet } from 'lucide-react';
import { formatINR } from '../utils/format';

interface TopBarProps {
  availableCash: number;
  totalNetWorth: number | null;
  onOpenSearch: () => void;
  onNewOrder: () => void;
}

export const TopBar: React.FC<TopBarProps> = ({
  availableCash,
  totalNetWorth,
  onOpenSearch,
  onNewOrder,
}) => {
  // Mock ticker data for market ribbon
  const tickers = [
    { symbol: 'NIFTY 50', price: '24,352.40', change: '+0.54%', up: true },
    { symbol: 'TCS', price: '4,120.00', change: '+1.15%', up: true },
    { symbol: 'INFY', price: '1,890.50', change: '-0.42%', up: false },
    { symbol: 'RELIANCE', price: '2,980.10', change: '+0.88%', up: true },
    { symbol: 'HDFCBANK', price: '1,650.00', change: '+0.21%', up: true },
  ];

  return (
    <header className="sticky top-0 z-40 bg-slate-950/80 backdrop-blur-xl border-b border-slate-800/80 px-6 py-3">
      <div className="flex items-center justify-between gap-6">
        {/* Brand & Market Ticker */}
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-xl bg-gradient-to-tr from-indigo-600 to-violet-500 flex items-center justify-center font-black text-white text-base shadow-lg shadow-indigo-500/20">
              T
            </div>
            <div>
              <span className="font-bold text-white text-base tracking-tight">Trade</span>
              <span className="font-bold text-indigo-400 text-base tracking-tight">Point</span>
              <span className="ml-1.5 text-[9px] font-bold px-1.5 py-0.2 rounded bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                PRO
              </span>
            </div>
          </div>

          {/* Ticker Ribbon */}
          <div className="hidden lg:flex items-center gap-4 pl-4 border-l border-slate-800 text-xs font-mono-nums">
            {tickers.map((t) => (
              <div key={t.symbol} className="flex items-center gap-1.5">
                <span className="font-bold text-slate-300 font-sans text-[11px]">{t.symbol}</span>
                <span className="text-slate-400 font-semibold">{t.price}</span>
                <span
                  className={`text-[10px] font-bold flex items-center ${
                    t.up ? 'text-emerald-400' : 'text-rose-400'
                  }`}
                >
                  {t.up ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
                  {t.change}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Global Search & Account Stats */}
        <div className="flex items-center gap-3">
          {/* Quick Search Shortcut */}
          <button
            type="button"
            onClick={onOpenSearch}
            className="hidden sm:flex items-center gap-3 px-3 py-1.5 bg-slate-900 hover:bg-slate-800/80 border border-slate-800 text-slate-400 hover:text-white rounded-xl text-xs transition-all"
          >
            <Search className="w-3.5 h-3.5" />
            <span>Search stocks, news, orders...</span>
            <kbd className="px-1.5 py-0.5 rounded bg-slate-800 text-[10px] font-mono font-semibold border border-slate-700">
              Ctrl+K
            </kbd>
          </button>

          {/* Balance Badge */}
          <div className="hidden md:flex items-center gap-2 bg-slate-900 border border-slate-800 rounded-xl px-3 py-1.5 text-xs font-mono-nums">
            <Wallet className="w-3.5 h-3.5 text-emerald-400" />
            <span className="text-slate-400 font-sans text-[11px]">Cash:</span>
            <span className="font-bold text-emerald-400">{formatINR(availableCash)}</span>
          </div>

          {/* New Order Button */}
          <button
            type="button"
            onClick={onNewOrder}
            className="px-3.5 py-1.5 bg-gradient-to-r from-indigo-600 to-indigo-500 hover:from-indigo-500 hover:to-indigo-400 text-white rounded-xl text-xs font-bold shadow-lg shadow-indigo-600/30 flex items-center gap-1.5 transition-all"
          >
            <Zap className="w-3.5 h-3.5" />
            <span>New Order</span>
          </button>

          {/* Demo Account Indicator */}
          <div className="flex items-center gap-2 pl-2">
            <div className="w-7 h-7 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center text-xs font-bold text-indigo-400">
              D
            </div>
            <div className="hidden xl:block text-left text-[11px]">
              <div className="font-bold text-slate-200 leading-none">Paper Trader</div>
              <div className="text-[10px] text-slate-500 flex items-center gap-1 mt-0.5">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                Simulated
              </div>
            </div>
          </div>
        </div>
      </div>
    </header>
  );
};

