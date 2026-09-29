"""Balances, positions and collateral behind one Advanced Trade market."""

from decimal import Decimal

from tribulnation.sdk.market import Collateral, Position

from typed_coinbase.schemas import V3Account

from .mixin import ExchangeMixin, MarketMixin


async def brokerage_account(self: ExchangeMixin, asset: str, /) -> V3Account | None:
  """Find the v3 brokerage account holding `asset`, sweeping every page."""
  paging = self.app.advanced_trade.http.accounts.list_paged()
  async for page in paging.via(self.call_app):
    for account in page:
      if account['currency'] == asset:
        return account


async def position(self: MarketMixin) -> Position:
  """Fetch the spot position: the base asset's brokerage balance."""
  account = await brokerage_account(self, self.product_id.split('-')[0])
  return Position(size=account['available_balance']['value'] if account else Decimal(0))


async def collateral(self: MarketMixin) -> Collateral:
  """Fetch the spot collateral bucket: the quote asset's brokerage balance."""
  account = await brokerage_account(self, self.quote_asset)
  if account is None:
    return Collateral(equity=Decimal(0), free_collateral=Decimal(0))
  free = account['available_balance']['value']
  return Collateral(equity=free + account['hold']['value'], free_collateral=free)
