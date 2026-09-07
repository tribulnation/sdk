"""Coinbase Advanced Trade's spot exchange."""

from typing_extensions import Collection, Mapping, Sequence
from dataclasses import dataclass

from tribulnation.sdk.market import Exchange as _Exchange, Settings, Ticker

from . import impl
from .spot_market import SpotMarket


@dataclass(frozen=True, kw_only=True)
class SpotExchange(impl.ExchangeMixin, _Exchange):
  """Every `SPOT` product on Coinbase Advanced Trade."""

  @property
  def exchange_id(self) -> str:
    return impl.SPOT_EXCHANGE_ID

  async def markets(self) -> Sequence[str]:
    products = await impl.list_products(self, product_type='SPOT')
    return [product['product_id'] for product in products]

  async def market(self, market_id: str, /) -> SpotMarket:
    return SpotMarket(shared=self.shared, product_id=market_id)

  async def tickers(
    self, markets: Collection[str] | None = None, *, settings: Settings = {}
  ) -> Mapping[str, Ticker]:
    """Fetch a ticker snapshot for many spot markets at once.

    Read from the product catalogue, which carries last price and 24h volume but no
    book depth, so `bid_qty`/`ask_qty` are always unset -- use `depth` for those.
    """
    products = await impl.list_products(self, product_type='SPOT')
    return impl.tickers(impl.filtered(products, markets))
