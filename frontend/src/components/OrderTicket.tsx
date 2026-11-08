import React, { useState, useEffect } from 'react';
import { ArrowUpRight, ArrowDownLeft, AlertCircle, CheckCircle2, ShieldCheck, Zap } from 'lucide-react';
import { api } from '../services/api';
import { formatINR } from '../utils/format';
import { sound } from '../utils/sound';
import { Order } from '../types/api';

interface OrderTicketProps {
  initialSymbol?: string;
  initialPrice?: number;
  availableCash: number;
  currentHoldingQty?: number;
  onOrderSuccess: (order: Order) => void;
  onClose?: () => void;
}

export const OrderTicket: React.FC<OrderTicketProps> = ({
  initialSymbol = 'TCS',
  initialPrice = 3850,
  availableCash,
  currentHoldingQty = 0,
  onOrderSuccess,
  onClose,
}) => {
  const [symbol, setSymbol] = useState(initialSymbol);
  const [side, setSide] = useState<'BUY' | 'SELL'>('BUY');
  const [quantity, setQuantity] = useState<number>(1);
  const [price, setPrice] = useState<number>(initialPrice);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successOrder, setSuccessOrder] = useState<Order | null>(null);

  useEffect(() => {
    if (initialSymbol) setSymbol(initialSymbol);
    if (initialPrice) setPrice(initialPrice);
  }, [initialSymbol, initialPrice]);

  const grossAmount = quantity * (price || 0);
  const canAfford = side === 'SELL' || grossAmount <= availableCash;
  const canSell = side === 'BUY' || quantity <= currentHoldingQty;

  const handlePreset = (addQty: number) => {
    setQuantity((prev) => Math.max(1, prev + addQty));
  };

  const handleMax = () => {
    if (side === 'BUY' && price > 0) {
      const maxBuy = Math.floor(availableCash / price);
      setQuantity(Math.max(1, maxBuy));
    } else if (side === 'SELL') {
      setQuantity(Math.max(1, currentHoldingQty));
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!symbol.trim() || quantity <= 0) return;
    setError(null);
    setLoading(true);

    try {
      const res = await api.placeOrder({
        symbol: symbol.trim().toUpperCase(),
        side,
        quantity,
        order_type: 'MARKET',
      });

      setSuccessOrder(res.order);
      sound.playOrderSuccess();
      onOrderSuccess(res.order);

      // Auto close or reset after 2.5s
      setTimeout(() => {
        setSuccessOrder(null);
        if (onClose) onClose();
      }, 2500);
    } catch (err: any) {
      setError(err.message || 'Order submission failed.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-2xl backdrop-blur-md relative overflow-hidden">
      {/* Background glow based on side */}
      <div
        className={`absolute -top-24 -right-24 w-48 h-48 rounded-full blur-3xl opacity-20 pointer-events-none ${
          side === 'BUY' ? 'bg-emerald-500' : 'bg-rose-500'
        }`}
      />

      {/* Header */}
      <div className="flex items-center justify-between pb-3 border-b border-slate-800 mb-4">
        <div className="flex items-center gap-2">
          <Zap className="w-5 h-5 text-indigo-400" />
          <h3 className="font-bold text-white text-base">Quick Order Ticket</h3>
        </div>
        <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
          INSTANT SIMULATION
        </span>
      </div>

      {successOrder ? (
        <div className="py-8 text-center animate-in fade-in zoom-in-95 duration-200">
          <div className="w-14 h-14 bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 rounded-2xl flex items-center justify-center mx-auto mb-3">
            <CheckCircle2 className="w-8 h-8" />
          </div>
          <h4 className="text-lg font-bold text-white">Order Executed!</h4>
          <p className="text-xs text-slate-400 mt-1">
            {successOrder.side} {successOrder.quantity} {successOrder.symbol} @{' '}
            {formatINR(successOrder.execution_price)}
          </p>
          <div className="mt-4 p-3 bg-slate-950 rounded-xl text-[11px] text-slate-400 font-mono-nums">
            Order ID: {successOrder.order_id}
          </div>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Side Toggle: BUY vs SELL */}
          <div className="grid grid-cols-2 gap-2 p-1 bg-slate-950 rounded-xl border border-slate-800">
            <button
              type="button"
              onClick={() => setSide('BUY')}
              className={`flex items-center justify-center gap-1.5 py-2.5 rounded-lg text-xs font-bold transition-all ${
                side === 'BUY'
                  ? 'bg-emerald-600 text-white shadow-lg shadow-emerald-900/30'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              <ArrowDownLeft className="w-4 h-4" /> BUY
            </button>
            <button
              type="button"
              onClick={() => setSide('SELL')}
              className={`flex items-center justify-center gap-1.5 py-2.5 rounded-lg text-xs font-bold transition-all ${
                side === 'SELL'
                  ? 'bg-rose-600 text-white shadow-lg shadow-rose-900/30'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              <ArrowUpRight className="w-4 h-4" /> SELL
            </button>
          </div>

          {/* Symbol & Market Quote */}
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1">Stock Symbol</label>
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={symbol}
                onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                placeholder="e.g. TCS"
                required
                className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-sm font-bold text-white tracking-wide uppercase focus:outline-none focus:border-indigo-500"
              />
              <div className="text-right whitespace-nowrap px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl">
                <span className="text-[10px] text-slate-500 block leading-none">Est. Quote</span>
                <span className="text-xs font-bold font-mono-nums text-white">
                  {formatINR(price)}
                </span>
              </div>
            </div>
          </div>

          {/* Quantity Input & Stepper */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-xs font-medium text-slate-400">Quantity</label>
              <span className="text-[11px] text-slate-400">
                {side === 'BUY'
                  ? `Available Cash: ${formatINR(availableCash)}`
                  : `Owned Shares: ${currentHoldingQty}`}
              </span>
            </div>

            <div className="flex items-center gap-2">
              <input
                type="number"
                min="1"
                max="100000"
                value={quantity}
                onChange={(e) => setQuantity(Math.max(1, parseInt(e.target.value) || 1))}
                className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-sm font-bold font-mono-nums text-white focus:outline-none focus:border-indigo-500"
              />
              <button
                type="button"
                onClick={handleMax}
                className="px-3 py-2 rounded-xl text-xs font-bold bg-slate-800 hover:bg-slate-700 text-indigo-400 border border-slate-700 transition-colors"
              >
                MAX
              </button>
            </div>

            {/* Quick chips */}
            <div className="flex items-center gap-1.5 mt-2">
              {[+1, +5, +25, +100].map((add) => (
                <button
                  key={add}
                  type="button"
                  onClick={() => handlePreset(add)}
                  className="px-2 py-1 bg-slate-950 hover:bg-slate-800 rounded-lg text-[11px] font-semibold text-slate-400 hover:text-white border border-slate-800 transition-colors"
                >
                  +{add}
                </button>
              ))}
            </div>
          </div>

          {/* Calculation Summary Card */}
          <div className="p-3 bg-slate-950 rounded-xl border border-slate-800/80 space-y-1.5 text-xs">
            <div className="flex justify-between text-slate-400">
              <span>Order Type</span>
              <span className="font-semibold text-slate-300">MARKET (Immediate)</span>
            </div>
            <div className="flex justify-between text-slate-400">
              <span>Estimated Gross</span>
              <span className="font-bold font-mono-nums text-white text-sm">
                {formatINR(grossAmount)}
              </span>
            </div>
            {side === 'BUY' && !canAfford && (
              <div className="flex items-center gap-1.5 text-rose-400 text-[11px] pt-1">
                <AlertCircle className="w-3.5 h-3.5 shrink-0" />
                <span>Insufficient funds (Short by {formatINR(grossAmount - availableCash)})</span>
              </div>
            )}
            {side === 'SELL' && !canSell && (
              <div className="flex items-center gap-1.5 text-rose-400 text-[11px] pt-1">
                <AlertCircle className="w-3.5 h-3.5 shrink-0" />
                <span>Quantity exceeds holdings (You own {currentHoldingQty} shares)</span>
              </div>
            )}
          </div>

          {error && (
            <div className="p-2.5 bg-rose-500/10 border border-rose-500/20 rounded-xl text-xs text-rose-400 flex items-start gap-2">
              <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          {/* Submit Button */}
          <button
            type="submit"
            disabled={loading || (side === 'BUY' && !canAfford) || (side === 'SELL' && !canSell)}
            className={`w-full py-3 rounded-xl font-bold text-sm tracking-wide transition-all shadow-xl flex items-center justify-center gap-2 ${
              side === 'BUY'
                ? 'bg-emerald-500 hover:bg-emerald-400 text-slate-950 shadow-emerald-500/20 disabled:bg-slate-800 disabled:text-slate-600'
                : 'bg-rose-500 hover:bg-rose-400 text-white shadow-rose-500/20 disabled:bg-slate-800 disabled:text-slate-600'
            }`}
          >
            {loading ? (
              <div className="w-5 h-5 border-2 border-slate-900 border-t-transparent rounded-full animate-spin" />
            ) : (
              <>
                <ShieldCheck className="w-4 h-4" />
                <span>
                  Execute {side} {quantity} {symbol}
                </span>
              </>
            )}
          </button>
        </form>
      )}
    </div>
  );
};

