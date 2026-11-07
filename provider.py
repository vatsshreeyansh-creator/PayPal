"""Mock provider boundary. Replace its implementation with Kite later."""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol, runtime_checkable


class ProviderUnavailable(Exception):
    """The market-data provider could not complete a required operation."""


@dataclass(frozen=True)
class InstrumentData:
    exchange: str
    symbol: str
    name: str
    instrument_token: int
    instrument_type: str


@dataclass(frozen=True)
class QuoteData:
    price: Decimal
    as_of: datetime
    simulated: bool


@runtime_checkable
class MarketDataProvider(Protocol):
    def search_stocks(self, query: str, limit: int = 20) -> list[InstrumentData]: ...
    def get_quotes(self, instruments: list[InstrumentData]) -> dict[tuple[str, str], QuoteData]: ...


class MockMarketDataProvider:
    """Deterministic sample equities and simulated prices; never live data."""
    _stocks = (
        InstrumentData("NSE", "TCS", "Tata Consultancy Services", 123, "EQ"),
        InstrumentData("NSE", "TATAMOTORS", "Tata Motors", 124, "EQ"),
        InstrumentData("NSE", "TATASTEEL", "Tata Steel", 125, "EQ"),
        InstrumentData("NSE", "INFY", "Infosys Limited", 126, "EQ"),
        InstrumentData("NSE", "RELIANCE", "Reliance Industries Limited", 127, "EQ"),
        InstrumentData("NSE", "HDFCBANK", "HDFC Bank Limited", 128, "EQ"),
        InstrumentData("NSE", "ITC", "ITC Limited", 129, "EQ"),
    )
    _prices = {"TCS": Decimal("3865.25"), "TATAMOTORS": Decimal("945.10"),
               "TATASTEEL": Decimal("158.40"), "INFY": Decimal("1512.75"),
               "RELIANCE": Decimal("2920.00"), "HDFCBANK": Decimal("1710.35"),
               "ITC": Decimal("438.20")}

    def search_stocks(self, query: str, limit: int = 20) -> list[InstrumentData]:
        needle = query.casefold()
        matching = [s for s in self._stocks if needle in s.symbol.casefold() or needle in s.name.casefold()]
        return matching[:limit]

    def get_quotes(self, instruments: list[InstrumentData]) -> dict[tuple[str, str], QuoteData]:
        now = datetime.now(timezone.utc)
        return {(i.exchange, i.symbol): QuoteData(self._prices[i.symbol], now, True)
                for i in instruments if i.symbol in self._prices}
