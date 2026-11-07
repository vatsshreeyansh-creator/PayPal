"""Atomic simulated market-order execution and transaction history."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from models import Account, CashLedgerEntry, Holding, Instrument, Order, TransactionRecord
from portfolio_service import get_cash_balance
from provider import InstrumentData, MarketDataProvider, ProviderUnavailable
from schemas import OrderRequest, OrderResponse, Transaction

CENT = Decimal("0.01")


class StockNotFound(Exception): pass
class OrderNotFound(Exception): pass
class IdempotencyConflict(Exception): pass


def _cash(value: Decimal) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def _order_response(order: Order) -> OrderResponse:
    created = order.created_at or datetime.now(timezone.utc)
    return OrderResponse(order_id=order.order_id, symbol=order.instrument.symbol,
                         side=order.side, quantity=order.quantity, order_type=order.order_type,
                         status=order.status,
                         execution_price=f"{_cash(order.execution_price):.2f}" if order.execution_price is not None else None,
                         rejection_reason=order.rejection_reason, currency=order.account.currency,
                         created_at=created)


def _same_request(order: Order, request: OrderRequest, instrument_id: int) -> bool:
    return (order.instrument_id == instrument_id and order.side == request.side
            and order.quantity == request.quantity and order.order_type == request.order_type)


def _response_for_key(session: Session, account: Account, request: OrderRequest, instrument: Instrument | None):
    existing = session.scalar(select(Order).where(Order.account_id == account.id,
                                                   Order.idempotency_key == request.idempotency_key))
    if existing is None:
        return None
    if instrument is None or not _same_request(existing, request, instrument.id):
        raise IdempotencyConflict
    return _order_response(existing)


def place_order(session: Session, provider: MarketDataProvider, account_id: str,
                request: OrderRequest) -> tuple[OrderResponse, bool]:
    """Submit one idempotent market order. Business rejections are persisted as REJECTED."""
    account = session.scalar(select(Account).where(Account.account_id == account_id))
    instrument = session.scalar(select(Instrument).where(Instrument.exchange == "NSE",
                                                          Instrument.symbol == request.symbol.strip().upper()))
    if instrument is None:
        raise StockNotFound
    if account is None:
        raise RuntimeError("Demo account is not initialized")

    # Fast idempotency read. The unique DB constraint is still authoritative.
    prior = _response_for_key(session, account, request, instrument)
    if prior is not None:
        session.rollback()
        return prior, False

    quote = None
    data = InstrumentData(instrument.exchange, instrument.symbol, instrument.name,
                          instrument.instrument_token, instrument.instrument_type)
    try:
        quote = provider.get_quotes([data]).get((instrument.exchange, instrument.symbol))
    except ProviderUnavailable:
        quote = None
    price = _cash(Decimal(quote.price)) if quote is not None and quote.simulated else None
    if price is not None and price <= 0:
        price = None

    # Acquire SQLite's write reservation before checking cash/holdings. This
    # serializes competing balance-changing requests in the documented one-process demo.
    session.rollback()
    connection = session.connection()
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql("BEGIN IMMEDIATE")
    account = session.scalar(select(Account).where(Account.account_id == account_id))
    instrument = session.scalar(select(Instrument).where(Instrument.exchange == "NSE",
                                                          Instrument.symbol == request.symbol.strip().upper()))
    prior = _response_for_key(session, account, request, instrument)
    if prior is not None:
        session.rollback()
        return prior, False

    order = Order(order_id=str(uuid4()), account_id=account.id, instrument_id=instrument.id,
                  side=request.side, quantity=request.quantity, order_type="MARKET",
                  status="REJECTED", idempotency_key=request.idempotency_key)
    session.add(order)
    session.flush()  # also obtains the uniqueness lock before balance checks
    reason = None
    gross = _cash(price * request.quantity) if price is not None else None
    holding = session.scalar(select(Holding).where(Holding.account_id == account.id,
                                                    Holding.instrument_id == instrument.id))
    if price is None:
        reason = "QUOTE_UNAVAILABLE"
    elif request.side == "BUY" and get_cash_balance(session, account) < gross:
        reason = "INSUFFICIENT_CASH"
    elif request.side == "SELL" and (holding is None or holding.quantity < request.quantity):
        reason = "INSUFFICIENT_SHARES"

    if reason is not None:
        order.rejection_reason = reason
    else:
        order.status = "FILLED"
        order.execution_price = price
        transaction_id = str(uuid4())
        session.add(TransactionRecord(transaction_id=transaction_id, order_id=order.order_id,
                                      account_id=account.id, instrument_id=instrument.id,
                                      side=request.side, quantity=request.quantity,
                                      price=price, gross_amount=gross))
        cash_delta = -gross if request.side == "BUY" else gross
        session.add(CashLedgerEntry(account_id=account.id, order_id=order.order_id,
                                    entry_key=f"ORDER:{order.order_id}",
                                    entry_type=request.side, amount=cash_delta))
        if request.side == "BUY":
            if holding is None:
                holding = Holding(account_id=account.id, instrument_id=instrument.id,
                                  quantity=request.quantity, average_purchase_price=price,
                                  realized_pnl=Decimal("0.00"))
                session.add(holding)
            else:
                old_cost = Decimal(holding.average_purchase_price) * holding.quantity
                holding.quantity += request.quantity
                holding.average_purchase_price = ((old_cost + gross) / holding.quantity).quantize(
                    Decimal("0.000001"), rounding=ROUND_HALF_UP)
        else:
            realized = _cash((price - Decimal(holding.average_purchase_price)) * request.quantity)
            holding.realized_pnl = _cash(Decimal(holding.realized_pnl) + realized)
            holding.quantity -= request.quantity
            if holding.quantity == 0:
                session.delete(holding)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        account = session.scalar(select(Account).where(Account.account_id == account_id))
        instrument = session.scalar(select(Instrument).where(Instrument.exchange == "NSE",
                                                              Instrument.symbol == request.symbol.strip().upper()))
        prior = _response_for_key(session, account, request, instrument)
        if prior is not None:
            session.rollback()
            return prior, False
        raise
    return _order_response(order), True


def get_order(session: Session, account_id: str, order_id: str) -> OrderResponse:
    order = session.scalar(select(Order).join(Account).where(
        Order.account_id == Account.id, Account.account_id == account_id, Order.order_id == order_id))
    if order is None:
        raise OrderNotFound
    return _order_response(order)


def list_orders(session: Session, account_id: str) -> list[OrderResponse]:
    rows = session.scalars(select(Order).join(Account).where(
        Order.account_id == Account.id, Account.account_id == account_id
    ).order_by(Order.created_at.desc(), Order.id.desc())).all()
    return [_order_response(row) for row in rows]


def list_transactions(session: Session, account_id: str) -> list[Transaction]:
    rows = session.execute(select(TransactionRecord, Instrument, Order).join(Account, TransactionRecord.account_id == Account.id)
        .join(Instrument, TransactionRecord.instrument_id == Instrument.id)
        .join(Order, TransactionRecord.order_id == Order.order_id)
        .where(Account.account_id == account_id)
        .order_by(TransactionRecord.occurred_at.desc(), TransactionRecord.id.desc())).all()
    return [Transaction(transaction_id=tx.transaction_id, order_id=tx.order_id,
                        symbol=instrument.symbol, side=tx.side, quantity=str(tx.quantity),
                        price=f"{_cash(tx.price):.2f}", gross_amount=f"{_cash(tx.gross_amount):.2f}",
                        currency=account_currency, occurred_at=tx.occurred_at)
            for tx, instrument, order in rows
            for account_currency in [order.account.currency]]
