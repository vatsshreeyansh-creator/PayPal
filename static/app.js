/*
 * TradePoint browser shell. API fields intentionally follow openapi.json and
 * the generated static/api-types.d.ts; provider text is always added as text.
 */
/** @typedef {import("./api-types").components["schemas"]["AccountSummary"]} AccountSummary */
/** @typedef {import("./api-types").components["schemas"]["PortfolioSummary"]} PortfolioSummary */
/** @typedef {import("./api-types").components["schemas"]["WatchlistItem"]} WatchlistItem */
/** @typedef {import("./api-types").components["schemas"]["OrderResponse"]} OrderResponse */
/** @typedef {import("./api-types").components["schemas"]["Transaction"]} Transaction */
/** @typedef {import("./api-types").components["schemas"]["NewsArticle"]} NewsArticle */
/** @typedef {import("./api-types").components["schemas"]["ResearchSuggestion"]} ResearchSuggestion */

const $ = (selector, root = document) => root.querySelector(selector);
const make = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
};

/** @type {WatchlistItem[]} */
let watchlistItems = [];
/** @type {PortfolioSummary | null} */
let portfolioData = null;
/** @type {NewsArticle[]} */
let newsArticles = [];
let nextNewsToken = null;
let selectedArticleId = null;
let selectedMarketStock = null;

async function api(path, options = {}) {
  let response;
  try {
    const headers = {};
    if (options.body) headers['Content-Type'] = 'application/json';
    response = await fetch(path, {headers, ...options});
  } catch (_) {
    throw new Error('TradePoint could not reach the server. Check that the app is running.');
  }
  let body;
  try { body = await response.json(); }
  catch (_) { throw new Error('The server returned an invalid response.'); }
  if (!response.ok) throw new Error(body.error?.message || 'The request could not be completed.');
  return body;
}

function setInline(id, message = '', isError = false) {
  const node = document.getElementById(id);
  if (!node) return;
  node.textContent = message;
  node.classList.toggle('error', Boolean(isError));
}

function showMessage(message, isError = false) {
  const node = $('#global-message');
  node.textContent = message;
  node.classList.toggle('error', isError);
  node.hidden = false;
  window.clearTimeout(showMessage.timer);
  showMessage.timer = window.setTimeout(() => { node.hidden = true; }, 5000);
}

// Prices and monetary totals stay strings as returned by the backend.
function money(value, currency = 'INR') {
  if (value === null || value === undefined) return 'Unavailable';
  return currency === 'INR' ? `₹ ${value}` : `${value} ${currency}`;
}

function pnlClass(value) {
  if (value === null || value === undefined) return 'neutral';
  return value.startsWith('-') ? 'neg' : value === '0.00' ? 'neutral' : 'pos';
}

function formattedDate(value, includeTime = false) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString(undefined, includeTime
    ? {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'}
    : {month: 'short', day: 'numeric'});
}

function emptyRow(bodyId, colspan, message) {
  const body = document.getElementById(bodyId);
  body.replaceChildren();
  const row = document.createElement('tr');
  const cell = make('td', 'empty-cell', message);
  cell.colSpan = colspan;
  row.append(cell);
  body.append(row);
}

function setView(name, updateHash = true) {
  const target = document.querySelector(`[data-view="${name}"]`);
  if (!target) return;
  document.querySelectorAll('.view-panel').forEach(view => view.classList.toggle('active', view === target));
  document.querySelectorAll('[data-view-link]').forEach(link => link.classList.toggle('active', link.dataset.viewLink === name));
  const label = document.querySelector(`[data-view-link="${name}"]`);
  const title = label?.cloneNode(true);
  title?.querySelector('.nav-icon')?.remove();
  $('#current-section').textContent = title?.textContent.trim() || name;
  if (updateHash) history.replaceState(null, '', `#${name}`);
  document.body.classList.remove('nav-open');
  const loaders = {dashboard: loadDashboard, portfolio: loadPortfolio, watchlist: loadWatchlist,
    markets: loadMarketContext, orders: loadOrders, news: () => loadNews(true)};
  if (loaders[name]) loaders[name]();
  window.scrollTo({top: 0, behavior: 'smooth'});
}

document.querySelectorAll('[data-view-link]').forEach(link => {
  link.addEventListener('click', event => {
    event.preventDefault();
    setView(link.dataset.viewLink);
  });
});
document.querySelectorAll('[data-go-view]').forEach(button => button.addEventListener('click', () => setView(button.dataset.goView)));
document.querySelectorAll('[data-refresh]').forEach(button => button.addEventListener('click', () => {
  const loaders = {portfolio: loadPortfolio, watchlist: loadWatchlist, orders: loadOrders};
  loaders[button.dataset.refresh]?.();
}));
$('#menu-toggle').addEventListener('click', () => document.body.classList.toggle('nav-open'));
$('#sidebar-scrim').addEventListener('click', () => document.body.classList.remove('nav-open'));
window.addEventListener('hashchange', () => setView(location.hash.slice(1) || 'dashboard', false));

async function loadAccount() {
  /** @type {AccountSummary} */
  const account = await api('/api/account');
  $('#account-id').textContent = account.account_id;
  $('#dashboard-cash').textContent = money(account.cash_balance, account.currency);
  $('#dashboard-account-note').textContent = `${account.currency} demo account`;
  $('#portfolio-cash').textContent = money(account.cash_balance, account.currency);
  return account;
}

function renderPortfolio(data) {
  portfolioData = data;
  $('#portfolio-total').textContent = money(data.total_portfolio_value, data.account.currency);
  $('#portfolio-count').textContent = String(data.holdings.length);
  $('#dashboard-total').textContent = money(data.total_portfolio_value, data.account.currency);
  $('#dashboard-total-note').textContent = data.total_portfolio_value === null
    ? 'Incomplete: at least one quote is unavailable' : 'Cash plus available holding values';
  $('#dashboard-holdings').textContent = String(data.holdings.length);
  const body = $('#portfolio-holdings');
  if (!data.holdings.length) {
    emptyRow('portfolio-holdings', 7, 'No holdings yet. Completed buy orders will appear here.');
    return;
  }
  body.replaceChildren();
  data.holdings.forEach(holding => {
    const row = document.createElement('tr');
    const company = make('td'); company.append(make('strong', 'table-primary-text', holding.name));
    row.append(company, make('td', 'ticker-cell', holding.symbol), make('td', '', holding.quantity),
      make('td', '', money(holding.average_purchase_price, holding.currency)),
      make('td', '', money(holding.current_price, holding.currency)),
      make('td', '', money(holding.market_value, holding.currency)));
    row.append(make('td', pnlClass(holding.unrealized_pnl), holding.unrealized_pnl === null
      ? 'Unavailable' : money(holding.unrealized_pnl, holding.currency)));
    body.append(row);
  });
}

async function loadPortfolio() {
  try {
    const [accountResult, portfolio] = await Promise.all([api('/api/account'), api('/api/portfolio')]);
    $('#account-id').textContent = accountResult.account_id;
    $('#dashboard-cash').textContent = money(accountResult.cash_balance, accountResult.currency);
    $('#dashboard-account-note').textContent = `${accountResult.currency} demo account`;
    renderPortfolio(portfolio);
  } catch (error) {
    $('#portfolio-holdings').replaceChildren();
    emptyRow('portfolio-holdings', 7, error.message);
    showMessage(error.message, true);
  }
}

async function loadMarketContext() {
  const results = await Promise.allSettled([api('/api/portfolio'), api('/api/watchlist')]);
  if (results[0].status === 'fulfilled') renderPortfolio(results[0].value);
  if (results[1].status === 'fulfilled') renderWatchlist(results[1].value);
}

function renderWatchlist(data) {
  watchlistItems = data.items;
  $('#watchlist-count').textContent = `${data.items.length} saved ${data.items.length === 1 ? 'stock' : 'stocks'} · Quotes refresh when the list is loaded.`;
  const body = $('#watchlist');
  if (!data.items.length) {
    emptyRow('watchlist', 5, 'Your watchlist is empty. Search above to add an NSE equity.');
  } else {
    body.replaceChildren();
    data.items.forEach(item => {
      const row = document.createElement('tr');
      const name = make('td'); name.append(make('strong', 'table-primary-text', item.stock.name));
      row.append(name, make('td', 'ticker-cell', item.stock.symbol),
        make('td', 'price-cell', item.quote ? money(item.quote.price, item.quote.currency) : 'Unavailable'),
        make('td', 'quote-source', item.quote ? (item.quote.simulated ? 'Simulated quote' : 'Provider quote') : 'Quote unavailable'));
      const action = make('td');
      const remove = make('button', 'remove-button', 'Remove');
      remove.type = 'button'; remove.setAttribute('aria-label', `Remove ${item.stock.symbol} from watchlist`);
      remove.addEventListener('click', () => removeWatchlist(item.stock.symbol));
      action.append(remove); row.append(action); body.append(row);
    });
  }
  renderWatchlistPreview(data.items);
}

function renderWatchlistPreview(items) {
  const box = $('#dashboard-watchlist');
  box.replaceChildren();
  if (!items.length) {
    box.append(make('div', 'empty-cell', 'No saved stocks yet.'));
    return;
  }
  items.slice(0, 5).forEach(item => {
    const row = make('div', 'preview-item');
    row.append(make('span', 'symbol-avatar', item.stock.symbol.slice(0, 3)));
    const copy = make('div', 'preview-copy');
    copy.append(make('strong', '', item.stock.name), make('small', '', item.stock.symbol));
    row.append(copy, make('span', 'preview-value', item.quote ? money(item.quote.price) : '—'));
    box.append(row);
  });
}

async function loadWatchlist() {
  try { renderWatchlist(await api('/api/watchlist')); }
  catch (error) { emptyRow('watchlist', 5, error.message); showMessage(error.message, true); }
}

function renderSearchResults(container, results, onSelect, actionText = 'View') {
  container.replaceChildren();
  if (!results.length) {
    container.append(make('div', 'empty-cell', 'No matching NSE equities found.'));
    return;
  }
  results.forEach(stock => {
    const row = make('div', 'search-result');
    const copy = make('div');
    copy.append(make('div', 'search-result-name', stock.name),
      make('small', 'search-result-meta', `${stock.symbol} · ${stock.exchange} · Instrument ${stock.instrument_token}`));
    const actions = make('div', 'search-result-actions');
    const button = make('button', 'btn btn-sm btn-outline-primary', actionText);
    button.type = 'button'; button.addEventListener('click', () => onSelect(stock, button));
    actions.append(button); row.append(copy, actions); container.append(row);
  });
}

$('#search-form').addEventListener('submit', async event => {
  event.preventDefault();
  const results = $('#results'); results.replaceChildren();
  setInline('status', 'Searching…');
  try {
    const data = await api('/api/stocks/search', {method: 'POST', body: JSON.stringify({query: $('#query').value, limit: 20})});
    setInline('status', data.results.length ? 'Choose a stock to save it to your watchlist.' : 'No matching NSE equities found.');
    renderSearchResults(results, data.results, async (stock, button) => {
      button.disabled = true; button.textContent = 'Adding…';
      try {
        const result = await api('/api/watchlist', {method: 'POST', body: JSON.stringify({symbol: stock.symbol})});
        setInline('status', result.created ? `${stock.symbol} added to your watchlist.` : `${stock.symbol} is already in your watchlist.`);
        showMessage(result.created ? `${stock.symbol} added to watchlist.` : `${stock.symbol} is already saved.`);
        await loadWatchlist();
      } catch (error) { setInline('status', error.message, true); button.disabled = false; button.textContent = 'Add'; }
    }, 'Add');
  } catch (error) { setInline('status', error.message, true); }
});

async function removeWatchlist(symbol) {
  try {
    await api(`/api/watchlist/${encodeURIComponent(symbol)}`, {method: 'DELETE'});
    showMessage(`${symbol} removed from watchlist.`);
    await loadWatchlist();
  } catch (error) { showMessage(error.message, true); }
}

$('#global-search-form').addEventListener('submit', event => {
  event.preventDefault();
  $('#market-query').value = $('#global-search').value;
  setView('markets');
  $('#market-search-form').requestSubmit();
});

function quoteForSymbol(symbol) {
  const position = portfolioData?.holdings.find(item => item.symbol === symbol);
  if (position?.current_price) return {price: position.current_price, currency: position.currency, simulated: null};
  const saved = watchlistItems.find(item => item.stock.symbol === symbol);
  return saved?.quote || null;
}

function showMarketStock(stock) {
  selectedMarketStock = stock;
  const detail = $('#market-detail'); detail.replaceChildren();
  const header = make('div', 'market-stock-heading');
  const copy = make('div'); copy.append(make('h2', '', stock.name), make('p', 'ticker-cell', `${stock.symbol} · ${stock.exchange} equity`));
  header.append(copy, make('span', 'instrument-chip', `Token ${stock.instrument_token}`));
  detail.append(header, make('div', 'panel-footnote', 'Stock data shown here comes from the instrument search result.'));
  const quote = quoteForSymbol(stock.symbol);
  const quoteBox = $('#market-quote'); quoteBox.replaceChildren();
  if (quote) {
    quoteBox.append(make('strong', 'metric-value', money(quote.price, quote.currency)));
    quoteBox.append(make('small', 'quote-source', quote.simulated === null ? 'Available from portfolio quote' : quote.simulated ? 'Simulated quote' : 'Provider quote'));
  } else {
    quoteBox.append(make('span', '', 'No quote is available for this stock in the current account views.'));
  }
}

$('#market-search-form').addEventListener('submit', async event => {
  event.preventDefault();
  const box = $('#market-results'); box.replaceChildren(make('div', 'empty-cell', 'Searching…'));
  try {
    const data = await api('/api/stocks/search', {method: 'POST', body: JSON.stringify({query: $('#market-query').value, limit: 20})});
    renderSearchResults(box, data.results, stock => showMarketStock(stock));
  } catch (error) { box.replaceChildren(make('div', 'inline-status error', error.message)); }
});

function renderOrderResult(order) {
  const box = $('#trade-result'); box.replaceChildren();
  const card = make('div', 'trade-result-card');
  card.append(make('h3', '', `${order.side} ${order.symbol} · ${order.status}`));
  const grid = make('div', 'trade-result-list');
  const values = [['Order ID', order.order_id], ['Quantity', order.quantity], ['Order type', order.order_type],
    ['Execution price', money(order.execution_price, order.currency)], ['Created', formattedDate(order.created_at, true)],
    ['Result', order.status === 'FILLED' ? 'Simulated fill' : order.rejection_reason || 'Rejected']];
  values.forEach(([label, value]) => { const item = make('div'); item.append(make('small', '', label), make('strong', '', value)); grid.append(item); });
  card.append(grid); box.append(card);
  if (order.status === 'REJECTED') setInline('trade-status', `Order rejected: ${order.rejection_reason}.`, true);
  else setInline('trade-status', 'Paper order filled successfully.');
}

$('#trade-form').addEventListener('submit', async event => {
  event.preventDefault();
  const submit = event.submitter;
  if (submit) submit.disabled = true;
  setInline('trade-status', 'Submitting simulated order…');
  const side = $('input[name="side"]:checked').value;
  const payload = {symbol: $('#trade-symbol').value.trim().toUpperCase(), side,
    quantity: Number($('#trade-quantity').value), order_type: 'MARKET',
    idempotency_key: `web-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`};
  try {
    /** @type {OrderResponse} */
    const result = await api('/api/orders', {method: 'POST', body: JSON.stringify(payload)});
    renderOrderResult(result);
    await Promise.allSettled([loadAccount(), loadPortfolio(), loadOrders(), loadWatchlist()]);
  } catch (error) { setInline('trade-status', error.message, true); }
  finally { if (submit) submit.disabled = false; }
});

function renderTransactions(transactions) {
  const body = $('#transactions-table');
  if (!body) return;
  if (!transactions.length) {
    emptyRow('transactions-table', 7, 'No completed transactions yet.');
    emptyRow('dashboard-transactions', 5, 'No transactions yet.');
    return;
  }
  body.replaceChildren();
  transactions.forEach(tx => {
    const row = document.createElement('tr');
    row.append(make('td', '', formattedDate(tx.occurred_at, true)), make('td', 'ticker-cell', tx.symbol),
      make('td', tx.side === 'BUY' ? 'pos' : 'neg', tx.side), make('td', '', tx.quantity),
      make('td', '', money(tx.price, tx.currency)), make('td', '', money(tx.gross_amount, tx.currency)),
      make('td', 'id-cell', tx.order_id));
    body.append(row);
  });
  const preview = $('#dashboard-transactions'); preview.replaceChildren();
  if (!transactions.length) { emptyRow('dashboard-transactions', 5, 'No transactions yet.'); return; }
  transactions.slice(0, 5).forEach(tx => {
    const row = document.createElement('tr');
    row.append(make('td', 'ticker-cell', tx.symbol), make('td', tx.side === 'BUY' ? 'pos' : 'neg', tx.side),
      make('td', '', tx.quantity), make('td', '', money(tx.price, tx.currency)), make('td', '', formattedDate(tx.occurred_at)));
    preview.append(row);
  });
}

function renderOrders(orders) {
  const body = $('#orders-table');
  if (!orders.length) { emptyRow('orders-table', 8, 'No orders have been submitted.'); return; }
  body.replaceChildren();
  orders.forEach(order => {
    const row = document.createElement('tr');
    row.append(make('td', '', formattedDate(order.created_at, true)), make('td', 'ticker-cell', order.symbol),
      make('td', order.side === 'BUY' ? 'pos' : 'neg', order.side), make('td', '', order.quantity),
      make('td', '', order.order_type), make('td', '', money(order.execution_price, order.currency)));
    const statusCell = make('td');
    statusCell.append(make('span', `status-pill ${order.status === 'FILLED' ? 'filled' : 'rejected'}`, order.status));
    if (order.rejection_reason) statusCell.append(make('small', 'status-reason', order.rejection_reason));
    row.append(statusCell, make('td', 'id-cell', order.order_id));
    row.title = `Order ID: ${order.order_id}`;
    body.append(row);
  });
}

async function loadOrders() {
  try {
    const [orders, transactions] = await Promise.all([api('/api/orders'), api('/api/transactions')]);
    renderOrders(orders); renderTransactions(transactions);
  } catch (error) {
    emptyRow('orders-table', 8, error.message); emptyRow('transactions-table', 7, error.message);
  }
}

function articleCard(article, selected = false) {
  const card = make('article', `news-card${selected ? ' selected' : ''}`);
  const meta = make('div', 'article-meta');
  meta.append(make('span', '', article.source), make('span', '', '·'), make('span', '', formattedDate(article.published_at)));
  (article.symbols || []).slice(0, 4).forEach(symbol => meta.append(make('span', 'article-symbol', symbol)));
  card.append(meta, make('h3', '', article.title));
  if (article.summary) card.append(make('p', '', article.summary));
  card.addEventListener('click', () => loadArticle(article.article_id));
  return card;
}

function renderNewsFeed(append = false) {
  const box = $('#news-feed');
  if (!append) box.replaceChildren();
  if (!newsArticles.length && !append) {
    box.append(make('div', 'panel-card empty-cell', 'No relevant articles were returned for this feed.'));
    return;
  }
  newsArticles.slice(append ? Math.max(0, newsArticles.length - 20) : 0).forEach(article => {
    box.append(articleCard(article, article.article_id === selectedArticleId));
  });
  if (nextNewsToken) {
    const more = make('button', 'btn btn-outline-secondary load-more-button', 'Load more articles');
    more.type = 'button'; more.addEventListener('click', () => loadNews(false)); box.append(more);
  }
}

async function loadNews(reset = true) {
  const scope = $('#news-scope').value;
  const query = $('#news-query').value.trim();
  if (reset) { newsArticles = []; nextNewsToken = null; }
  setInline('news-status', reset ? 'Loading news…' : 'Loading more…');
  const params = new URLSearchParams({scope, page_size: '20'});
  if (query) params.set('query', query);
  if (!reset && nextNewsToken) params.set('page_token', nextNewsToken);
  try {
    const data = await api(`/api/news?${params.toString()}`);
    newsArticles = reset ? data.articles : [...newsArticles, ...data.articles];
    nextNewsToken = data.next_page_token;
    setInline('news-status', `${newsArticles.length} article${newsArticles.length === 1 ? '' : 's'} loaded.`);
    renderNewsFeed();
    renderDashboardNews(newsArticles);
  } catch (error) { setInline('news-status', error.message, true); if (reset) $('#news-feed').replaceChildren(make('div', 'panel-card empty-cell', error.message)); }
}

function renderDashboardNews(articles) {
  const box = $('#dashboard-news'); box.replaceChildren();
  if (!articles.length) { box.append(make('div', 'empty-cell', 'No news available yet.')); return; }
  articles.slice(0, 4).forEach(article => {
    const item = make('button', 'preview-item preview-news'); item.type = 'button';
    const copy = make('span', 'preview-copy'); copy.append(make('strong', '', article.title), make('small', '', `${article.source} · ${formattedDate(article.published_at)}`));
    item.append(copy, make('span', 'preview-arrow', '→'));
    item.addEventListener('click', () => { setView('news'); loadArticle(article.article_id); });
    box.append(item);
  });
}

async function loadArticle(articleId) {
  selectedArticleId = articleId;
  const panel = $('#article-detail'); panel.replaceChildren(make('div', 'empty-cell', 'Loading article…'));
  try {
    /** @type {NewsArticle} */
    const article = await api(`/api/news/${encodeURIComponent(articleId)}`);
    panel.replaceChildren();
    const meta = make('div', 'article-meta');
    meta.append(make('span', '', article.source), make('span', '', '·'), make('span', '', formattedDate(article.published_at, true)));
    (article.symbols || []).forEach(symbol => meta.append(make('span', 'article-symbol', symbol)));
    panel.append(meta, make('h2', '', article.title));
    if (article.summary) panel.append(make('p', 'article-body', article.summary));
    if (article.content) panel.append(make('div', 'article-body', article.content));
    else panel.append(make('div', 'article-body muted', 'Full article content is not available from the provider.'));
    const external = document.createElement('a');
    try {
      const target = new URL(article.url);
      if (target.protocol === 'https:' || target.protocol === 'http:') {
        external.href = target.href; external.target = '_blank'; external.rel = 'noopener noreferrer';
        external.className = 'article-link'; external.textContent = 'Open original article ↗'; panel.append(external);
      }
    } catch (_) { /* A malformed provider URL is omitted from the UI. */ }
    const summaryButton = make('button', 'btn btn-sm btn-primary-soft summary-trigger', 'Generate AI summary');
    summaryButton.type = 'button'; summaryButton.addEventListener('click', () => loadSummary(articleId, summaryButton));
    panel.append(summaryButton);
    renderNewsFeed();
  } catch (error) { panel.replaceChildren(make('div', 'inline-status error', error.message)); }
}

async function loadSummary(articleId, button) {
  button.disabled = true; button.textContent = 'Generating…';
  try {
    const summary = await api(`/api/news/${encodeURIComponent(articleId)}/summary`, {method: 'POST'});
    const box = make('section', 'summary-box');
    box.append(make('h3', '', 'AI-generated summary'), make('p', '', summary.summary));
    const groups = [['Reported facts', summary.reported_facts], ['Key developments', summary.key_developments],
      ['Potential positive implications', summary.positive_implications], ['Potential negative implications', summary.negative_implications]];
    groups.forEach(([label, values]) => {
      if (!values?.length) return;
      const section = make('div', 'summary-group'); section.append(make('strong', '', label));
      const list = document.createElement('ul'); values.forEach(value => list.append(make('li', '', value)));
      section.append(list); box.append(section);
    });
    box.append(make('p', 'summary-disclaimer', summary.disclaimer));
    $('#article-detail').append(box);
    button.textContent = 'Summary ready';
  } catch (error) { button.disabled = false; button.textContent = 'Generate AI summary'; showMessage(error.message, true); }
}

$('#news-form').addEventListener('submit', event => { event.preventDefault(); loadNews(true); });

function renderResearch(data) {
  const target = $('#research-results'); target.replaceChildren();
  data.suggestions.forEach(suggestion => {
    const card = make('article', 'research-card');
    const title = make('div', 'research-card-heading');
    title.append(make('h2', '', `${suggestion.symbol} research`), make('small', 'muted', `Generated ${formattedDate(suggestion.generated_at, true)}`));
    card.append(title, make('p', 'research-thesis', suggestion.thesis));
    const facts = [['Reported facts', suggestion.reported_facts], ['Potential positive implications', suggestion.positive_implications],
      ['Potential negative implications', suggestion.negative_implications], ['Risks to consider', suggestion.risks]];
    facts.forEach(([label, values]) => {
      const section = make('section', 'research-section'); section.append(make('h3', '', label));
      if (!values?.length) section.append(make('p', 'muted', 'No items returned.'));
      else { const list = document.createElement('ul'); values.forEach(value => list.append(make('li', '', value))); section.append(list); }
      card.append(section);
    });
    const evidence = make('section', 'research-section'); evidence.append(make('h3', '', 'Supporting articles'));
    if (!suggestion.evidence_article_ids.length) evidence.append(make('p', 'muted', 'No article references were available.'));
    else {
      const links = make('div', 'evidence-links');
      suggestion.evidence_article_ids.forEach(id => {
        const button = make('button', 'evidence-link', `Article ${id.slice(0, 8)}`); button.type = 'button';
        button.addEventListener('click', () => { setView('news'); loadArticle(id); }); links.append(button);
      }); evidence.append(links);
    }
    card.append(evidence, make('div', 'research-uncertainty', `Uncertainty: ${suggestion.uncertainty}`));
    target.append(card);
  });
  target.append(make('p', 'summary-disclaimer', data.disclaimer));
}

$('#research-form').addEventListener('submit', async event => {
  event.preventDefault();
  setInline('research-status', 'Preparing research…');
  $('#research-results').replaceChildren();
  try {
    const result = await api('/api/research/suggestions', {method: 'POST',
      body: JSON.stringify({symbol: $('#research-symbol').value.trim().toUpperCase()})});
    renderResearch(result);
    setInline('research-status', 'Research generated from available news evidence.');
  } catch (error) { setInline('research-status', error.message, true); }
});

async function loadDashboard() {
  const tasks = await Promise.allSettled([loadAccount(), api('/api/portfolio').then(renderPortfolio),
    api('/api/watchlist').then(renderWatchlist), api('/api/transactions'),
    api('/api/news?scope=personal&page_size=5')]);
  const failed = tasks.find(result => result.status === 'rejected');
  if (failed) showMessage(failed.reason?.message || 'Some dashboard data could not be loaded.', true);
  const txResult = tasks[3];
  if (txResult.status === 'fulfilled') renderTransactions(txResult.value);
  else emptyRow('dashboard-transactions', 5, 'Transactions could not be loaded.');
  const newsResult = tasks[4];
  if (newsResult.status === 'fulfilled') renderDashboardNews(newsResult.value.articles);
  else $('#dashboard-news').replaceChildren(make('div', 'empty-cell', 'News could not be loaded.'));
}

async function loadInitialShell() {
  const initialView = location.hash.slice(1) || 'dashboard';
  loadAccount().catch(error => showMessage(error.message, true));
  setView(initialView, false);
}

loadInitialShell();
