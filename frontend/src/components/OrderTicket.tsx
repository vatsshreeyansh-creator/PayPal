import React, { useEffect, useRef, useState } from 'react';
import { ArrowUpRight, ArrowDownLeft, AlertCircle, CheckCircle2, ShieldCheck, Zap } from 'lucide-react';
import { api } from '../services/api';
import { formatINR } from '../utils/format';
import { sound } from '../utils/sound';
import { createOrderIntentKey } from '../utils/orderIntent';
import type { OrderResponse } from '../types/api';

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Order submission failed.';
}

interface OrderTicketProps {
  initialSymbol?: string;
  initialPrice?: string | null;
  availableCash: string | null;
  currentHoldingQty?: string;
  onOrderSuccess: (order: OrderResponse) => void;
  onClose?: () => void;
}

export const OrderTicket: React.FC<OrderTicketProps> = ({
  initialSymbol = '', initialPrice = null, availableCash, currentHoldingQty = '0',
  onOrderSuccess, onClose,
}) => {
  const [symbol, setSymbol] = useState(initialSymbol);
  const [side, setSide] = useState<'BUY' | 'SELL'>('BUY');
  const [quantity, setQuantity] = useState('1');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<OrderResponse | null>(null);
  const intentKey = useRef(createOrderIntentKey());

  useEffect(() => {
    setSymbol(initialSymbol);
    intentKey.current = createOrderIntentKey();
  }, [initialSymbol]);

  const newIntent = () => {
    intentKey.current = createOrderIntentKey();
    setResult(null);
    setError(null);
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!symbol.trim() || !/^[1-9]\d*$/.test(quantity) || Number(quantity) > 100000 || loading) return;
    setError(null);
    setLoading(true);
    try {
      const response = await api.placeOrder({
        symbol: symbol.trim().toUpperCase(), side, quantity: Number(quantity), order_type: 'MARKET',
        idempotency_key: intentKey.current,
      });
      setResult(response);
      intentKey.current = createOrderIntentKey();
      if (response.status === 'FILLED') sound.playOrderSuccess();
      onOrderSuccess(response);
      if (response.status === 'FILLED') {
        window.setTimeout(() => onClose?.(), 2500);
      }
    } catch (requestError: unknown) {
      // Keep the key after transport/5xx failures so retrying the same intent is safe.
      setError(errorMessage(requestError));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-2xl relative overflow-hidden">
      <div className="flex items-center justify-between pb-3 border-b border-slate-800 mb-4">
        <div className="flex items-center gap-2"><Zap className="w-5 h-5 text-indigo-400" /><h3 className="font-bold text-white text-base">Quick Order Ticket</h3></div>
        <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">PAPER ORDER</span>
      </div>

      {result && (
        <div role="status" className={`mb-4 p-3 rounded-xl border text-sm ${result.status === 'FILLED' ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300' : 'border-rose-500/30 bg-rose-500/10 text-rose-300'}`}>
          <div className="flex items-center gap-2 font-bold">
            {result.status === 'FILLED' ? <CheckCircle2 className="w-4 h-4" /> : <AlertCircle className="w-4 h-4" />}
            {result.status === 'FILLED' ? 'Order filled' : 'Order rejected'}
          </div>
          <p className="mt-1 text-xs">{result.side} {result.quantity} {result.symbol}
            {result.status === 'FILLED' ? ` at ${formatINR(result.execution_price)}` : `: ${result.rejection_reason?.replaceAll('_', ' ').toLowerCase()}`}
          </p>
          <p className="text-[10px] mt-1 opacity-80">Order ID: {result.order_id}</p>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid grid-cols-2 gap-2 p-1 bg-slate-950 rounded-xl border border-slate-800">
          <button type="button" onClick={() => { if (side !== 'BUY') newIntent(); setSide('BUY'); }} className={`py-2.5 rounded-lg text-xs font-bold ${side === 'BUY' ? 'bg-emerald-600 text-white' : 'text-slate-400'}`}><ArrowDownLeft className="inline w-4 h-4" /> BUY</button>
          <button type="button" onClick={() => { if (side !== 'SELL') newIntent(); setSide('SELL'); }} className={`py-2.5 rounded-lg text-xs font-bold ${side === 'SELL' ? 'bg-rose-600 text-white' : 'text-slate-400'}`}><ArrowUpRight className="inline w-4 h-4" /> SELL</button>
        </div>
        <label className="block text-xs text-slate-400">Stock symbol
          <input value={symbol} onChange={(event) => { newIntent(); setSymbol(event.target.value.toUpperCase()); }} required className="mt-1 w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-sm font-bold text-white" />
        </label>
        <label className="block text-xs text-slate-400">Quantity (whole shares)
          <input type="number" min="1" max="100000" step="1" value={quantity} onChange={(event) => { newIntent(); setQuantity(event.target.value); }} required className="mt-1 w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-sm font-bold text-white" />
        </label>
        <div className="text-xs text-slate-400 space-y-1">
          <p>Available cash: {availableCash === null ? 'Unavailable' : formatINR(availableCash)}</p>
          <p>Owned shares: {currentHoldingQty}</p>
          <p>Quote: {initialPrice === null ? 'Unavailable; server will determine order outcome.' : formatINR(initialPrice)}</p>
          <p className="text-[10px]">Final price and balance validation come from the backend.</p>
        </div>
        {error && <div role="alert" className="p-2.5 bg-rose-500/10 border border-rose-500/20 rounded-xl text-xs text-rose-300"><AlertCircle className="inline w-4 h-4 mr-1" />{error}</div>}
        <button type="submit" disabled={loading || !symbol.trim()} className="w-full py-3 rounded-xl font-bold text-sm bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 text-white flex items-center justify-center gap-2">
          {loading ? 'Submitting…' : <><ShieldCheck className="w-4 h-4" /> Submit simulated {side}</>}
        </button>
      </form>
    </div>
  );
};
