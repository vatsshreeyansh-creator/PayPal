import React, { useState, useEffect } from 'react';
import { api } from './services/api';
import {
  AccountSummary,
  PortfolioSummary,
  WatchlistItem,
  Order,
  Transaction,
  NewsArticle,
} from './types/api';
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
import { formatINR } from './utils/format';
import {
  TrendingUp,
  Briefcase,
  Star,
  Activity,
  Layers,
  Sparkles,
  ArrowUpRight,
  ShieldAlert,
} from 'lucide-react';

export function App() {
  const [currentView, setCurrentView] = useState<
    'dashboard' | 'watchlist' | 'portfolio' | 'orders' | 'news' | 'research'
  >('dashboard');

  // Core Data
  const [account, setAccount] = useState<AccountSummary | null>(null);
  const [portfolio, setPortfolio] = useState<PortfolioSummary | null>(null);
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [news, setNews] = useState<NewsArticle[]>([]);

  // Chart & Trading Focus
  const [selectedStock, setSelectedStock] = useState<{
    symbol: string;
    name: string;
    price: number;
    simulated: boolean;
  }>({
    symbol: 'TCS',
    name: 'Tata Consultancy Services Limited',
    price: 4120.0,
    simulated: true,
  });

  // UI state
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const [isOrderModalOpen, setIsOrderModalOpen] = useState(false);
  const [newsScope, setNewsScope] = useState<'personal' | 'market'>('personal');
  const [loadingPortfolio, setLoadingPortfolio] = useState(false);
  const [loadingOrders, setLoadingOrders] = useState(false);
  const [loadingNews, setLoadingNews] = useState(false);

  // Initial Data Load
  const refreshAll = async () => {
    try {
      const [acc, port, wl, ords, txs] = await Promise.allSettled([
        api.getAccount(),
        api.getPortfolio(),
        api.getWatchlist(),
        api.getOrders(),
        api.getTransactions(),
      ]);

      if (acc.status === 'fulfilled') setAccount(acc.value);
      if (port.status === 'fulfilled') setPortfolio(port.value);
      if (wl.status === 'fulfilled') {
        setWatchlist(wl.value);
        if (wl.value.length > 0 && selectedStock.symbol === 'TCS') {
          const first = wl.value[0];
          setSelectedStock({
            symbol: first.stock.symbol,
            name: first.stock.name,
            price: first.quote ? parseFloat(first.quote.price) : 3800,
            simulated: first.quote?.simulated ?? true,
          });
        }
      }
      if (ords.status === 'fulfilled') setOrders(ords.value);
      if (txs.status === 'fulfilled') setTransactions(txs.value);
    } catch (err) {
      console.error('Failed to load dashboard data', err);
    }
  };

  const loadNews = async (scope: 'personal' | 'market' = newsScope, query = '') => {
    setLoadingNews(true);
    try {
      const items = await api.getNews(scope, query);
      setNews(items);
    } catch (err) {
      console.error(err);
    } finally {
      setLoadingNews(false);
    }
  };

  useEffect(() => {
    refreshAll();
    loadNews();
  }, []);

  const handleOrderSuccess = (order: Order) => {
    // Re-fetch portfolio, account, orders, transactions
    refreshAll();
  };

  const handleSelectStock = (symbol: string, name = '', price = 0) => {
    setSelectedStock({
      symbol,
      name: name || symbol,
      price: price || 3500,
      simulated: true,
    });
  };

  const handleTradeStock = (symbol: string, price = 0) => {
    setSelectedStock((prev) => ({
      ...prev,
      symbol,
      price: price || prev.price,
    }));
    setIsOrderModalOpen(true);
  };

  const handleResearchStock = (symbol: string) => {
    setSelectedStock((prev) => ({ ...prev, symbol }));
    setCurrentView('research');
  };

  const availableCash = parseFloat(
    (account as any)?.cash_balance ||
      account?.cash ||
      (portfolio as any)?.account?.cash_balance ||
      portfolio?.cash ||
      '1000000'
  );
  const totalValuation = (portfolio as any)?.total_portfolio_value
    ? parseFloat((portfolio as any).total_portfolio_value)
    : portfolio?.total_valuation
    ? parseFloat(portfolio.total_valuation)
    : null;
  const netWorth = totalValuation !== null ? totalValuation : availableCash;

  const currentHolding = portfolio?.holdings?.find(
    (h: any) => (h.symbol || h.stock?.symbol) === selectedStock.symbol
  );

  return (
    <div className="min-h-screen bg-[#070b14] text-slate-100 flex flex-col font-sans selection:bg-indigo-500 selection:text-white">
      {/* Top Bar */}
      <TopBar
        availableCash={availableCash}
        totalNetWorth={netWorth}
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
                    {netWorth !== null ? formatINR(netWorth) : '—'}
                  </div>
                  <div className="text-[11px] text-emerald-400 flex items-center gap-1 mt-1 font-semibold">
                    <TrendingUp className="w-3 h-3" /> Paper trading active
                  </div>
                </div>

                <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-4 shadow-xl backdrop-blur-md">
                  <div className="flex items-center justify-between text-slate-400 text-xs mb-1">
                    <span>Available Cash Balance</span>
                    <Briefcase className="w-4 h-4 text-emerald-400" />
                  </div>
                  <div className="text-xl font-bold font-mono-nums text-emerald-400">
                    {formatINR(availableCash)}
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
                    currentHoldingQty={currentHolding?.quantity || 0}
                    onOrderSuccess={handleOrderSuccess}
                  />

                  <div className="h-[440px]">
                    <WatchlistPanel
                      watchlist={watchlist}
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
                onSelectStock={handleSelectStock}
                onTradeStock={handleTradeStock}
                onResearchStock={handleResearchStock}
                onRefresh={refreshAll}
              />
            </div>
          )}

          {currentView === 'portfolio' && (
            <div className="max-w-6xl mx-auto space-y-6">
              <PortfolioPanel
                portfolio={portfolio}
                loading={loadingPortfolio}
                onRefresh={refreshAll}
                onTrade={handleTradeStock}
                onResearch={handleResearchStock}
              />
            </div>
          )}

          {currentView === 'orders' && (
            <div className="max-w-6xl mx-auto space-y-6">
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
                news={news}
                loading={loadingNews}
                scope={newsScope}
                onScopeChange={(newScope) => {
                  setNewsScope(newScope);
                  loadNews(newScope);
                }}
                onFilterChange={(q) => loadNews(newsScope, q)}
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
              currentHoldingQty={currentHolding?.quantity || 0}
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
        onSelectStock={(sym) => {
          handleSelectStock(sym);
          setCurrentView('dashboard');
        }}
      />
    </div>
  );
}

export default App;
