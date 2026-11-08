import React from 'react';
import { BarChart2 } from 'lucide-react';
import { formatINR } from '../utils/format';

interface MarketChartProps {
  symbol: string;
  name: string;
  currentPrice: string | null;
  simulated: boolean | null;
}

export const MarketChart: React.FC<MarketChartProps> = ({ symbol, name, currentPrice, simulated }) => (
  <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-2xl">
    <div className="flex items-center justify-between gap-4 pb-3 border-b border-slate-800/80">
      <div><div className="flex items-center gap-2"><span className="text-xl font-bold text-white">{symbol || 'Select a stock'}</span>{simulated === true && <span className="text-[10px] px-2 py-0.5 rounded bg-amber-500/10 text-amber-300">DEMO QUOTE</span>}</div><p className="text-xs text-slate-400 mt-1">{name}</p></div>
      <div className="text-right"><div className="text-xl font-bold text-white">{currentPrice === null ? 'Quote unavailable' : formatINR(currentPrice)}</div><span className="text-[10px] text-slate-500">{simulated === null ? 'No quote selected' : simulated ? 'Simulated quote' : 'Provider quote'}</span></div>
    </div>
    <div className="h-64 mt-4 rounded-xl border border-dashed border-slate-700 flex flex-col items-center justify-center text-center px-6">
      <BarChart2 className="w-8 h-8 text-slate-500 mb-2" />
      <p className="text-sm font-semibold text-slate-300">Historical chart unavailable</p>
      <p className="text-xs text-slate-500 mt-1">TradePoint has no historical-price API yet. No generated price history is shown.</p>
    </div>
  </div>
);

