"""Watchlist business logic and normalized provider/database boundary."""
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from models import Instrument, WatchlistEntry
from provider import InstrumentData, MarketDataProvider, ProviderUnavailable
from schemas import Quote, StockSummary, WatchlistItem


class StockNotFound(Exception):
    pass


class WatchlistItemNotFound(Exception):
    pass


def _is_nse_equity(data: InstrumentData) -> bool:
    """Only NSE equity shares are eligible for stock search and watchlists."""
    return data.exchange == "NSE" and data.instrument_type == "EQ"


def stock_schema(stock: Instrument) -> StockSummary:
    return StockSummary(symbol=stock.symbol, name=stock.name, exchange=stock.exchange,
                        instrument_token=stock.instrument_token)


def _upsert(session: Session, data: InstrumentData) -> Instrument:
    row = session.scalar(select(Instrument).where(Instrument.exchange == data.exchange,
                                                  Instrument.symbol == data.symbol))
    if row is None:
        row = Instrument(exchange=data.exchange, symbol=data.symbol, name=data.name,
                         instrument_token=data.instrument_token, instrument_type=data.instrument_type)
        session.add(row)
        session.flush()
    else:
        row.name, row.instrument_token, row.instrument_type = data.name, data.instrument_token, data.instrument_type
    return row


def seed_instruments(session: Session, provider: MarketDataProvider) -> None:
    if session.scalar(select(Instrument.id).limit(1)) is not None:
        return
    for data in provider.search_stocks("", 100):
        if _is_nse_equity(data):
            _upsert(session, data)
    session.commit()


def search(session: Session, provider: MarketDataProvider, query: str, limit: int) -> list[StockSummary]:
    matches = provider.search_stocks(query, limit)
    rows = [_upsert(session, data) for data in matches if _is_nse_equity(data)]
    session.commit()
    return [stock_schema(row) for row in rows]


def _quote(data, quote_data) -> Quote:
    amount = Decimal(quote_data.price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return Quote(price=f"{amount:.2f}", as_of=quote_data.as_of,
                 simulated=quote_data.simulated)


def _item(stock: Instrument, quote_data=None) -> WatchlistItem:
    q = _quote(stock, quote_data) if quote_data is not None else None
    return WatchlistItem(stock=stock_schema(stock), quote=q)


def _quote_map(provider: MarketDataProvider, instruments: list[InstrumentData]):
    if not instruments:
        return {}
    try:
        return provider.get_quotes(instruments)
    except ProviderUnavailable:
        return {}


def add(session: Session, provider: MarketDataProvider, user_id: str, symbol: str) -> tuple[WatchlistItem, bool]:
    stock = session.scalar(select(Instrument).where(Instrument.exchange == "NSE",
                                                    Instrument.instrument_type == "EQ",
                                                    Instrument.symbol == symbol))
    if stock is None:
        try:
            matches = provider.search_stocks(symbol, 100)
        except ProviderUnavailable:
            raise
        data = next((m for m in matches if _is_nse_equity(m) and m.symbol.upper() == symbol), None)
        if data is None:
            raise StockNotFound
        stock = _upsert(session, data)
        session.commit()

    stmt = select(WatchlistEntry).where(WatchlistEntry.user_id == user_id,
                                         WatchlistEntry.instrument_id == stock.id)
    entry = session.scalar(stmt)
    created = entry is None
    if created:
        session.add(WatchlistEntry(user_id=user_id, instrument_id=stock.id))
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            entry = session.scalar(stmt)
            if entry is None:
                raise
            created = False
    data = InstrumentData(stock.exchange, stock.symbol, stock.name, stock.instrument_token, stock.instrument_type)
    quotes = _quote_map(provider, [data])
    return _item(stock, quotes.get((stock.exchange, stock.symbol))), created


def list_items(session: Session, provider: MarketDataProvider, user_id: str) -> list[WatchlistItem]:
    rows = session.execute(select(Instrument).join(WatchlistEntry).where(
        WatchlistEntry.instrument_id == Instrument.id, WatchlistEntry.user_id == user_id
    ).order_by(WatchlistEntry.created_at, Instrument.symbol)).scalars().all()
    instruments = [InstrumentData(r.exchange, r.symbol, r.name, r.instrument_token, r.instrument_type) for r in rows]
    quotes = _quote_map(provider, instruments)
    return [_item(row, quotes.get((row.exchange, row.symbol))) for row in rows]


def remove(session: Session, user_id: str, symbol: str) -> None:
    entry = session.scalar(select(WatchlistEntry).join(Instrument).where(
        WatchlistEntry.instrument_id == Instrument.id, WatchlistEntry.user_id == user_id,
        Instrument.exchange == "NSE", Instrument.symbol == symbol))
    if entry is None:
        raise WatchlistItemNotFound
    session.delete(entry)
    session.commit()
