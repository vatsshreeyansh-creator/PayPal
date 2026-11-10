// @vitest-environment jsdom
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../services/api';
import type { Quote, StockSummary, WatchlistItem } from '../types/api';
import { MarketsPanel } from './MarketsPanel';

const stock: StockSummary = {
  symbol: 'TCS', name: 'Tata Consultancy Services', exchange: 'NSE', instrument_token: 123,
};
const quote: Quote = {
  price: '3865.25', currency: 'INR', as_of: '2026-11-10T10:00:00Z', simulated: true,
};
const watched: WatchlistItem = { stock, quote };

let host: HTMLDivElement;
let root: Root;
let currentWatchlist: WatchlistItem[] = [];
let currentWatchlistError: string | null = null;

function renderPanel() {
  act(() => {
    root.render(<MarketsPanel
      watchlist={currentWatchlist}
      watchlistError={currentWatchlistError}
      onWatchlistChange={async () => undefined}
    />);
  });
}

function setup() {
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
  currentWatchlist = [];
  currentWatchlistError = null;
  renderPanel();
}

function enterQuery(value: string) {
  const input = host.querySelector<HTMLInputElement>('#markets-query');
  if (!input) throw new Error('Markets search input was not rendered');
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
  if (!setter) throw new Error('Native input value setter is unavailable');
  setter.call(input, value);
  act(() => input.dispatchEvent(new Event('input', { bubbles: true })));
}

async function submitSearch() {
  const form = host.querySelector<HTMLFormElement>('form');
  if (!form) throw new Error('Markets search form was not rendered');
  await act(async () => {
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await Promise.resolve();
  });
}

function buttonWithText(text: string): HTMLButtonElement {
  const button = [...host.querySelectorAll('button')].find((item) => item.textContent?.includes(text));
  if (!button) throw new Error(`Button containing “${text}” was not rendered`);
  return button;
}

afterEach(() => {
  if (root) act(() => root.unmount());
  host?.remove();
  vi.restoreAllMocks();
});

describe('MarketsPanel', () => {
  it('searches through the API client and displays the returned NSE stock', async () => {
    const search = vi.spyOn(api, 'searchStocks').mockResolvedValue([stock]);
    setup();
    enterQuery('Tata');
    await submitSearch();

    expect(search).toHaveBeenCalledWith('Tata', 20);
    expect(host.textContent).toContain('Tata Consultancy Services');
    expect(host.textContent).toContain('TCS');
    expect(host.textContent).toContain('NSE equity');
  });

  it('shows an honest empty-result state and does not search blank input', async () => {
    const search = vi.spyOn(api, 'searchStocks').mockResolvedValue([]);
    setup();
    await submitSearch();
    expect(search).not.toHaveBeenCalled();

    enterQuery('No such share');
    await submitSearch();
    expect(search).toHaveBeenCalledWith('No such share', 20);
    expect(host.textContent).toContain('No matching NSE equities were found.');
    expect(host.textContent).not.toContain('₹');
  });

  it('shows loading while a search is pending and renders search failures', async () => {
    let rejectSearch!: (error: Error) => void;
    vi.spyOn(api, 'searchStocks').mockReturnValue(new Promise((_, reject) => { rejectSearch = reject; }));
    setup();
    enterQuery('TCS');
    const form = host.querySelector('form');
    if (!form) throw new Error('Markets search form was not rendered');
    act(() => form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
    expect(host.textContent).toContain('Searching NSE equities…');

    await act(async () => {
      rejectSearch(new Error('Market search unavailable.'));
      await Promise.resolve();
    });
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('Market search unavailable.');
    expect(host.textContent).not.toContain('3865.25');
  });

  it('adds a result through the watchlist API and reflects refreshed membership', async () => {
    const add = vi.spyOn(api, 'addToWatchlist').mockResolvedValue({ item: watched, created: true });
    vi.spyOn(api, 'searchStocks').mockResolvedValue([stock]);
    setup();
    enterQuery('TCS');
    await submitSearch();

    let finishRefresh!: () => void;
    const refresh = vi.fn(() => new Promise<void>((resolve) => { finishRefresh = resolve; }));
    // Replace the callback with a controlled parent refresh to observe the in-flight state.
    act(() => root.render(<MarketsPanel watchlist={currentWatchlist} watchlistError={null} onWatchlistChange={refresh} />));
    await act(async () => {
      buttonWithText('Add to watchlist').click();
      await Promise.resolve();
    });
    expect(add).toHaveBeenCalledWith('TCS');
    expect(buttonWithText('Add to watchlist').disabled).toBe(true);

    currentWatchlist = [watched];
    await act(async () => {
      finishRefresh();
      await Promise.resolve();
    });
    // The parent owns list state; render its refreshed response as App does.
    renderPanel();
    expect(refresh).toHaveBeenCalledOnce();
    expect(buttonWithText('In watchlist').disabled).toBe(true);
    expect(host.textContent).toContain('₹3,865.25');
  });

  it('shows watchlist-add failures clearly', async () => {
    vi.spyOn(api, 'searchStocks').mockResolvedValue([stock]);
    vi.spyOn(api, 'addToWatchlist').mockRejectedValue(new Error('Watchlist unavailable.'));
    setup();
    enterQuery('TCS');
    await submitSearch();
    await act(async () => {
      buttonWithText('Add to watchlist').click();
      await Promise.resolve();
    });
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('Watchlist unavailable.');
  });

  it('shows available quotes only from watchlist data and handles nullable quotes', async () => {
    vi.spyOn(api, 'searchStocks').mockResolvedValue([stock]);
    setup();
    enterQuery('TCS');
    await submitSearch();
    expect(host.textContent).toContain('Unavailable');
    expect(host.textContent).not.toContain('3865.25');

    currentWatchlist = [{ stock, quote }];
    renderPanel();
    expect(host.textContent).toContain('₹3,865.25');
    expect(host.textContent).toContain('Simulated');

    currentWatchlist = [{ stock, quote: null }];
    renderPanel();
    expect(host.textContent).toContain('Unavailable');
    expect(host.textContent).not.toContain('₹3,865.25');
  });

  it('reports a watchlist loading failure and keeps quote data unavailable', async () => {
    vi.spyOn(api, 'searchStocks').mockResolvedValue([stock]);
    setup();
    enterQuery('TCS');
    await submitSearch();
    currentWatchlist = [];
    currentWatchlistError = 'Watchlist could not be loaded.';
    renderPanel();

    expect(host.querySelector('[role="alert"]')?.textContent).toContain('Quotes may be unavailable');
    expect(host.textContent).toContain('Unavailable');
    expect(host.textContent).not.toContain('₹3,865.25');
  });
});
