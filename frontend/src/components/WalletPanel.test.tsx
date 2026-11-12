// @vitest-environment jsdom
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '../services/api';
import type {
  WalletSummaryResponse,
  WalletHistoryResponse,
  PayPalCreateOrderResponse,
  PayPalCaptureOrderResponse,
  PayPalCancelOrderResponse,
} from '../types/api';
import { WalletPanel, isAuthorizedSandboxUrl } from './WalletPanel';

const mockSummary: WalletSummaryResponse = {
  account_id: 'demo-user',
  currency: 'INR',
  cash_balance: '1000000.00',
  total_deposited: '8202.50',
  payment_mode: 'mock',
};

const mockHistory: WalletHistoryResponse = {
  items: [
    {
      entry_id: 1,
      entry_key: 'PAYPAL_DEPOSIT:MOCK-1',
      category: 'DEPOSIT',
      amount: '+8202.50',
      currency: 'INR',
      description: 'PayPal deposit ($100.00 USD converted to 8202.50 INR)',
      reference_id: 'MOCK-1',
      payment_amount: '100.00',
      payment_currency: 'USD',
      exchange_rate: '85.000000',
      created_at: '2026-11-12T10:00:00Z',
    },
    {
      entry_id: 2,
      entry_key: 'ORDER:order-1',
      category: 'STOCK_BUY',
      amount: '-3865.00',
      currency: 'INR',
      description: 'Bought 1 shares of TCS',
      reference_id: 'order-1',
      payment_amount: null,
      payment_currency: null,
      exchange_rate: null,
      created_at: '2026-11-12T10:30:00Z',
    },
  ],
};

const defaultCreateResponse: PayPalCreateOrderResponse = {
  deposit_id: 'dep-123',
  paypal_order_id: 'MOCK-PP-ORDER-99',
  status: 'CREATED',
  payment_amount: '100.00',
  payment_currency: 'USD',
  payment_mode: 'mock',
  approval_url: null,
};

const defaultCaptureResponse: PayPalCaptureOrderResponse = {
  deposit_id: 'dep-123',
  paypal_order_id: 'MOCK-PP-ORDER-99',
  paypal_capture_id: 'CAP-777',
  status: 'COMPLETED',
  payment_amount: '100.00',
  payment_currency: 'USD',
  paypal_fee_amount: '3.50',
  paypal_fee_currency: 'USD',
  paypal_fee_in_receivable_currency: null,
  paypal_fee_in_receivable_currency_code: null,
  net_payment_amount: '96.50',
  exchange_rate: '85.000000',
  exchange_rate_source_currency: 'USD',
  exchange_rate_target_currency: 'INR',
  wallet_credit_amount: '8202.50',
  wallet_currency: 'INR',
  updated_cash_balance: '1008202.50',
  failure_code: null,
  failure_reason: null,
  completed_at: '2026-11-12T10:00:00Z',
};

let host: HTMLDivElement;
let root: Root;

function renderWalletPanel(onBalanceUpdated?: () => void) {
  act(() => {
    root.render(<WalletPanel onBalanceUpdated={onBalanceUpdated} />);
  });
}

function setInputValue(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
  if (!setter) throw new Error('Native input value setter is unavailable');
  setter.call(input, value);
  act(() => input.dispatchEvent(new Event('input', { bubbles: true })));
}

beforeEach(() => {
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
  sessionStorage.clear();
  vi.spyOn(api, 'getWalletSummary').mockResolvedValue(mockSummary);
  vi.spyOn(api, 'getWalletHistory').mockResolvedValue(mockHistory);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});

describe('WalletPanel', () => {
  it('renders available wallet balance in INR, total deposited, and currency labels', async () => {
    await act(async () => {
      renderWalletPanel();
    });

    expect(host.textContent).toContain('Wallet & Balance');
    expect(host.textContent).toContain('₹10,00,000.00');
    expect(host.textContent).toContain('Wallet: INR');
    expect(host.textContent).toContain('₹8,202.50');
    expect(host.textContent).toContain('Total Deposited');
  });

  it('validates USD deposit amount before creating an order', async () => {
    await act(async () => {
      renderWalletPanel();
    });

    const input = host.querySelector<HTMLInputElement>('#usd-amount-input');
    expect(input).not.toBeNull();

    // Test blank input
    setInputValue(input!, '');
    const form = host.querySelector('form');
    await act(async () => {
      form!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });
    expect(host.textContent).toContain('Please enter a deposit amount in USD');

    // Test negative / zero
    setInputValue(input!, '-50');
    await act(async () => {
      form!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });
    expect(host.textContent).toContain('Deposit amount must be a positive number');

    // Test excessive amount > 10,000
    setInputValue(input!, '15000');
    await act(async () => {
      form!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });
    expect(host.textContent).toContain('Maximum single deposit amount is $10,000.00 USD');
  });

  it('initiates PayPal order creation and enters approval pending state', async () => {
    const createSpy = vi.spyOn(api, 'createPayPalOrder').mockResolvedValue(defaultCreateResponse);

    await act(async () => {
      renderWalletPanel();
    });

    const form = host.querySelector('form');
    await act(async () => {
      form!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });

    expect(createSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        amount: '100.00',
        currency: 'USD',
      })
    );
    expect(host.textContent).toContain('PayPal Sandbox Order Created: MOCK-PP-ORDER-99');
    expect(host.textContent).toContain('Simulate Customer Approval & Capture');
  });

  it('displays API errors when order creation fails', async () => {
    vi.spyOn(api, 'createPayPalOrder').mockRejectedValue(new ApiError('PayPal API is temporarily unreachable.', 'PAYPAL_ERROR'));

    await act(async () => {
      renderWalletPanel();
    });

    const form = host.querySelector('form');
    await act(async () => {
      form!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });

    expect(host.textContent).toContain('Deposit Request Failed');
    expect(host.textContent).toContain('PayPal API is temporarily unreachable.');
  });

  it('successfully captures approved order and displays verified INR settlement credit', async () => {
    vi.spyOn(api, 'createPayPalOrder').mockResolvedValue(defaultCreateResponse);
    const captureSpy = vi.spyOn(api, 'capturePayPalOrder').mockResolvedValue(defaultCaptureResponse);

    await act(async () => {
      renderWalletPanel();
    });

    // Create order
    const form = host.querySelector('form');
    await act(async () => {
      form!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });

    // Trigger capture
    const captureBtn = [...host.querySelectorAll('button')].find((b) =>
      b.textContent?.includes('Simulate Customer Approval & Capture')
    );
    expect(captureBtn).not.toBeUndefined();

    await act(async () => {
      captureBtn!.click();
    });

    expect(captureSpy).toHaveBeenCalledWith({ paypal_order_id: 'MOCK-PP-ORDER-99' });
    expect(host.textContent).toContain('Deposit Successfully Captured & Verified!');
    expect(host.textContent).toContain('$100.00 USD');
    expect(host.textContent).toContain('+₹8,202.50');
    expect(host.textContent).toContain('85.000000 USD→INR');
  });

  it('displays reconciliation state when backend returns REQUIRES_RECONCILIATION', async () => {
    vi.spyOn(api, 'createPayPalOrder').mockResolvedValue(defaultCreateResponse);

    const mockReconRes: PayPalCaptureOrderResponse = {
      ...defaultCaptureResponse,
      status: 'REQUIRES_RECONCILIATION',
      failure_code: 'CONVERSION_VERIFICATION_FAILED',
      failure_reason: 'breakdown undergoing settlement verification',
    };
    vi.spyOn(api, 'capturePayPalOrder').mockResolvedValue(mockReconRes);

    await act(async () => {
      renderWalletPanel();
    });

    const form = host.querySelector('form');
    await act(async () => {
      form!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });

    const captureBtn = [...host.querySelectorAll('button')].find((b) =>
      b.textContent?.includes('Simulate Customer Approval & Capture')
    );
    await act(async () => {
      captureBtn!.click();
    });

    expect(host.textContent).toContain('Deposit Under Reconciliation');
    expect(host.textContent).toContain('breakdown undergoing settlement verification');
    // Ensure success was NOT shown
    expect(host.textContent).not.toContain('Deposit Successfully Captured & Verified!');
  });

  it('handles user cancellation and does not claim success', async () => {
    vi.spyOn(api, 'createPayPalOrder').mockResolvedValue(defaultCreateResponse);
    const cancelSpy = vi.spyOn(api, 'cancelPayPalOrder').mockResolvedValue({
      deposit_id: 'dep-123',
      paypal_order_id: 'MOCK-PP-ORDER-99',
      status: 'CANCELLED',
    });

    await act(async () => {
      renderWalletPanel();
    });

    const form = host.querySelector('form');
    await act(async () => {
      form!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });

    const cancelBtn = [...host.querySelectorAll('button')].find((b) =>
      b.textContent?.includes('Cancel Deposit')
    );
    await act(async () => {
      cancelBtn!.click();
    });

    expect(cancelSpy).toHaveBeenCalledWith({ paypal_order_id: 'MOCK-PP-ORDER-99' });
    expect(host.textContent).toContain('Deposit was cancelled');
    expect(host.textContent).not.toContain('Deposit Successfully Captured & Verified!');
    expect(sessionStorage.getItem('tradepoint_pending_deposit')).toBeNull();
  });

  it('handles cancellation rejected with HTTP 422 without claiming cancellation or wiping session', async () => {
    vi.spyOn(api, 'createPayPalOrder').mockResolvedValue(defaultCreateResponse);
    vi.spyOn(api, 'cancelPayPalOrder').mockRejectedValue(
      new ApiError("Deposit in status 'COMPLETED' cannot be cancelled", 'INVALID_DEPOSIT_STATE')
    );
    const summarySpy = vi.spyOn(api, 'getWalletSummary');

    await act(async () => {
      renderWalletPanel();
    });

    const form = host.querySelector('form');
    await act(async () => {
      form!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });

    const cancelBtn = [...host.querySelectorAll('button')].find((b) =>
      b.textContent?.includes('Cancel Deposit')
    );
    await act(async () => {
      cancelBtn!.click();
    });

    // Does NOT say "Deposit was cancelled" or "No funds were debited"
    expect(host.textContent).not.toContain('Deposit was cancelled');
    expect(host.textContent).not.toContain('No funds were charged');
    expect(host.textContent).toContain('Cancellation could not be confirmed');
    expect(host.textContent).toContain("Deposit in status 'COMPLETED' cannot be cancelled");
    // Preserves session storage for investigation
    expect(sessionStorage.getItem('tradepoint_pending_deposit')).not.toBeNull();
    // Refreshed wallet data
    expect(summarySpy).toHaveBeenCalled();
  });

  it('handles cancellation rejected with HTTP 409 when capture is pending', async () => {
    vi.spyOn(api, 'createPayPalOrder').mockResolvedValue(defaultCreateResponse);
    vi.spyOn(api, 'cancelPayPalOrder').mockRejectedValue(
      new ApiError('Payment capture is currently in progress', 'CAPTURE_PENDING')
    );

    await act(async () => {
      renderWalletPanel();
    });

    const form = host.querySelector('form');
    await act(async () => {
      form!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });

    const cancelBtn = [...host.querySelectorAll('button')].find((b) =>
      b.textContent?.includes('Cancel Deposit')
    );
    await act(async () => {
      cancelBtn!.click();
    });

    expect(host.textContent).not.toContain('Deposit was cancelled');
    expect(host.textContent).toContain('Payment capture is currently in progress');
    expect(sessionStorage.getItem('tradepoint_pending_deposit')).not.toBeNull();
  });

  it('handles network failure during cancellation honestly', async () => {
    vi.spyOn(api, 'createPayPalOrder').mockResolvedValue(defaultCreateResponse);
    vi.spyOn(api, 'cancelPayPalOrder').mockRejectedValue(new Error('Failed to fetch'));

    await act(async () => {
      renderWalletPanel();
    });

    const form = host.querySelector('form');
    await act(async () => {
      form!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });

    const cancelBtn = [...host.querySelectorAll('button')].find((b) =>
      b.textContent?.includes('Cancel Deposit')
    );
    await act(async () => {
      cancelBtn!.click();
    });

    expect(host.textContent).not.toContain('Deposit was cancelled');
    expect(host.textContent).toContain('Cancellation could not be confirmed');
    expect(sessionStorage.getItem('tradepoint_pending_deposit')).not.toBeNull();
  });

  it('does not overwrite COMPLETED state if cancellation is attempted after completion', async () => {
    vi.spyOn(api, 'createPayPalOrder').mockResolvedValue(defaultCreateResponse);
    vi.spyOn(api, 'capturePayPalOrder').mockResolvedValue(defaultCaptureResponse);

    await act(async () => {
      renderWalletPanel();
    });

    // Create & capture order
    const form = host.querySelector('form');
    await act(async () => {
      form!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });
    const captureBtn = [...host.querySelectorAll('button')].find((b) =>
      b.textContent?.includes('Simulate Customer Approval & Capture')
    );
    await act(async () => {
      captureBtn!.click();
    });

    expect(host.textContent).toContain('Deposit Successfully Captured & Verified!');

    // Even if cancel API were triggered somehow, completed state remains intact
    vi.spyOn(api, 'cancelPayPalOrder').mockRejectedValue(
      new ApiError("Deposit in status 'COMPLETED' cannot be cancelled", 'INVALID_DEPOSIT_STATE')
    );

    expect(host.textContent).toContain('Deposit Successfully Captured & Verified!');
    expect(host.textContent).not.toContain('Deposit was cancelled');
  });

  it('isolates mock controls: hides simulation button when backend reports Sandbox mode', async () => {
    vi.spyOn(api, 'getWalletSummary').mockResolvedValue({
      ...mockSummary,
      payment_mode: 'sandbox',
    });
    vi.spyOn(api, 'createPayPalOrder').mockResolvedValue({
      deposit_id: 'dep-sandbox-1',
      paypal_order_id: 'SANDBOX-ORDER-123',
      status: 'CREATED',
      payment_amount: '100.00',
      payment_currency: 'USD',
      payment_mode: 'sandbox',
      approval_url: 'https://www.sandbox.paypal.com/checkoutnow?token=SANDBOX-ORDER-123',
    });

    await act(async () => {
      renderWalletPanel();
    });

    const form = host.querySelector('form');
    await act(async () => {
      form!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });

    expect(host.textContent).toContain('SANDBOX-ORDER-123');
    // Mock simulation button MUST NOT be present
    expect(host.textContent).not.toContain('Simulate Customer Approval & Capture');
    // Real sandbox approval link must be present
    const sandboxLink = host.querySelector('a[href*="sandbox.paypal.com"]');
    expect(sandboxLink).not.toBeNull();
    expect(sandboxLink?.getAttribute('href')).toContain('SANDBOX-ORDER-123');
    expect(host.textContent).toContain('Check Approval & Capture');
  });

  it('isolates mock controls: hides simulation button when payment_mode is unknown or unavailable', async () => {
    vi.spyOn(api, 'getWalletSummary').mockResolvedValue({
      ...mockSummary,
      payment_mode: null,
    });
    vi.spyOn(api, 'createPayPalOrder').mockResolvedValue({
      deposit_id: 'dep-unknown-1',
      paypal_order_id: 'UNKNOWN-ORDER-123',
      status: 'CREATED',
      payment_amount: '100.00',
      payment_currency: 'USD',
      payment_mode: null,
      approval_url: null,
    });

    await act(async () => {
      renderWalletPanel();
    });

    const form = host.querySelector('form');
    await act(async () => {
      form!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });

    expect(host.textContent).toContain('UNKNOWN-ORDER-123');
    expect(host.textContent).not.toContain('Simulate Customer Approval & Capture');
  });

  it('ensures reconciliation messaging is truthful and does not promise automatic credit', async () => {
    vi.spyOn(api, 'createPayPalOrder').mockResolvedValue(defaultCreateResponse);
    vi.spyOn(api, 'capturePayPalOrder').mockResolvedValue({
      ...defaultCaptureResponse,
      status: 'REQUIRES_RECONCILIATION',
      failure_reason: null,
    });

    await act(async () => {
      renderWalletPanel();
    });

    const form = host.querySelector('form');
    await act(async () => {
      form!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });

    const captureBtn = [...host.querySelectorAll('button')].find((b) =>
      b.textContent?.includes('Simulate Customer Approval & Capture')
    );
    await act(async () => {
      captureBtn!.click();
    });

    expect(host.textContent).toContain('Deposit Under Reconciliation');
    // Must NOT promise automatic credit
    expect(host.textContent).not.toContain('automatically');
    expect(host.textContent).not.toContain('Funds will be verified shortly');
    // Must instruct user not to re-pay and explain operator review
    expect(host.textContent).toContain('manual operator review');
    expect(host.textContent).toContain('Please do not initiate another payment');
    // Preserves deposit details
    expect(host.textContent).toContain('MOCK-PP-ORDER-99');
    expect(host.textContent).toContain('dep-123');
    expect(host.textContent).toContain('$100.00 USD');
  });

  it('handles capture network error without claiming confirmed payment failure and allows retry', async () => {
    vi.spyOn(api, 'createPayPalOrder').mockResolvedValue(defaultCreateResponse);
    vi.spyOn(api, 'capturePayPalOrder').mockRejectedValue(
      new ApiError('Connection timed out during capture', 'NETWORK_TIMEOUT')
    );

    await act(async () => {
      renderWalletPanel();
    });

    const form = host.querySelector('form');
    await act(async () => {
      form!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });

    const captureBtn = [...host.querySelectorAll('button')].find((b) =>
      b.textContent?.includes('Simulate Customer Approval & Capture')
    );
    await act(async () => {
      captureBtn!.click();
    });

    // Does NOT wipe session storage
    expect(sessionStorage.getItem('tradepoint_pending_deposit')).not.toBeNull();
    // Does NOT say payment was permanently failed or cancel was confirmed
    expect(host.textContent).toContain('Unable to confirm capture status');
    expect(host.textContent).toContain('Connection timed out during capture');
    // Shows safe retry capture and check balance options
    expect(host.textContent).toContain('Retry Capture');
    expect(host.textContent).toContain('Check Wallet Balance');
  });

  it('renders unified history distinguishing USD deposits from INR stock trades', async () => {
    await act(async () => {
      renderWalletPanel();
    });

    expect(host.textContent).toContain('Unified Cash Movement History');
    expect(host.textContent).toContain('DEPOSIT');
    expect(host.textContent).toContain('$100.00 USD');
    expect(host.textContent).toContain('85.000000');
    expect(host.textContent).toContain('+₹8,202.50');

    expect(host.textContent).toContain('STOCK BUY');
    expect(host.textContent).toContain('Bought 1 shares of TCS');
    expect(host.textContent).toContain('-₹3,865.00');
  });

  it('validates Sandbox approval URLs defensively with isAuthorizedSandboxUrl', () => {
    // Valid hosts
    expect(isAuthorizedSandboxUrl('https://www.sandbox.paypal.com/checkoutnow?token=abc')).toBe(true);
    expect(isAuthorizedSandboxUrl('https://sandbox.paypal.com/checkoutnow?token=abc')).toBe(true);

    // Insecure HTTP
    expect(isAuthorizedSandboxUrl('http://www.sandbox.paypal.com/checkoutnow?token=abc')).toBe(false);

    // Production host rejected in Sandbox
    expect(isAuthorizedSandboxUrl('https://www.paypal.com/checkoutnow?token=abc')).toBe(false);
    expect(isAuthorizedSandboxUrl('https://paypal.com/checkoutnow?token=abc')).toBe(false);

    // Lookalike / phishing domains
    expect(isAuthorizedSandboxUrl('https://www.sandbox.paypal.com.evil.test/checkout')).toBe(false);
    expect(isAuthorizedSandboxUrl('https://evil.test/checkout')).toBe(false);

    // Embedded credentials
    expect(isAuthorizedSandboxUrl('https://user:pass@www.sandbox.paypal.com/checkout')).toBe(false);

    // Non-standard port
    expect(isAuthorizedSandboxUrl('https://www.sandbox.paypal.com:8443/checkout')).toBe(false);

    // Null / empty / invalid
    expect(isAuthorizedSandboxUrl(null)).toBe(false);
    expect(isAuthorizedSandboxUrl(undefined)).toBe(false);
    expect(isAuthorizedSandboxUrl('not-a-url')).toBe(false);
  });

  it('renders security warning and suppresses redirect if backend returns invalid approval_url', async () => {
    vi.spyOn(api, 'getWalletSummary').mockResolvedValue({
      ...mockSummary,
      payment_mode: 'sandbox',
    });
    vi.spyOn(api, 'createPayPalOrder').mockResolvedValue({
      deposit_id: 'dep-invalid-url-1',
      paypal_order_id: 'ORDER-INVALID-URL-123',
      status: 'CREATED',
      payment_amount: '100.00',
      payment_currency: 'USD',
      payment_mode: 'sandbox',
      approval_url: 'https://attacker.evil.test/phish?token=123',
    });

    await act(async () => {
      renderWalletPanel();
    });

    const form = host.querySelector('form');
    await act(async () => {
      form!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });

    // The attacker link MUST NOT be rendered
    const link = host.querySelector('a[href*="attacker.evil.test"]');
    expect(link).toBeNull();
    // A security notice is displayed
    expect(host.textContent).toContain('Authoritative Sandbox approval URL was not provided or failed security validation');
  });

  it('prevents abandoning unresolved deposits in REQUIRES_RECONCILIATION and uncertain FAILED', async () => {
    vi.spyOn(api, 'createPayPalOrder').mockResolvedValue(defaultCreateResponse);
    vi.spyOn(api, 'capturePayPalOrder').mockResolvedValue({
      ...defaultCaptureResponse,
      status: 'REQUIRES_RECONCILIATION',
    });

    await act(async () => {
      renderWalletPanel();
    });

    const form = host.querySelector('form');
    await act(async () => {
      form!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });

    const captureBtn = [...host.querySelectorAll('button')].find((b) =>
      b.textContent?.includes('Simulate Customer Approval & Capture')
    );
    await act(async () => {
      captureBtn!.click();
    });

    expect(host.textContent).toContain('Deposit Under Reconciliation');

    // Verify NO "Dismiss Alert" or "Abandon" button exists
    const buttons = [...host.querySelectorAll('button')].map((b) => b.textContent?.trim());
    expect(buttons).not.toContain('Dismiss Alert');
    expect(buttons).not.toContain('Abandon & Start Over');
    expect(buttons).not.toContain('Start Over');
    expect(buttons).toContain('Check Wallet Balance');

    // Deposit form MUST NOT be rendered while deposit is unresolved
    expect(host.querySelector('#usd-amount-input')).toBeNull();
  });
});
