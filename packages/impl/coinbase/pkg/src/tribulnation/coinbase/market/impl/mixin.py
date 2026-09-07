"""Scoping shared by Coinbase's Advanced Trade exchanges and markets."""

from dataclasses import dataclass

from tribulnation.coinbase.core import Mixin

VENUE_ID = 'coinbase'
SPOT_EXCHANGE_ID = 'spot'
INTX_EXCHANGE_ID = 'intx'
"""Coinbase International Exchange, the venue's only perpetual-swap product family."""


@dataclass(frozen=True, kw_only=True)
class ExchangeMixin(Mixin):
  """An Advanced Trade exchange: one product family under one fee schedule."""

  @property
  def venue_id(self) -> str:
    return VENUE_ID


@dataclass(frozen=True, kw_only=True)
class MarketMixin(ExchangeMixin):
  """One Advanced Trade product.

  Spot and perpetuals share every endpoint on this surface -- `BTC-USD` and
  `BTC-PERP-INTX` differ only in which product id they name -- so `market_id` is the
  Coinbase product id verbatim.
  """

  product_id: str

  @property
  def market_id(self) -> str:
    return self.product_id

  @property
  def quote_asset(self) -> str:
    """The quote asset, read off the product id (`BTC-USD` -> `USD`)."""
    return self.product_id.split('-')[1]
