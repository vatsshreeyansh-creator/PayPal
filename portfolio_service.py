"""Read-only demo-account and portfolio operations."""
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload
from models import Account, CashLedgerEntry, Holding
from provider import InstrumentData, MarketDataProvider, ProviderUnavailable
from schemas import AccountSummary, Holding as HoldingSchema, PortfolioSummary

CENT = Decimal("0.01")


def money(value: Decimal) -> str:
    return f"{Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP):.2f}"


def ensure_demo_account(session: Session, account_id: str, initial_cash: Decimal) -> Account:
    """Create the configured demo account once; later env changes do not reset it."""
    account = session.scalar(select(Account).where(Account.account_id == account_id))
    if account is None:
        account = Account(account_id=account_id, currency="INR", initial_cash=initial_cash)
        session.add(account)
        session.flush()
    has_opening = session.scalar(select(CashLedgerEntry.id).where(
        CashLedgerEntry.account_id == account.id, CashLedgerEntry.entry_key == "OPENING_BALANCE"))
    if has_opening is None:
        session.add(CashLedgerEntry(account_id=account.id, entry_key="OPENING_BALANCE",
                                    entry_type="INITIAL_CASH", amount=account.initial_cash))
    session.commit()
    return account


def get_cash_balance(session: Session, account: Account) -> Decimal:
    balance = session.scalar(select(func.coalesce(func.sum(CashLedgerEntry.amount), 0))
                             .where(CashLedgerEntry.account_id == account.id))
    return Decimal(balance)


def get_account(session: Session, account_id: str) -> AccountSummary:
    account = session.scalar(select(Account).where(Account.account_id == account_id))
    if account is None:
        raise LookupError("Configured demo account has not been initialized")
    return AccountSummary(account_id=account.account_id, currency=account.currency,
                          cash_balance=money(get_cash_balance(session, account)))


def get_portfolio(session: Session, provider: MarketDataProvider, account_id: str) -> PortfolioSummary:
    account = session.scalar(select(Account).where(Account.account_id == account_id)
                             .options(selectinload(Account.holdings).selectinload(Holding.instrument)))
    if account is None:
        raise LookupError("Configured demo account has not been initialized")

    holdings = sorted(account.holdings, key=lambda h: h.instrument.symbol)
    instruments = [InstrumentData(h.instrument.exchange, h.instrument.symbol, h.instrument.name,
                                  h.instrument.instrument_token, h.instrument.instrument_type)
                   for h in holdings]
    quotes = {}
    if instruments:
        try:
            quotes = provider.get_quotes(instruments)
        except ProviderUnavailable:
            # Quotes are read-time data. An outage leaves persisted positions intact.
            quotes = {}

    cash = get_cash_balance(session, account)
    total = cash
    complete_valuation = True
    result = []
    for holding in holdings:
        instrument = holding.instrument
        quote = quotes.get((instrument.exchange, instrument.symbol))
        quantity = holding.quantity
        average = Decimal(holding.average_purchase_price)
        realized = Decimal(holding.realized_pnl)
        if quote is None:
            current_price = market_value = unrealized = None
            complete_valuation = False
        else:
            current = Decimal(quote.price).quantize(CENT, rounding=ROUND_HALF_UP)
            value = (current * quantity).quantize(CENT, rounding=ROUND_HALF_UP)
            current_price, market_value = money(current), money(value)
            unrealized = money(value - (average * quantity))
            total += value
        result.append(HoldingSchema(
            symbol=instrument.symbol, name=instrument.name, quantity=str(quantity),
            average_purchase_price=money(average), current_price=current_price,
            market_value=market_value, realized_pnl=money(realized),
            unrealized_pnl=unrealized, currency=account.currency,
        ))
    return PortfolioSummary(
        account=AccountSummary(account_id=account.account_id, currency=account.currency,
                               cash_balance=money(cash)),
        holdings=result,
        total_portfolio_value=money(total) if complete_valuation else None,
    )
