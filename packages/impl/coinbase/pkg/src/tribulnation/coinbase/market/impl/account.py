"""Balances, positions and collateral behind one Advanced Trade market."""

from decimal import Decimal

from tribulnation.sdk.market import Collateral, PerpCollateral, PerpPosition, Position

from typed_coinbase.schemas import V3Account

from tribulnation.coinbase.core import wrap_exceptions
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


@wrap_exceptions
async def portfolio_uuid(self: ExchangeMixin) -> str:
  """The INTX portfolio this key is scoped to."""
  permissions = await self.app.advanced_trade.http.key_permissions.get()
  return permissions['portfolio_uuid']


@wrap_exceptions
async def perp_position(self: MarketMixin) -> PerpPosition:
  """Fetch the open INTX perpetual position on this product.

  Needs a key scoped to an INTX portfolio: a `DEFAULT` retail key gets a live
  `PERMISSION_DENIED` here, surfaced as an `AuthError`.
  """
  uuid = await portfolio_uuid(self)
  response = await self.app.advanced_trade.http.perpetuals.positions.list(uuid)
  for row in response['positions']:
    if row['product_id'] == self.product_id:
      return PerpPosition(size=row['net_size'], entry_price=row['entry_vwap']['value'])
  return PerpPosition()


@wrap_exceptions
async def perp_collateral(self: ExchangeMixin) -> PerpCollateral:
  """Fetch the INTX portfolio's collateral bucket.

  Margins are reported as utilization ratios of collateral, so they are scaled back
  into quote units here. Same permission gate as `perp_position`.
  """
  uuid = await portfolio_uuid(self)
  summary = await self.app.advanced_trade.http.perpetuals.portfolio_summary(uuid)
  portfolio = summary['portfolios'][0]
  equity = portfolio['collateral']
  initial_margin = portfolio['portfolio_initial_margin'] * equity
  return PerpCollateral(
    equity=equity,
    free_collateral=equity - initial_margin,
    initial_margin=initial_margin,
    maintenance_margin=portfolio['portfolio_maintenance_margin'] * equity,
    leverage=portfolio['position_notional'] / equity if equity > 0 else Decimal(0),
    margin_mode='isolated'
    if portfolio['margin_type'] == 'MARGIN_TYPE_ISOLATED'
    else 'cross',
  )
