import React, { useEffect, useRef, useState } from 'react';
import { createChart, ColorType, IChartApi, CandlestickSeries, AreaSeries } from 'lightweight-charts';
import { Maximize2, BarChart2, TrendingUp } from 'lucide-react';
import { formatINR } from '../utils/format';

interface MarketChartProps {
  symbol: string;
  name: string;
  currentPrice: number;
  currency?: string;
  simulated?: boolean;
}

export const MarketChart: React.FC<MarketChartProps> = ({
  symbol,
  name,
  currentPrice,
  currency = 'INR',
  simulated = true,
}) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [chartType, setChartType] = useState<'candlestick' | 'area'>('area');
  const [timeframe, setTimeframe] = useState<'1D' | '1W' | '1M' | '1Y'>('1M');

  // Generate deterministic synthetic candlestick data around the currentPrice
  const generateMockData = (basePrice: number, points: number) => {
    const data = [];
    const now = new Date();
    // seed calculation based on symbol characters
    let seed = symbol.split('').reduce((acc, c) => acc + c.charCodeAt(0), 42);
    const random = () => {
      seed = (seed * 9301 + 49297) % 233280;
      return seed / 233280;
    };

    let price = basePrice * 0.92;
    for (let i = points; i >= 0; i--) {
      const date = new Date(now.getTime() - i * 24 * 60 * 60 * 1000);
      const timeStr = date.toISOString().split('T')[0];
      const change = (random() - 0.48) * (basePrice * 0.025);
      const open = price;
      const close = i === 0 ? basePrice : price + change;
      const high = Math.max(open, close) + random() * (basePrice * 0.012);
      const low = Math.min(open, close) - random() * (basePrice * 0.012);
      price = close;

      data.push({
        time: timeStr,
        open: parseFloat(open.toFixed(2)),
        high: parseFloat(high.toFixed(2)),
        low: parseFloat(low.toFixed(2)),
        close: parseFloat(close.toFixed(2)),
        value: parseFloat(close.toFixed(2)), // for area chart
      });
    }
    return data;
  };

  useEffect(() => {
    if (!chartContainerRef.current) return;

    // Clear previous chart if any
    chartContainerRef.current.innerHTML = '';

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#0f172a' },
        textColor: '#94a3b8',
      },
      grid: {
        vertLines: { color: 'rgba(255, 255, 255, 0.04)' },
        horzLines: { color: 'rgba(255, 255, 255, 0.04)' },
      },
      crosshair: {
        vertLine: { color: '#6366f1', width: 1, style: 2 },
        horzLine: { color: '#6366f1', width: 1, style: 2 },
      },
      timeScale: {
        borderColor: 'rgba(255, 255, 255, 0.08)',
        timeVisible: true,
      },
      rightPriceScale: {
        borderColor: 'rgba(255, 255, 255, 0.08)',
      },
      width: chartContainerRef.current.clientWidth,
      height: 340,
    });

    chartRef.current = chart;

    const points = timeframe === '1D' ? 30 : timeframe === '1W' ? 60 : timeframe === '1M' ? 120 : 365;
    const seriesData = generateMockData(currentPrice || 1000, points);

    if (chartType === 'candlestick') {
      const candleSeries = chart.addSeries(CandlestickSeries, {
        upColor: '#10b981',
        downColor: '#ef4444',
        borderVisible: false,
        wickUpColor: '#10b981',
        wickDownColor: '#ef4444',
      });
      candleSeries.setData(seriesData);
    } else {
      const areaSeries = chart.addSeries(AreaSeries, {
        topColor: 'rgba(99, 102, 241, 0.45)',
        bottomColor: 'rgba(99, 102, 241, 0.02)',
        lineColor: '#818cf8',
        lineWidth: 2,
      });
      areaSeries.setData(
        seriesData.map((d) => ({
          time: d.time,
          value: d.value,
        }))
      );
    }

    chart.timeScale().fitContent();

    const handleResize = () => {
      if (chartContainerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: chartContainerRef.current.clientWidth,
        });
      }
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, [symbol, currentPrice, chartType, timeframe]);

  return (
    <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-2xl backdrop-blur-md">
      {/* Chart Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 mb-4 pb-3 border-b border-slate-800/80">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-xl font-bold text-white tracking-tight">{symbol}</span>
            <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 font-medium">
              NSE Equity
            </span>
            {simulated && (
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20 font-semibold tracking-wide">
                SIMULATED DATA
              </span>
            )}
          </div>
          <p className="text-xs text-slate-400 font-medium mt-0.5">{name}</p>
        </div>

        <div className="flex items-center gap-6">
          <div className="text-right">
            <div className="text-2xl font-bold font-mono-nums text-white">
              {formatINR(currentPrice)}
            </div>
            <div className="text-xs font-semibold text-emerald-400 flex items-center justify-end gap-1">
              <TrendingUp className="w-3.5 h-3.5" /> +1.28% today
            </div>
          </div>

          {/* Controls */}
          <div className="flex items-center gap-1.5 bg-slate-950 p-1 rounded-xl border border-slate-800">
            <button
              onClick={() => setChartType('area')}
              className={`p-1.5 rounded-lg text-xs transition-all ${
                chartType === 'area'
                  ? 'bg-indigo-600 text-white shadow'
                  : 'text-slate-400 hover:text-white'
              }`}
              title="Area Chart"
            >
              <TrendingUp className="w-4 h-4" />
            </button>
            <button
              onClick={() => setChartType('candlestick')}
              className={`p-1.5 rounded-lg text-xs transition-all ${
                chartType === 'candlestick'
                  ? 'bg-indigo-600 text-white shadow'
                  : 'text-slate-400 hover:text-white'
              }`}
              title="Candlestick Chart"
            >
              <BarChart2 className="w-4 h-4" />
            </button>
          </div>

          {/* Timeframes */}
          <div className="flex items-center gap-1 bg-slate-950 p-1 rounded-xl border border-slate-800">
            {(['1D', '1W', '1M', '1Y'] as const).map((tf) => (
              <button
                key={tf}
                onClick={() => setTimeframe(tf)}
                className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-all ${
                  timeframe === tf
                    ? 'bg-slate-800 text-white font-bold'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {tf}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Chart Canvas */}
      <div ref={chartContainerRef} className="w-full rounded-xl overflow-hidden" />
    </div>
  );
};

