"""Scoping shared by Coinbase's Advanced Trade exchanges and markets."""

from dataclasses import dataclass
from typing_extensions import Literal

from tribulnation.coinbase.core import Mixin

VENUE_ID: Literal['coinbase'] = 'coinbase'
SPOT_EXCHANGE_ID = 'spot'


@dataclass(frozen=True, kw_only=True)
class ExchangeMixin(Mixin):
  """An Advanced Trade exchange: one product family under one fee schedule."""

  @property
  def venue_id(self) -> Literal['coinbase']:
    """The venue ID."""
    return VENUE_ID

  @property
  def account_id(self) -> str:
    """Root SDK account key this object was opened under, else `venue_id`."""
    return self.shared.account_id or self.venue_id


@dataclass(frozen=True, kw_only=True)
class MarketMixin(ExchangeMixin):
  """One Advanced Trade product; `market_id` is the Coinbase product id verbatim."""

  product_id: str

  @property
  def market_id(self) -> str:
    return self.product_id

  @property
  def quote_asset(self) -> str:
    """The quote asset, read off the product id (`BTC-USD` -> `USD`)."""
    return self.product_id.split('-')[1]
