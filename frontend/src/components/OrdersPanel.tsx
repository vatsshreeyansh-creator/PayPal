import React, { useState } from 'react';
import { History, CheckCircle2, XCircle, ArrowUpRight, ArrowDownLeft, RefreshCw } from 'lucide-react';
import { Order, Transaction } from '../types/api';
import { formatINR, formatDateTime } from '../utils/format';

interface OrdersPanelProps {
  orders: Order[];
  transactions: Transaction[];
  loading: boolean;
  onRefresh: () => void;
}

export const OrdersPanel: React.FC<OrdersPanelProps> = ({
  orders,
  transactions,
  loading,
  onRefresh,
}) => {
  const [tab, setTab] = useState<'orders' | 'transactions'>('orders');

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-2xl backdrop-blur-md">
      {/* Header & Tabs */}
      <div className="flex flex-wrap items-center justify-between gap-4 pb-4 border-b border-slate-800">
        <div className="flex items-center gap-2">
          <History className="w-5 h-5 text-indigo-400" />
          <h2 className="text-lg font-bold text-white">Order & Execution Activity</h2>
          <button
            onClick={onRefresh}
            disabled={loading}
            className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
            title="Refresh Activity"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>

        <div className="flex items-center gap-1 bg-slate-950 p-1 rounded-xl border border-slate-800">
          <button
            onClick={() => setTab('orders')}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
              tab === 'orders'
                ? 'bg-indigo-600 text-white shadow'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            Orders Log ({orders.length})
          </button>
          <button
            onClick={() => setTab('transactions')}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
              tab === 'transactions'
                ? 'bg-indigo-600 text-white shadow'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            Settled Transactions ({transactions.length})
          </button>
        </div>
      </div>

      {/* Content Table */}
      <div className="mt-4 overflow-x-auto">
        {tab === 'orders' ? (
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-slate-800 text-slate-400 font-semibold uppercase tracking-wider text-[10px]">
                <th className="pb-3 pl-2">Time</th>
                <th className="pb-3">Symbol</th>
                <th className="pb-3">Side</th>
                <th className="pb-3 text-right">Qty</th>
                <th className="pb-3 text-right">Exec Price</th>
                <th className="pb-3 text-center">Status</th>
                <th className="pb-3 text-right pr-2">Order ID</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 font-mono-nums">
              {orders.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-slate-500 font-sans">
                    No orders have been submitted yet.
                  </td>
                </tr>
              ) : (
                orders.map((o) => {
                  const isFilled = o.status === 'FILLED';
                  return (
                    <tr key={o.order_id} className="hover:bg-slate-800/40 transition-colors">
                      <td className="py-3 pl-2 text-slate-400 font-sans text-[11px]">
                        {formatDateTime(o.executed_at || o.requested_at)}
                      </td>
                      <td className="py-3 font-bold text-white font-sans">{o.symbol}</td>
                      <td className="py-3">
                        <span
                          className={`inline-flex items-center gap-1 font-bold ${
                            o.side === 'BUY' ? 'text-emerald-400' : 'text-rose-400'
                          }`}
                        >
                          {o.side === 'BUY' ? (
                            <ArrowDownLeft className="w-3.5 h-3.5" />
                          ) : (
                            <ArrowUpRight className="w-3.5 h-3.5" />
                          )}
                          {o.side}
                        </span>
                      </td>
                      <td className="py-3 text-right font-bold text-white">{o.quantity}</td>
                      <td className="py-3 text-right font-bold text-slate-200">
                        {o.execution_price ? formatINR(o.execution_price) : '—'}
                      </td>
                      <td className="py-3 text-center font-sans">
                        <span
                          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold ${
                            isFilled
                              ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                              : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                          }`}
                        >
                          {isFilled ? (
                            <CheckCircle2 className="w-3 h-3" />
                          ) : (
                            <XCircle className="w-3 h-3" />
                          )}
                          {o.status}
                        </span>
                      </td>
                      <td className="py-3 text-right pr-2 text-slate-400 text-[11px]">
                        {o.order_id.slice(0, 8)}...
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        ) : (
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-slate-800 text-slate-400 font-semibold uppercase tracking-wider text-[10px]">
                <th className="pb-3 pl-2">Time</th>
                <th className="pb-3">Symbol</th>
                <th className="pb-3">Side</th>
                <th className="pb-3 text-right">Quantity</th>
                <th className="pb-3 text-right">Execution Price</th>
                <th className="pb-3 text-right pr-2">Gross Amount</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 font-mono-nums">
              {transactions.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-slate-500 font-sans">
                    No completed transactions yet.
                  </td>
                </tr>
              ) : (
                transactions.map((tx) => (
                  <tr key={tx.transaction_id} className="hover:bg-slate-800/40 transition-colors">
                    <td className="py-3 pl-2 text-slate-400 font-sans text-[11px]">
                      {formatDateTime(tx.executed_at)}
                    </td>
                    <td className="py-3 font-bold text-white font-sans">{tx.symbol}</td>
                    <td className="py-3">
                      <span
                        className={`font-bold ${
                          tx.side === 'BUY' ? 'text-emerald-400' : 'text-rose-400'
                        }`}
                      >
                        {tx.side}
                      </span>
                    </td>
                    <td className="py-3 text-right font-bold text-white">{tx.quantity}</td>
                    <td className="py-3 text-right text-slate-200">{formatINR(tx.price)}</td>
                    <td className="py-3 text-right pr-2 font-bold text-white">
                      {formatINR(tx.gross_amount)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};

