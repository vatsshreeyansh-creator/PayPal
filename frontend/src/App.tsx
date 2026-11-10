import React, { useState, useEffect } from 'react';
import { api } from './services/api';
import {
  AccountSummary,
  PortfolioSummary,
  WatchlistItem,
  Order,
  Transaction,
} from './types/api';
import type { NewsSearchResponse } from './types/api';
import { TopBar } from './components/TopBar';
import { SidebarNav } from './components/SidebarNav';
import { MarketChart } from './components/MarketChart';
import { OrderTicket } from './components/OrderTicket';
import { WatchlistPanel } from './components/WatchlistPanel';
import { PortfolioPanel } from './components/PortfolioPanel';
import { OrdersPanel } from './components/OrdersPanel';
import { NewsPanel } from './components/NewsPanel';
import { AiResearchHub } from './components/AiResearchHub';
import { CommandPalette } from './components/CommandPalette';
import { MarketsPanel } from './components/MarketsPanel';
import { formatINR } from './utils/format';
import {
  Briefcase,
  Star,
  Activity,
  Layers,
} from 'lucide-react';

export function App() {
  const [currentView, setCurrentView] = useState<
    'dashboard' | 'markets' | 'watchlist' | 'portfolio' | 'orders' | 'news' | 'research'
  >('dashboard');

  // Core Data
  const [account, setAccount] = useState<AccountSummary | null>(null);
  const [portfolio, setPortfolio] = useState<PortfolioSummary | null>(null);
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [newsFeed, setNewsFeed] = useState<NewsSearchResponse | null>(null);
  const [dashboardError, setDashboardError] = useState<string | null>(null);
  const [portfolioError, setPortfolioError] = useState<string | null>(null);
  const [watchlistError, setWatchlistError] = useState<string | null>(null);
  const [ordersError, setOrdersError] = useState<string | null>(null);
  const [newsError, setNewsError] = useState<string | null>(null);
  const [loadingDashboard, setLoadingDashboard] = useState(false);
  const [currentNewsQuery, setCurrentNewsQuery] = useState('');

  // Chart & Trading Focus
  const [selectedStock, setSelectedStock] = useState<{
    symbol: string;
    name: string;
    price: string | null;
    simulated: boolean | null;
  }>({
    symbol: '',
    name: '',
    price: null,
    simulated: null,
  });

  // UI state
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const [isOrderModalOpen, setIsOrderModalOpen] = useState(false);
  const [newsScope, setNewsScope] = useState<'personal' | 'market'>('personal');
  const [loadingPortfolio, setLoadingPortfolio] = useState(false);
  const [loadingWatchlist, setLoadingWatchlist] = useState(false);
  const [loadingOrders, setLoadingOrders] = useState(false);
  const [loadingNews, setLoadingNews] = useState(false);

  // Initial Data Load
  const refreshAll = async () => {
    setLoadingDashboard(true);
    setLoadingPortfolio(true);
    setLoadingWatchlist(true);
    setLoadingOrders(true);
    try {
      const [acc, port, wl, ords, txs] = await Promise.allSettled([
        api.getAccount(),
        api.getPortfolio(),
        api.getWatchlist(),
        api.getOrders(),
        api.getTransactions(),
      ]);

      const errors: string[] = [];
      if (acc.status === 'fulfilled') setAccount(acc.value);
      else { setAccount(null); errors.push('Account could not be loaded.'); }
      if (port.status === 'fulfilled') { setPortfolio(port.value); setPortfolioError(null); }
      else { setPortfolio(null); setPortfolioError('Portfolio could not be loaded.'); errors.push('Portfolio could not be loaded.'); }
      if (wl.status === 'fulfilled') {
        setWatchlist(wl.value);
        setWatchlistError(null);
      } else { setWatchlist([]); setWatchlistError('Watchlist could not be loaded.'); errors.push('Watchlist could not be loaded.'); }
      if (ords.status === 'fulfilled' && txs.status === 'fulfilled') {
        setOrders(ords.value); setTransactions(txs.value); setOrdersError(null);
      } else { setOrders([]); setTransactions([]); setOrdersError('Order and transaction history could not be loaded.'); errors.push('Order history could not be loaded.'); }
      setDashboardError(errors.length ? errors.join(' ') : null);
    } finally {
      setLoadingDashboard(false);
      setLoadingPortfolio(false);
      setLoadingWatchlist(false);
      setLoadingOrders(false);
    }
  };

  const loadNews = async (scope: 'personal' | 'market' = newsScope, query = currentNewsQuery, pageToken?: string) => {
    setLoadingNews(true);
    setNewsError(null);
    try {
      const response = await api.getNews(scope, query, pageToken);
      setNewsFeed((previous) => pageToken && previous
        ? { ...response, articles: [...previous.articles, ...response.articles] }
        : response);
      setNewsScope(response.scope);
      setCurrentNewsQuery(query);
    } catch (requestError: unknown) {
      setNewsError(requestError instanceof Error ? requestError.message : 'News could not be loaded.');
    } finally {
      setLoadingNews(false);
    }
  };

  useEffect(() => {
    refreshAll();
    loadNews();
  }, []);

  const handleOrderSuccess = (_order: Order) => {
    // Re-fetch portfolio, account, orders, transactions
    refreshAll();
  };

  const handleSelectStock = (symbol: string, name = '', price: string | null = null, simulated: boolean | null = null) => {
    setSelectedStock({
      symbol,
      name: name || symbol,
      price,
      simulated,
    });
  };

  const handleTradeStock = (symbol: string, price: string | null = null, _quantity?: string) => {
    setSelectedStock((prev) => ({
      symbol,
      name: prev.symbol === symbol ? prev.name : symbol,
      price,
      simulated: prev.symbol === symbol ? prev.simulated : null,
    }));
    setIsOrderModalOpen(true);
  };

  const handleResearchStock = (symbol: string) => {
    setSelectedStock((prev) => ({ ...prev, symbol }));
    setCurrentView('research');
  };

  const availableCash = account?.cash_balance ?? null;
  const totalValuation = portfolio?.total_portfolio_value ?? null;
  const netWorth = totalValuation;

  const currentHolding = portfolio?.holdings?.find(
    (holding) => holding.symbol === selectedStock.symbol
  );

  return (
    <div className="min-h-screen bg-[#070b14] text-slate-100 flex flex-col font-sans selection:bg-indigo-500 selection:text-white">
      {/* Top Bar */}
      <TopBar
        availableCash={availableCash}
        onOpenSearch={() => setIsSearchOpen(true)}
        onNewOrder={() => setIsOrderModalOpen(true)}
      />

      <div className="flex-1 flex overflow-hidden">
        {/* Sidebar */}
        <SidebarNav currentView={currentView} onNavigate={setCurrentView} />

        {/* Main Content Workspace */}
        <main className="flex-1 overflow-y-auto p-6 space-y-6">
          {currentView === 'dashboard' && (
            <div className="space-y-6 max-w-7xl mx-auto">
              {/* Top Metric Cards */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-4 shadow-xl backdrop-blur-md">
                  <div className="flex items-center justify-between text-slate-400 text-xs mb-1">
                    <span>Total Portfolio Value</span>
                    <Layers className="w-4 h-4 text-indigo-400" />
                  </div>
                  <div className="text-xl font-bold font-mono-nums text-white">
                    {netWorth !== null ? formatINR(netWorth) : 'Unavailable'}
                  </div>
                  <div className="text-[11px] text-slate-400 mt-1 font-semibold">
                    Portfolio value from backend
                  </div>
                </div>

                <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-4 shadow-xl backdrop-blur-md">
                  <div className="flex items-center justify-between text-slate-400 text-xs mb-1">
                    <span>Available Cash Balance</span>
                    <Briefcase className="w-4 h-4 text-emerald-400" />
                  </div>
                  <div className="text-xl font-bold font-mono-nums text-emerald-400">
                    {availableCash === null ? 'Unavailable' : formatINR(availableCash)}
                  </div>
                  <div className="text-[11px] text-slate-500 mt-1">Instant buying power</div>
                </div>

                <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-4 shadow-xl backdrop-blur-md">
                  <div className="flex items-center justify-between text-slate-400 text-xs mb-1">
                    <span>Active Stock Positions</span>
                    <Activity className="w-4 h-4 text-violet-400" />
                  </div>
                  <div className="text-xl font-bold font-mono-nums text-white">
                    {portfolio?.holdings?.length || 0}
                  </div>
                  <div className="text-[11px] text-slate-500 mt-1">Equities held in account</div>
                </div>

                <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-4 shadow-xl backdrop-blur-md">
                  <div className="flex items-center justify-between text-slate-400 text-xs mb-1">
                    <span>Watchlist Tracked</span>
                    <Star className="w-4 h-4 text-amber-400" />
                  </div>
                  <div className="text-xl font-bold font-mono-nums text-white">
                    {watchlist.length}
                  </div>
                  <div className="text-[11px] text-slate-500 mt-1">Monitored NSE assets</div>
                </div>
              </div>

              {/* Chart & Quick Trade 2-Column Grid */}
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <div className="lg:col-span-2 space-y-6">
                  <MarketChart
                    symbol={selectedStock.symbol}
                    name={selectedStock.name}
                    currentPrice={selectedStock.price}
                    simulated={selectedStock.simulated}
                  />

                  {/* Portfolio Preview */}
                  <PortfolioPanel
                    portfolio={portfolio}
                    loading={loadingPortfolio}
                    error={portfolioError}
                    onRefresh={refreshAll}
                    onTrade={handleTradeStock}
                    onResearch={handleResearchStock}
                  />
                </div>

                {/* Right Column: Order Ticket & Watchlist */}
                <div className="space-y-6">
                  <OrderTicket
                    initialSymbol={selectedStock.symbol}
                    initialPrice={selectedStock.price}
                    availableCash={availableCash}
                    currentHoldingQty={currentHolding?.quantity || '0'}
                    onOrderSuccess={handleOrderSuccess}
                  />

                  <div className="h-[440px]">
                    <WatchlistPanel
                      watchlist={watchlist}
                      loading={loadingWatchlist}
                      error={watchlistError}
                      onSelectStock={handleSelectStock}
                      onTradeStock={handleTradeStock}
                      onResearchStock={handleResearchStock}
                      onRefresh={refreshAll}
                    />
                  </div>
                </div>
              </div>
            </div>
          )}

          {currentView === 'watchlist' && (
            <div className="max-w-5xl mx-auto h-[700px]">
              <WatchlistPanel
                watchlist={watchlist}
                loading={loadingWatchlist}
                error={watchlistError}
                onSelectStock={handleSelectStock}
                onTradeStock={handleTradeStock}
                onResearchStock={handleResearchStock}
                onRefresh={refreshAll}
              />
            </div>
          )}

          {currentView === 'markets' && (
            <MarketsPanel watchlist={watchlist} watchlistError={watchlistError} onWatchlistChange={refreshAll} />
          )}

          {currentView === 'portfolio' && (
            <div className="max-w-6xl mx-auto space-y-6">
              <PortfolioPanel
                portfolio={portfolio}
                loading={loadingPortfolio}
                error={portfolioError}
                onRefresh={refreshAll}
                onTrade={handleTradeStock}
                onResearch={handleResearchStock}
              />
            </div>
          )}

          {dashboardError && <div role="alert" className="max-w-7xl mx-auto p-3 rounded-xl bg-rose-500/10 text-rose-300 text-sm">{dashboardError}</div>}
          {loadingDashboard && <div role="status" className="max-w-7xl mx-auto text-xs text-slate-400">Refreshing account data…</div>}

          {currentView === 'orders' && (
            <div className="max-w-6xl mx-auto space-y-6">
              {ordersError && <p role="alert" className="text-rose-300">{ordersError}</p>}
              <OrdersPanel
                orders={orders}
                transactions={transactions}
                loading={loadingOrders}
                onRefresh={refreshAll}
              />
            </div>
          )}

          {currentView === 'news' && (
            <div className="max-w-5xl mx-auto space-y-6">
              <NewsPanel
                news={newsFeed}
                loading={loadingNews}
                error={newsError}
                scope={newsScope}
                onScopeChange={(newScope) => {
                  setNewsScope(newScope);
                  loadNews(newScope);
                }}
                onFilterChange={(q) => loadNews(newsScope, q)}
                onLoadMore={(token) => loadNews(newsScope, currentNewsQuery, token)}
                onResearchStock={handleResearchStock}
              />
            </div>
          )}

          {currentView === 'research' && (
            <div className="max-w-5xl mx-auto space-y-6">
              <AiResearchHub
                initialSymbol={selectedStock.symbol}
                onTradeStock={handleTradeStock}
              />
            </div>
          )}
        </main>
      </div>

      {/* Floating Quick Order Modal (when triggered from TopBar or other buttons) */}
      {isOrderModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-in fade-in">
          <div className="w-full max-w-md relative">
            <button
              onClick={() => setIsOrderModalOpen(false)}
              className="absolute right-4 top-4 z-10 text-slate-400 hover:text-white p-1 rounded-lg"
            >
              ✕
            </button>
            <OrderTicket
              initialSymbol={selectedStock.symbol}
              initialPrice={selectedStock.price}
              availableCash={availableCash}
              currentHoldingQty={currentHolding?.quantity || '0'}
              onOrderSuccess={(order) => {
                handleOrderSuccess(order);
                setTimeout(() => setIsOrderModalOpen(false), 1500);
              }}
              onClose={() => setIsOrderModalOpen(false)}
            />
          </div>
        </div>
      )}

      {/* Command Palette */}
      <CommandPalette
        isOpen={isSearchOpen}
        onClose={() => setIsSearchOpen(false)}
        onNavigate={setCurrentView}
          onSelectStock={(stock) => {
          handleSelectStock(stock.symbol, stock.name, null, null);
          setCurrentView('dashboard');
        }}
      />
    </div>
  );
}

export default App;
