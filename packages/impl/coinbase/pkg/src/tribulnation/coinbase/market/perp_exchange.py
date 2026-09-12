"""Coinbase International Exchange's perpetual exchange."""

from typing_extensions import Collection, Mapping, Sequence
from dataclasses import dataclass

from tribulnation.sdk.market import (
  PerpCollateral,
  PerpExchange as _PerpExchange,
  PerpStats,
  Settings,
  Ticker,
)

from . import impl
from .perp_market import PerpMarket


@dataclass(frozen=True, kw_only=True)
class PerpExchange(impl.ExchangeMixin, _PerpExchange):
  """Every INTX perpetual on Coinbase Advanced Trade."""

  @property
  def exchange_id(self) -> str:
    return impl.INTX_EXCHANGE_ID

  async def markets(self) -> Sequence[str]:
    products = await impl.list_products(self, product_type='FUTURE', perpetual=True)
    return [product['product_id'] for product in products]

  async def market(self, market_id: str, /) -> PerpMarket:
    return PerpMarket(shared=self.shared, product_id=market_id)

  async def tickers(
    self, markets: Collection[str] | None = None, *, settings: Settings = {}
  ) -> Mapping[str, Ticker]:
    """Combine INTX trade statistics with batched bid/ask prices and sizes."""
    products = await impl.list_products(self, product_type='FUTURE', perpetual=True)
    return await impl.tickers(self, impl.filtered(products, markets))

  async def perp_stats(
    self, markets: Collection[str] | None = None, *, settings: Settings = {}
  ) -> Mapping[str, PerpStats]:
    """Fetch pricing and funding for many perpetuals at once.

    Index price, funding and open interest all live in the catalogue's
    `future_product_details`, so this is one sweep rather than a call per market. A
    product missing that blob is skipped rather than reported with holes.
    """
    products = await impl.list_products(self, product_type='FUTURE', perpetual=True)
    out: dict[str, PerpStats] = {}
    for product in impl.filtered(products, markets):
      stats = impl.parse_perp_stats(product)
      if stats is not None:
        out[product['product_id']] = stats
    return out

  async def perp_collateral(self, market_id: str | None = None, /) -> PerpCollateral:
    """Fetch INTX collateral.

    Coinbase holds one collateral pool per INTX portfolio rather than one per market,
    so both the exchange-level and the market-level read resolve to the same bucket.
    """
    return await impl.perp_collateral(self)
