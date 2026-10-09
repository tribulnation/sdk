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
  order_id: str | None = None
  """ID of the order this fill executed, as `place_order` returns it and `OrderState.id` reports it. `None` if the venue does not report it."""
  client_order_id: str | None = None
  """Client order ID of that order: the `Order['client_order_id']` it was placed with, or one generated for it. `None` if the order has none or the venue does not report it."""
  price: Decimal
  qty: Decimal
  """Signed quantity (netagive -> sell, positive -> buy)"""
  time: datetime | None
  """Execution time (the venue's, e.g. block time); `None` when the venue doesn't report it on that feed, e.g. dYdX full-node fills (see `details['height']`)."""
  maker: bool
  fee: Fee | None = None
  details: Any = None


@dataclass(kw_only=True)
class ExchangeTrade(Trade):
  """A personal fill with its exchange-local market identity."""

  market_id: str
  """Native SDK market ID within the exchange, without venue/exchange prefixes."""
