"""Account-scoped reads -- balances, positions and margin -- in either account mode.

Classic keeps spot and futures balances in separate compartments (`spot.account.assets`
against `mix.account.get`, each with its own `available` semantics); UTA has one unified
pool (`account.assets`) every product line draws on. Each read below dispatches on the
account's detected mode.
"""

from typing_extensions import Literal
from decimal import Decimal
import asyncio

from tribulnation.sdk.market import Collateral, PerpCollateral, PerpPosition, Position
from typed_bitget.classic.mix.account.get import MixAccountAsset
from typed_bitget.classic.spot.account.assets import SpotAccountAsset
from typed_bitget.uta.account.assets import AccountAsset, AccountAssets

from .mixin import VenueMixin
from .parse import MARGIN_COIN, PERP


async def classic_spot_asset(self: VenueMixin, coin: str) -> SpotAccountAsset | None:
  """One coin's row in a Classic account's spot wallet, if it has one."""
  rows = await self.call(
    lambda: self.client.classic.spot.account.assets(coin=coin, validate=self.validate)
  )
  return next((r for r in rows if r['coin'] == coin), None)


async def uta_assets(self: VenueMixin) -> AccountAssets:
  """A UTA account's unified pool: equity, margin figures and per-coin balances."""
  return await self.call(lambda: self.client.uta.account.assets(validate=self.validate))


async def uta_coin(self: VenueMixin, coin: str) -> AccountAsset | None:
  """One coin's row in a UTA account's unified pool, if it has one.

  The pool omits coins with a zero balance, so no row means nothing held.
  """
  assets = await uta_assets(self)
  return next((a for a in assets['assets'] if a['coin'] == coin), None)


async def spot_position(self: VenueMixin, base: str) -> Position:
  """The base-asset balance backing a spot market, orders and holds included."""
  if await self.is_uta():
    row = await uta_coin(self, base)
    return Position(size=row['balance'] if row else Decimal(0))
  asset = await classic_spot_asset(self, base)
  if asset is None:
    return Position()
  return Position(size=asset['available'] + asset['frozen'] + asset['locked'])


async def spot_collateral(self: VenueMixin, quote: str) -> Collateral:
  """The quote-asset balance backing a spot market: total held, and the free part."""
  if await self.is_uta():
    row = await uta_coin(self, quote)
    if row is None:
      return Collateral(equity=Decimal(0), free_collateral=Decimal(0))
    return Collateral(equity=row['balance'], free_collateral=row['available'])
  asset = await classic_spot_asset(self, quote)
  if asset is None:
    return Collateral(equity=Decimal(0), free_collateral=Decimal(0))
  return Collateral(
    equity=asset['available'] + asset['frozen'] + asset['locked'],
    free_collateral=asset['available'],
  )


async def uta_pool(self: VenueMixin) -> Collateral:
  """A UTA account's whole unified pool, valued in USD."""
  assets = await uta_assets(self)
  return Collateral(equity=assets['accountEquity'], free_collateral=assets['effEquity'])


async def classic_mix_account(self: VenueMixin, symbol: str) -> MixAccountAsset:
  """A Classic account's USDT-margined futures wallet, as seen from one symbol."""
  return await self.call(
    lambda: self.client.classic.mix.account.get(
      symbol=symbol, product_type=PERP, margin_coin=MARGIN_COIN, validate=self.validate
    )
  )


async def perp_position(self: VenueMixin, symbol: str) -> PerpPosition:
  """The net position in one contract: signed size and average entry price.

  A hedge-mode account may hold a long and a short row at once; they are netted, with
  the entry price averaged by size.
  """
  rows: list[tuple[Literal['long', 'short'], Decimal, Decimal]] = []
  if await self.is_uta():
    positions = await self.call(
      lambda: self.client.uta.position.current_positions(
        PERP, symbol=symbol, validate=self.validate
      )
    )
    rows = [
      (p['posSide'], Decimal(p['total']), Decimal(p['avgPrice']))
      for p in positions['list'] or []
    ]
  else:
    positions = await self.call(
      lambda: self.client.classic.mix.position.get(
        PERP, symbol=symbol, margin_coin=MARGIN_COIN, validate=self.validate
      )
    )
    rows = [(p['holdSide'], p['total'], p['openPriceAvg']) for p in positions]
  size = sum(
    (total if side == 'long' else -total for side, total, _ in rows), Decimal(0)
  )
  gross = sum((total for _, total, _ in rows), Decimal(0))
  if gross == 0:
    return PerpPosition()
  entry = sum((total * price for _, total, price in rows), Decimal(0)) / gross
  return PerpPosition(size=size, entry_price=entry)


def not_supported_classic_collateral() -> NotImplementedError:
  """Why a Classic account has no `PerpCollateral`."""
  return NotImplementedError(
    'not supported on a Classic account: `classic.mix.account.get` carries no '
    'initial or maintenance margin figure (only `available`, `accountEquity` and '
    '`crossedRiskRate`), and `PerpCollateral` requires both'
  )


async def uta_perp_collateral(
  self: VenueMixin, symbol: str | None = None
) -> PerpCollateral:
  """A UTA account's margin pool, with the margin mode configured for `symbol`.

  UTA runs one pool across every product line, so the figures are the same whatever
  the symbol; only `margin_mode` is symbol-specific. `account.settings` holds one row
  per (symbol, margin mode) rather than one per symbol -- the first row matching the
  symbol wins, and a symbol with no row is `cross`, the venue's default.
  """
  if symbol is None:
    assets = await uta_assets(self)
    mode: Literal['cross', 'isolated'] = 'cross'
  else:
    assets, settings = await asyncio.gather(
      uta_assets(self),
      self.call(lambda: self.client.uta.account.settings(validate=self.validate)),
    )
    config = next(
      (c for c in settings['symbolConfigList'] if c['symbol'] == symbol), None
    )
    mode = 'isolated' if config and config['marginMode'] == 'isolated' else 'cross'
  return PerpCollateral(
    equity=assets['accountEquity'],
    free_collateral=assets['effEquity'],
    initial_margin=assets['imr'],
    maintenance_margin=assets['mmr'],
    leverage=assets['leverage'],
    margin_mode=mode,
  )
