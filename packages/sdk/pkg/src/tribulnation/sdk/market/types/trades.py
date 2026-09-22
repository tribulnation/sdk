from typing_extensions import Any
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime


@dataclass(kw_only=True)
class Trade:
  @dataclass(kw_only=True)
  class Fee:
    amount: Decimal
    """Fee paid (or received if negative, in fee asset units)."""
    asset: str

  id: str | None
  price: Decimal
  qty: Decimal
  """Signed quantity (netagive -> sell, positive -> buy)"""
  time: datetime
  maker: bool
  fee: Fee | None = None
  details: Any = None


@dataclass(kw_only=True)
class ExchangeTrade(Trade):
  """A personal fill with its exchange-local market identity."""

  market_id: str
  """Native SDK market ID within the exchange, without venue/exchange prefixes."""
