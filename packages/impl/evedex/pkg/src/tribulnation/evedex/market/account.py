"""Positions, leverage, position limits and the account's cross-margin bucket.

Every read here works with an API key alone, and is shared between markets and
concurrent callers for their `ttl`.
"""

from datetime import timedelta
from decimal import Decimal
import asyncio

from typing_extensions import Sequence
from typed_evedex.exchange.account.available_balance import AvailableBalance
from typed_evedex.schemas import Instrument, Position, User
from tribulnation.sdk.market import PerpCollateral, PerpPosition, RemainingPositionLimit
from tribulnation.sdk.util import whole_leverage

from ..core import DEFAULT_LEVERAGE, Shared
from .common import signed

OVERRIDE_UNOBSERVED = (
  'EVEDEX per-account leverage limits (`riskFactorOverride.leverageLimit`) are not '
  'supported yet: which instruments they apply to is undocumented'
)


async def positions(shared: Shared, *, ttl: timedelta | None) -> Sequence[Position]:
  """Every position record of the account (`positions.list`), flat ones included: a
  record keeps an instrument's leverage setting at zero quantity."""
  shared.require_account()
  result = await shared.reads.read(
    ('positions',),
    lambda: shared.call(shared.client.exchange.positions.list),
    ttl=ttl,
  )
  return result['list']


def record(rows: Sequence[Position], instrument: str) -> Position | None:
  """The account's position record on an instrument, if it has one."""
  for p in rows:
    if p['instrument'] == instrument:
      return p


async def perp_position(
  shared: Shared, instrument: str, *, ttl: timedelta | None
) -> PerpPosition:
  """The signed position and entry price; `quantity` is unsigned beside `side`. The
  venue publishes a bankruptcy price, not a liquidation price, so none is reported."""
  p = record(await positions(shared, ttl=ttl), instrument)
  if p is None or p['quantity'] == 0:
    return PerpPosition()
  return PerpPosition(size=signed(p['side'], p['quantity']), entry_price=p['avgPrice'])


async def leverage(shared: Shared, instrument: str, *, ttl: timedelta | None) -> int:
  """The account's leverage on the instrument: its position record's, which keeps the
  setting while flat, else the venue's default of 1 for an instrument never set."""
  p = record(await positions(shared, ttl=ttl), instrument)
  return DEFAULT_LEVERAGE if p is None else p['leverage']


async def set_leverage(shared: Shared, name: str, value: Decimal):
  """Set the account's leverage on the instrument (`positions.set_leverage`), checked
  against the instrument's `maxLeverage` first. Not signed: an API key suffices. The
  shared positions read is dropped, so the next `leverage()` reads the new setting.

  Raises:
    ValueError: `value` is not a positive whole number, or is above the instrument's
      maximum.
    AuthError: The client is public.
  """
  row = await shared.instrument(name)
  whole = whole_leverage(value)
  if whole > row['maxLeverage']:
    raise ValueError(
      f'EVEDEX {name} allows leverage up to {row["maxLeverage"]}, got {value}'
    )
  shared.require_account()
  await shared.call(
    lambda: shared.client.exchange.positions.set_leverage(name, leverage=whole)
  )
  shared.reads.forget(('positions',))


async def available_balance(
  shared: Shared, *, ttl: timedelta | None
) -> AvailableBalance:
  """The account's margin summary, shared for the caller's `ttl`."""
  shared.require_account()
  return await shared.reads.read(
    ('available_balance',),
    lambda: shared.call(shared.client.exchange.account.available_balance),
    ttl=ttl,
  )


def bucket(summary: AvailableBalance, rows: Sequence[Position]) -> PerpCollateral:
  """The account's one cross bucket.

  Equity is the trading balance (`funding.balance`) plus every position's
  `unRealizedPnL`; free collateral is the venue's `availableBalance` (the balance less
  the initial margin of positions and open orders and less negative unrealized PnL);
  the initial margin is the positions' (open orders' reservations show in free
  collateral only); the maintenance margin the positions' `maintenanceMargin`; and
  leverage the positions' `volume` (notional) over equity.
  """
  equity = summary['funding']['balance'] + sum(
    (p['unRealizedPnL'] for p in rows), Decimal(0)
  )
  notional = sum((p['volume'] for p in summary['position']), Decimal(0))
  return PerpCollateral(
    equity=equity,
    free_collateral=summary['availableBalance'],
    initial_margin=sum((p['initialMargin'] for p in summary['position']), Decimal(0)),
    maintenance_margin=sum((p['maintenanceMargin'] for p in rows), Decimal(0)),
    leverage=notional / equity if notional and equity > 0 else Decimal(0),
    margin_mode='cross',
  )


async def collateral(shared: Shared, *, ttl: timedelta | None) -> PerpCollateral:
  """The account's one cross bucket, whatever the market."""
  summary, rows = await asyncio.gather(
    available_balance(shared, ttl=ttl), positions(shared, ttl=ttl)
  )
  return bucket(summary, rows)


async def me(shared: Shared, *, ttl: timedelta | None) -> User:
  """The account's user record (fee rates, risk overrides), shared for `ttl`."""
  shared.require_account()
  return await shared.reads.read(
    ('me',), lambda: shared.call(shared.client.exchange.account.me), ttl=ttl
  )


def remaining_position_limit(
  instrument: Instrument, *, user: User, size: Decimal, leverage: int
) -> RemainingPositionLimit:
  """The room per direction under the instrument's `leverageLimit` tier for the
  account's leverage, as notional at the mark price.

  `leverageLimit` maps a leverage to the largest position notional allowed at it; a
  leverage the table does not name has no published limit (`None`). The venue
  publishes no open-interest cap.

  Raises:
    NotImplementedError: The account has its own leverage limits.
  """
  if 'leverageLimit' in user['riskFactorOverride']:
    raise NotImplementedError(OVERRIDE_UNOBSERVED)
  mark = instrument['markPrice']
  return RemainingPositionLimit.capped(
    max_notional=instrument['leverageLimit'].get(str(leverage)),
    position=size * mark,
  )
