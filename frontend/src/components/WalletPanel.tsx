import React, { useState, useEffect } from 'react';
import {
  Wallet,
  ArrowUpRight,
  ArrowDownRight,
  Clock,
  CheckCircle2,
  AlertCircle,
  ExternalLink,
  ShieldCheck,
  RefreshCw,
  XCircle,
  AlertTriangle,
  CreditCard,
} from 'lucide-react';
import { api, ApiError } from '../services/api';
import type {
  WalletSummaryResponse,
  WalletHistoryResponse,
  WalletHistoryItem,
  PayPalCaptureOrderResponse,
} from '../types/api';
import { formatINR, formatDateTime } from '../utils/format';

interface WalletPanelProps {
  onBalanceUpdated?: () => void;
}

type DepositFlowState =
  | 'IDLE'
  | 'CREATING_ORDER'
  | 'APPROVAL_PENDING'
  | 'CAPTURING'
  | 'COMPLETED'
  | 'REQUIRES_RECONCILIATION'
  | 'FAILED'
  | 'CANCELLED';

interface StoredPendingDeposit {
  deposit_id: string;
  paypal_order_id: string;
  idempotency_key: string;
  amount_usd: string;
  approval_url?: string | null;
}

const STORAGE_KEY = 'tradepoint_pending_deposit';

export const isAuthorizedSandboxUrl = (url?: string | null): boolean => {
  if (!url || typeof url !== 'string') return false;
  try {
    const parsed = new URL(url.trim());
    const hostname = parsed.hostname.toLowerCase();
    return (
      parsed.protocol === 'https:' &&
      (hostname === 'www.sandbox.paypal.com' || hostname === 'sandbox.paypal.com') &&
      !parsed.username &&
      !parsed.password &&
      (parsed.port === '' || parsed.port === '443')
    );
  } catch {
    return false;
  }
};

export const WalletPanel: React.FC<WalletPanelProps> = ({ onBalanceUpdated }) => {
  // Data state
  const [summary, setSummary] = useState<WalletSummaryResponse | null>(null);
  const [history, setHistory] = useState<WalletHistoryResponse | null>(null);
  const [loadingSummary, setLoadingSummary] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Deposit Form state
  const [amountUsd, setAmountUsd] = useState('100.00');
  const [formError, setFormError] = useState<string | null>(null);
  const [flowState, setFlowState] = useState<DepositFlowState>('IDLE');
  const [activeDeposit, setActiveDeposit] = useState<StoredPendingDeposit | null>(null);
  const [captureResult, setCaptureResult] = useState<PayPalCaptureOrderResponse | null>(null);
  const [flowMessage, setFlowMessage] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [cancellationError, setCancellationError] = useState<string | null>(null);

  // Load wallet summary and history
  const loadWalletData = async () => {
    setLoadingSummary(true);
    setLoadingHistory(true);
    setError(null);
    try {
      const [sum, hist] = await Promise.all([
        api.getWalletSummary(),
        api.getWalletHistory(),
      ]);
      setSummary(sum);
      setHistory(hist);
      onBalanceUpdated?.();
    } catch (err: unknown) {
      const msg = err instanceof ApiError ? err.message : 'Failed to load wallet data.';
      setError(msg);
    } finally {
      setLoadingSummary(false);
      setLoadingHistory(false);
    }
  };

  useEffect(() => {
    loadWalletData();
  }, []);

  // Handle Return from PayPal via URL Query Parameters (or stored deposit recovery)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const token = params.get('token') || params.get('order_id');
    const isCancelled = params.get('cancelled') === 'true' || params.get('cancel') === 'true';

    // Retrieve any pending deposit retained in session
    let stored: StoredPendingDeposit | null = null;
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      if (raw) stored = JSON.parse(raw);
    } catch {
      // Ignore JSON parse errors
    }

    if (token) {
      const orderId = token;
      const idemKey = stored?.paypal_order_id === orderId ? stored.idempotency_key : `return-cap-${orderId}`;

      // Clean URL params to prevent repeated processing on manual page reload
      window.history.replaceState({}, document.title, window.location.pathname);

      if (isCancelled) {
        handleCancel(orderId);
      } else {
        handleCapture(orderId, idemKey);
      }
    } else if (stored && flowState === 'IDLE') {
      setActiveDeposit(stored);
      setFlowState('APPROVAL_PENDING');
    }
  }, []);

  // Validation
  const validateAmount = (val: string): boolean => {
    setFormError(null);
    const trimmed = val.trim();
    if (!trimmed) {
      setFormError('Please enter a deposit amount in USD.');
      return false;
    }
    const num = Number(trimmed);
    if (isNaN(num) || num <= 0) {
      setFormError('Deposit amount must be a positive number.');
      return false;
    }
    if (!/^\d+(\.\d{1,2})?$/.test(trimmed)) {
      setFormError('Amount can have at most 2 decimal places.');
      return false;
    }
    if (num < 1.0) {
      setFormError('Minimum deposit amount is $1.00 USD.');
      return false;
    }
    if (num > 10000.0) {
      setFormError('Maximum single deposit amount is $10,000.00 USD.');
      return false;
    }
    return true;
  };

  // Step 1: Create PayPal Order
  const handleInitiateDeposit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validateAmount(amountUsd)) return;
    if (activeDeposit) {
      setFormError('An active deposit is already pending. Please complete or cancel it before starting a new deposit.');
      return;
    }

    setFlowState('CREATING_ORDER');
    setFlowMessage(null);
    setError(null);

    const formattedAmount = Number(amountUsd).toFixed(2);
    // Unique idempotency key per deposit initiation attempt
    const idempotencyKey = `dep-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;

    try {
      const res = await api.createPayPalOrder({
        amount: formattedAmount,
        currency: 'USD',
        idempotency_key: idempotencyKey,
      });

      const pending: StoredPendingDeposit = {
        deposit_id: res.deposit_id,
        paypal_order_id: res.paypal_order_id,
        idempotency_key: idempotencyKey,
        amount_usd: formattedAmount,
        approval_url: res.approval_url || null,
      };

      setActiveDeposit(pending);
      try {
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify(pending));
      } catch {
        // sessionStorage fallback
      }

      setFlowState('APPROVAL_PENDING');
    } catch (err: unknown) {
      setFlowState('FAILED');
      const msg = err instanceof ApiError ? err.message : 'Could not create PayPal deposit order.';
      setFlowMessage(msg);
    }
  };

  // Step 2: Capture and Settle PayPal Order
  const handleCapture = async (orderId?: string, idempotencyKey?: string) => {
    const targetOrderId = orderId || activeDeposit?.paypal_order_id;

    if (!targetOrderId) {
      setFlowState('FAILED');
      setFlowMessage('Missing PayPal order reference to capture.');
      return;
    }

    setFlowState('CAPTURING');
    setFlowMessage('Capturing payment and verifying USD-to-INR settlement breakdown with PayPal...');
    setCancellationError(null);

    try {
      const res = await api.capturePayPalOrder({
        paypal_order_id: targetOrderId,
      });

      setCaptureResult(res);

      if (res.status === 'COMPLETED') {
        sessionStorage.removeItem(STORAGE_KEY);
        setFlowState('COMPLETED');
        setFlowMessage(null);
        await loadWalletData();
      } else if (res.status === 'REQUIRES_RECONCILIATION') {
        // Preserve pending deposit details for operator investigation
        setFlowState('REQUIRES_RECONCILIATION');
        const reasonText = res.failure_reason ? ` (${res.failure_reason})` : '';
        setFlowMessage(
          `Payment capture was received by PayPal${reasonText}, but settlement verification requires manual operator review. Please do not initiate another payment for this deposit. Your wallet balance will be updated once operator reconciliation is completed.`
        );
        await loadWalletData();
      } else {
        sessionStorage.removeItem(STORAGE_KEY);
        setFlowState('FAILED');
        setFlowMessage(res.failure_reason || 'PayPal capture could not be completed.');
      }
    } catch (err: unknown) {
      // Network timeout or unexpected server error:
      // DO NOT clear sessionStorage! Preserve activeDeposit so user can safely retry!
      setFlowState('FAILED');
      let msg = 'Network error occurred during payment capture.';
      if (err instanceof ApiError) {
        msg = err.message;
      }
      setFlowMessage(
        `Unable to confirm capture status: ${msg}. Your payment order (${targetOrderId}) is preserved. You can safely retry capture or check your balance.`
      );
      await loadWalletData();
    }
  };

  // Step 3: Cancel Deposit
  const handleCancel = async (orderId?: string) => {
    const targetOrderId = orderId || activeDeposit?.paypal_order_id;
    if (!targetOrderId) {
      resetDepositFlow();
      return;
    }

    setCancelling(true);
    setCancellationError(null);

    try {
      const res = await api.cancelPayPalOrder({ paypal_order_id: targetOrderId });
      if (res.status === 'CANCELLED') {
        sessionStorage.removeItem(STORAGE_KEY);
        setActiveDeposit(null);
        setFlowState('CANCELLED');
        setFlowMessage('Deposit was cancelled and authoritatively confirmed by PayPal. No funds were charged or credited.');
        await loadWalletData();
      } else {
        setCancellationError('Cancellation could not be confirmed by the server.');
        await loadWalletData();
      }
    } catch (err: unknown) {
      // Never swallow cancellation errors.
      // Do not clear the pending deposit from sessionStorage.
      // Do not display "No funds were charged."
      // Preserve activeDeposit so user can retry or investigate.
      let msg = 'Cancellation could not be confirmed due to an unexpected error.';
      if (err instanceof ApiError) {
        msg = `Cancellation could not be confirmed: ${err.message}`;
      }
      setCancellationError(msg);
      // Refresh wallet summary and history
      await loadWalletData();
    } finally {
      setCancelling(false);
    }
  };

  const resetDepositFlow = () => {
    sessionStorage.removeItem(STORAGE_KEY);
    setFlowState('IDLE');
    setActiveDeposit(null);
    setCaptureResult(null);
    setFlowMessage(null);
    setFormError(null);
    setCancellationError(null);
  };

  const presetAmounts = ['25.00', '50.00', '100.00', '250.00', '500.00'];

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      {/* Page Title & Subtitle */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-black tracking-tight text-white flex items-center gap-2.5">
            <Wallet className="w-6 h-6 text-indigo-400" />
            <span>Wallet & Balance</span>
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            Manage your INR cash ledger, deposit USD via PayPal Sandbox, and review unified cash movements.
          </p>
        </div>

        <button
          type="button"
          onClick={loadWalletData}
          disabled={loadingSummary || loadingHistory}
          className="self-start sm:self-auto flex items-center gap-2 px-3 py-1.5 bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-300 hover:text-white rounded-xl text-xs font-semibold transition-all disabled:opacity-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loadingSummary || loadingHistory ? 'animate-spin text-indigo-400' : ''}`} />
          <span>Refresh</span>
        </button>
      </div>

      {error && (
        <div role="alert" className="p-4 rounded-2xl bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs flex items-center gap-3">
          <AlertCircle className="w-4 h-4 shrink-0 text-rose-400" />
          <span>{error}</span>
        </div>
      )}

      {/* Top Balance & Metrics Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Available Cash Balance */}
        <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-xl backdrop-blur-md relative overflow-hidden">
          <div className="flex items-center justify-between text-slate-400 text-xs mb-1.5">
            <span className="font-semibold uppercase tracking-wider text-[10px]">Available Cash</span>
            <span className="px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-[10px] font-bold">
              Wallet: INR
            </span>
          </div>
          <div className="text-3xl font-black font-mono-nums text-emerald-400">
            {summary ? formatINR(summary.cash_balance) : '—'}
          </div>
          <p className="text-[11px] text-slate-400 mt-2 flex items-center gap-1.5 font-medium">
            <ShieldCheck className="w-3.5 h-3.5 text-indigo-400" />
            <span>Single source of truth (Cash Ledger)</span>
          </p>
        </div>

        {/* Total Completed Deposits */}
        <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-xl backdrop-blur-md">
          <div className="flex items-center justify-between text-slate-400 text-xs mb-1.5">
            <span className="font-semibold uppercase tracking-wider text-[10px]">Total Deposited</span>
            <ArrowDownRight className="w-4 h-4 text-indigo-400" />
          </div>
          <div className="text-3xl font-black font-mono-nums text-white">
            {summary ? formatINR(summary.total_deposited) : '—'}
          </div>
          <p className="text-[11px] text-slate-500 mt-2">Cumulative verified international deposits</p>
        </div>

        {/* Account Info */}
        <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-xl backdrop-blur-md">
          <div className="flex items-center justify-between text-slate-400 text-xs mb-1.5">
            <span className="font-semibold uppercase tracking-wider text-[10px]">Account ID</span>
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          </div>
          <div className="text-xl font-bold font-mono text-slate-200 truncate">
            {summary?.account_id || 'demo-user'}
          </div>
          <p className="text-[11px] text-slate-500 mt-2">Indian Equities Paper Trading Demo</p>
        </div>
      </div>

      {/* Add Funds Section & Status Alerts */}
      <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-6 shadow-xl backdrop-blur-md space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-800/80 pb-4">
          <div>
            <h2 className="text-base font-bold text-white flex items-center gap-2">
              <CreditCard className="w-4 h-4 text-indigo-400" />
              <span>Add Funds (International PayPal Deposit)</span>
            </h2>
            <p className="text-xs text-slate-400 mt-0.5">
              Pay in <strong className="text-white">USD</strong>; your TradePoint wallet receives verified <strong className="text-emerald-400">INR</strong> upon capture.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[11px] text-indigo-300 font-bold px-2 py-0.5 bg-indigo-500/10 border border-indigo-500/20 rounded-lg">
              PayPal Sandbox
            </span>
          </div>
        </div>

        {/* Dynamic Payment State Handling */}
        {flowState === 'COMPLETED' && captureResult && (
          <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-xs space-y-2 animate-in fade-in">
            <div className="flex items-center justify-between font-bold text-sm text-emerald-400">
              <span className="flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                Deposit Successfully Captured & Verified!
              </span>
              <button
                type="button"
                onClick={resetDepositFlow}
                className="text-[11px] text-slate-400 hover:text-white underline cursor-pointer"
              >
                Make Another Deposit
              </button>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-2 text-[11px] font-mono-nums text-slate-300">
              <div>
                <span className="text-slate-500 block text-[10px]">USD Paid:</span>
                <span className="font-bold text-white">${captureResult.payment_amount} USD</span>
              </div>
              <div>
                <span className="text-slate-500 block text-[10px]">PayPal Fee:</span>
                <span>{captureResult.paypal_fee_amount ? `$${captureResult.paypal_fee_amount} USD` : 'Included'}</span>
              </div>
              <div>
                <span className="text-slate-500 block text-[10px]">Exchange Rate:</span>
                <span className="text-indigo-300">{captureResult.exchange_rate ? `${captureResult.exchange_rate} USD→INR` : 'Settled'}</span>
              </div>
              <div>
                <span className="text-slate-500 block text-[10px]">INR Credited:</span>
                <span className="font-bold text-emerald-400">+{formatINR(captureResult.wallet_credit_amount)}</span>
              </div>
            </div>
          </div>
        )}

        {/* Cancellation Error Banner */}
        {cancellationError && (
          <div className="p-3.5 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs flex items-center justify-between animate-in fade-in">
            <div className="flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
              <span>{cancellationError}</span>
            </div>
            <button
              type="button"
              onClick={() => setCancellationError(null)}
              className="text-[11px] text-slate-400 hover:text-white underline cursor-pointer ml-2"
            >
              Dismiss
            </button>
          </div>
        )}

        {flowState === 'REQUIRES_RECONCILIATION' && (
          <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs space-y-3 animate-in fade-in">
            <div className="flex items-center justify-between font-bold text-sm text-amber-400">
              <span className="flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 text-amber-400" />
                Deposit Under Reconciliation
              </span>
            </div>
            <p className="text-[11px] text-amber-200/90 leading-relaxed">
              {flowMessage ||
                'Payment capture was received by PayPal, but settlement verification requires manual operator review. Please do not initiate another payment for this deposit. Your wallet balance will be updated once operator reconciliation is completed.'}
            </p>
            {(activeDeposit || captureResult) && (
              <div className="p-2.5 rounded-lg bg-amber-950/40 border border-amber-500/20 text-[11px] font-mono text-amber-200 space-y-1">
                <div>
                  <span className="text-amber-400 font-bold">PayPal Order ID:</span>{' '}
                  {activeDeposit?.paypal_order_id || captureResult?.paypal_order_id}
                </div>
                <div>
                  <span className="text-amber-400 font-bold">Deposit ID:</span>{' '}
                  {activeDeposit?.deposit_id || captureResult?.deposit_id}
                </div>
                <div>
                  <span className="text-amber-400 font-bold">Amount:</span> $
                  {activeDeposit?.amount_usd || captureResult?.payment_amount} USD
                </div>
              </div>
            )}
            <div className="flex items-center gap-3 pt-1">
              <button
                type="button"
                onClick={() => loadWalletData()}
                className="px-3.5 py-1.5 bg-amber-600/30 hover:bg-amber-600/50 text-amber-200 border border-amber-500/40 rounded-xl text-xs font-semibold flex items-center gap-1.5 transition-all cursor-pointer"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                <span>Check Wallet Balance</span>
              </button>
            </div>
          </div>
        )}

        {flowState === 'CANCELLED' && (
          <div className="p-4 rounded-xl bg-slate-800/80 border border-slate-700 text-slate-300 text-xs flex items-center justify-between animate-in fade-in">
            <div className="flex items-center gap-2">
              <XCircle className="w-4 h-4 text-slate-400" />
              <span>{flowMessage || 'Deposit checkout was cancelled. No funds were debited.'}</span>
            </div>
            <button
              type="button"
              onClick={resetDepositFlow}
              className="text-[11px] text-indigo-400 hover:text-indigo-300 font-bold"
            >
              Start Over
            </button>
          </div>
        )}

        {flowState === 'FAILED' && (
          <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs space-y-3 animate-in fade-in">
            <div className="flex items-center justify-between font-bold text-sm text-rose-400">
              <span className="flex items-center gap-2">
                <AlertCircle className="w-4 h-4 text-rose-400" />
                Deposit Request Failed
              </span>
              {!activeDeposit && (
                <button
                  type="button"
                  onClick={resetDepositFlow}
                  className="text-[11px] text-slate-400 hover:text-white underline cursor-pointer"
                >
                  Try Again
                </button>
              )}
            </div>
            <p className="text-[11px] text-rose-200/90 leading-relaxed">
              {flowMessage || 'Payment could not be processed.'}
            </p>
            {activeDeposit && (
              <div className="p-2.5 rounded-lg bg-rose-950/40 border border-rose-500/20 text-[11px] font-mono text-rose-200 space-y-1">
                <div>
                  <span className="text-rose-400 font-bold">PayPal Order ID:</span>{' '}
                  {activeDeposit.paypal_order_id}
                </div>
                <div>
                  <span className="text-rose-400 font-bold">Deposit ID:</span>{' '}
                  {activeDeposit.deposit_id}
                </div>
                <div>
                  <span className="text-rose-400 font-bold">Amount:</span> ${activeDeposit.amount_usd} USD
                </div>
              </div>
            )}
            {activeDeposit && (
              <div className="flex flex-wrap items-center gap-3 pt-1">
                <button
                  type="button"
                  onClick={() => handleCapture()}
                  className="px-3.5 py-1.5 bg-rose-600/30 hover:bg-rose-600/50 text-rose-100 border border-rose-500/40 rounded-xl text-xs font-bold flex items-center gap-1.5 transition-all cursor-pointer"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                  <span>Retry Capture</span>
                </button>
                <button
                  type="button"
                  onClick={() => loadWalletData()}
                  className="px-3.5 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white rounded-xl text-xs font-semibold transition-all cursor-pointer"
                >
                  Check Wallet Balance
                </button>
                <button
                  type="button"
                  onClick={() => handleCancel()}
                  disabled={cancelling}
                  className="px-3.5 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white rounded-xl text-xs font-semibold transition-all cursor-pointer disabled:opacity-50"
                >
                  {cancelling ? 'Cancelling...' : 'Cancel Deposit'}
                </button>
              </div>
            )}
          </div>
        )}

        {/* Approval Pending Banner (Ready for customer approval / capture handshake) */}
        {flowState === 'APPROVAL_PENDING' && activeDeposit && (
          <div className="p-4 rounded-xl bg-indigo-500/10 border border-indigo-500/30 text-indigo-200 text-xs space-y-3 animate-in fade-in">
            <div className="flex items-center justify-between font-bold text-indigo-300">
              <span className="flex items-center gap-2">
                <Clock className="w-4 h-4 text-indigo-400 animate-spin" />
                PayPal Sandbox Order Created: {activeDeposit.paypal_order_id}
              </span>
              <span className="font-mono text-white text-xs">${activeDeposit.amount_usd} USD</span>
            </div>

            {summary?.payment_mode === 'mock' ? (
              <>
                <p className="text-[11px] text-slate-300 leading-relaxed">
                  Backend is running in <strong className="text-indigo-300">Mock Payment Mode</strong>. You can simulate customer approval and execute capture directly below.
                </p>
                <div className="flex flex-wrap items-center gap-3 pt-1">
                  <button
                    type="button"
                    onClick={() => handleCapture()}
                    className="px-4 py-2 bg-gradient-to-r from-emerald-600 to-emerald-500 hover:from-emerald-500 hover:to-emerald-400 text-white rounded-xl text-xs font-bold shadow-lg shadow-emerald-900/30 flex items-center gap-2 transition-all cursor-pointer"
                  >
                    <CheckCircle2 className="w-3.5 h-3.5" />
                    <span>Simulate Customer Approval & Capture</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => handleCancel()}
                    disabled={cancelling}
                    className="px-3.5 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white rounded-xl text-xs font-semibold transition-all cursor-pointer disabled:opacity-50"
                  >
                    {cancelling ? 'Cancelling...' : 'Cancel Deposit'}
                  </button>
                </div>
              </>
            ) : (
              <>
                <p className="text-[11px] text-slate-300 leading-relaxed">
                  Please complete payment approval on PayPal Sandbox. Once approved and redirected back to TradePoint, settlement breakdown will be verified.
                </p>
                <div className="flex flex-wrap items-center gap-3 pt-1">
                  {isAuthorizedSandboxUrl(activeDeposit.approval_url) ? (
                    <a
                      href={activeDeposit.approval_url!}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="px-4 py-2 bg-gradient-to-r from-indigo-600 to-indigo-500 hover:from-indigo-500 hover:to-indigo-400 text-white rounded-xl text-xs font-bold shadow-lg shadow-indigo-900/30 flex items-center gap-2 transition-all cursor-pointer"
                    >
                      <span>Approve on PayPal Sandbox</span>
                      <ExternalLink className="w-3.5 h-3.5" />
                    </a>
                  ) : (
                    <div className="p-2.5 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs">
                      Authoritative Sandbox approval URL was not provided or failed security validation. You may check approval or cancel.
                    </div>
                  )}
                  <button
                    type="button"
                    onClick={() => handleCapture()}
                    className="px-3.5 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white rounded-xl text-xs font-semibold transition-all cursor-pointer"
                  >
                    Check Approval & Capture
                  </button>
                  <button
                    type="button"
                    onClick={() => handleCancel()}
                    disabled={cancelling}
                    className="px-3.5 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white rounded-xl text-xs font-semibold transition-all cursor-pointer disabled:opacity-50"
                  >
                    {cancelling ? 'Cancelling...' : 'Cancel Deposit'}
                  </button>
                </div>
              </>
            )}
          </div>
        )}

        {flowState === 'CAPTURING' && (
          <div className="p-4 rounded-xl bg-slate-800/90 border border-slate-700 text-slate-200 text-xs flex items-center gap-3 animate-pulse">
            <RefreshCw className="w-4 h-4 text-indigo-400 animate-spin shrink-0" />
            <span className="font-medium">
              {flowMessage || 'Capturing payment and verifying settlement with PayPal...'}
            </span>
          </div>
        )}

        {/* Deposit Form (When IDLE or initiating) */}
        {(flowState === 'IDLE' || flowState === 'CREATING_ORDER') && (
          <form onSubmit={handleInitiateDeposit} className="space-y-4">
            <div>
              <label htmlFor="usd-amount-input" className="block text-xs font-bold text-slate-300 mb-1.5">
                Deposit Amount (USD)
              </label>
              <div className="flex flex-col sm:flex-row gap-3">
                <div className="relative flex-1">
                  <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-400 font-bold text-sm">
                    $
                  </div>
                  <input
                    id="usd-amount-input"
                    type="text"
                    value={amountUsd}
                    onChange={(e) => setAmountUsd(e.target.value)}
                    placeholder="100.00"
                    disabled={flowState === 'CREATING_ORDER'}
                    className="w-full pl-8 pr-16 py-2.5 bg-slate-950 border border-slate-700 rounded-xl text-white font-mono text-sm focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all disabled:opacity-50"
                  />
                  <div className="absolute inset-y-0 right-0 pr-3.5 flex items-center pointer-events-none text-slate-500 text-xs font-bold">
                    USD
                  </div>
                </div>

                <button
                  type="submit"
                  disabled={flowState === 'CREATING_ORDER'}
                  className="px-6 py-2.5 bg-gradient-to-r from-indigo-600 to-indigo-500 hover:from-indigo-500 hover:to-indigo-400 text-white rounded-xl text-xs font-bold shadow-lg shadow-indigo-600/30 flex items-center justify-center gap-2 transition-all disabled:opacity-50 cursor-pointer"
                >
                  {flowState === 'CREATING_ORDER' ? (
                    <>
                      <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                      <span>Creating Order...</span>
                    </>
                  ) : (
                    <>
                      <ExternalLink className="w-3.5 h-3.5" />
                      <span>Continue to PayPal</span>
                    </>
                  )}
                </button>
              </div>

              {formError && (
                <p className="text-[11px] text-rose-400 mt-1.5 flex items-center gap-1 font-medium">
                  <AlertCircle className="w-3 h-3 shrink-0" />
                  <span>{formError}</span>
                </p>
              )}
            </div>

            {/* Quick Preset Buttons */}
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <span className="text-[10px] uppercase font-bold text-slate-500 mr-1">Presets:</span>
              {presetAmounts.map((amt) => (
                <button
                  key={amt}
                  type="button"
                  onClick={() => {
                    setAmountUsd(amt);
                    setFormError(null);
                  }}
                  className={`px-2.5 py-1 rounded-lg text-xs font-mono font-semibold border transition-all ${
                    amountUsd === amt
                      ? 'bg-indigo-600/30 border-indigo-500 text-indigo-300'
                      : 'bg-slate-950/80 border-slate-800 text-slate-400 hover:text-white hover:border-slate-700'
                  }`}
                >
                  ${amt}
                </button>
              ))}
            </div>

            {/* Invariant Explanation Banner */}
            <div className="p-3 bg-slate-950/70 border border-slate-800/80 rounded-xl text-[11px] text-slate-400 space-y-1">
              <div className="font-semibold text-slate-300 flex items-center gap-1.5">
                <ShieldCheck className="w-3.5 h-3.5 text-indigo-400" />
                <span>Authoritative Currency Conversion</span>
              </div>
              <p className="leading-relaxed">
                TradePoint does not display a fabricated exchange rate. Your wallet balance is maintained in INR; the final credited INR amount is verified from PayPal's authoritative settlement breakdown upon capture.
              </p>
            </div>
          </form>
        )}
      </div>

      {/* Unified Wallet Activity History */}
      <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-6 shadow-xl backdrop-blur-md space-y-4">
        <div className="flex items-center justify-between border-b border-slate-800/80 pb-3">
          <div>
            <h2 className="text-base font-bold text-white flex items-center gap-2">
              <Clock className="w-4 h-4 text-indigo-400" />
              <span>Unified Cash Movement History</span>
            </h2>
            <p className="text-xs text-slate-400 mt-0.5">
              Audited transaction activity from the TradePoint cash ledger (Deposits, Purchases, Sales).
            </p>
          </div>
          <span className="text-[11px] font-mono text-slate-500">
            {history?.items?.length || 0} entries
          </span>
        </div>

        {loadingHistory && !history && (
          <div className="py-8 text-center text-xs text-slate-500 flex items-center justify-center gap-2">
            <RefreshCw className="w-4 h-4 animate-spin text-indigo-400" />
            <span>Loading wallet activity...</span>
          </div>
        )}

        {history && history.items.length === 0 && (
          <div className="py-8 text-center text-xs text-slate-500">
            No wallet movements recorded yet.
          </div>
        )}

        {history && history.items.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-800 text-[11px] font-bold text-slate-500 uppercase tracking-wider">
                  <th className="pb-2.5">Type</th>
                  <th className="pb-2.5">Description</th>
                  <th className="pb-2.5">Original Payment</th>
                  <th className="pb-2.5">Exchange Rate</th>
                  <th className="pb-2.5 text-right">Net Cash Impact</th>
                  <th className="pb-2.5 text-right">Date & Time</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 font-mono-nums">
                {history.items.map((item: WalletHistoryItem) => {
                  const isCredit = item.amount.startsWith('+');
                  const isDeposit = item.category === 'DEPOSIT';
                  const isTrade = item.category === 'STOCK_BUY' || item.category === 'STOCK_SELL';

                  let badgeColor = 'bg-slate-800 text-slate-300';
                  if (isDeposit) badgeColor = 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20';
                  else if (item.category === 'STOCK_BUY') badgeColor = 'bg-blue-500/10 text-blue-400 border border-blue-500/20';
                  else if (item.category === 'STOCK_SELL') badgeColor = 'bg-purple-500/10 text-purple-400 border border-purple-500/20';

                  return (
                    <tr key={item.entry_id} className="hover:bg-slate-800/40 transition-colors">
                      <td className="py-3 pr-3">
                        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-lg text-[10px] font-bold ${badgeColor}`}>
                          {isDeposit && <ArrowDownRight className="w-3 h-3 text-emerald-400" />}
                          {item.category === 'STOCK_BUY' && <ArrowUpRight className="w-3 h-3 text-blue-400" />}
                          {item.category === 'STOCK_SELL' && <ArrowDownRight className="w-3 h-3 text-purple-400" />}
                          <span>{item.category.replace('_', ' ')}</span>
                        </span>
                      </td>

                      <td className="py-3 font-sans text-slate-200">
                        <div className="font-medium text-xs">{item.description}</div>
                        {item.reference_id && (
                          <div className="text-[10px] text-slate-500 font-mono mt-0.5">
                            Ref: {item.reference_id}
                          </div>
                        )}
                      </td>

                      <td className="py-3 text-slate-300">
                        {item.payment_amount && item.payment_currency ? (
                          <span className="font-bold text-white">
                            ${item.payment_amount} {item.payment_currency}
                          </span>
                        ) : (
                          <span className="text-slate-600">—</span>
                        )}
                      </td>

                      <td className="py-3 text-slate-400">
                        {item.exchange_rate ? (
                          <span className="text-indigo-300">{item.exchange_rate}</span>
                        ) : (
                          <span className="text-slate-600">—</span>
                        )}
                      </td>

                      <td className={`py-3 text-right font-bold text-sm ${isCredit ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {isCredit ? `+${formatINR(item.amount.replace('+', ''))}` : `-${formatINR(item.amount.replace('-', ''))}`}
                      </td>

                      <td className="py-3 text-right text-slate-500 text-[11px]">
                        {formatDateTime(item.created_at)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};
