"""Positions, leverage, position limits and the account's cross-margin bucket, read by
address.

Every read here is public, keyed by the account's address, and shared between markets
and concurrent callers for their `ttl`.
"""

from datetime import timedelta
from decimal import Decimal

from typing_extensions import Sequence
from typed_risex.account.positions import BuilderPosition
from typed_risex.markets.all import MarketInfo
from typed_risex.portfolio.details import PortfolioDetails
from tribulnation.sdk.market import PerpCollateral, PerpPosition, RemainingPositionLimit
from tribulnation.sdk.util import whole_leverage

from ..core import Shared, wad

ISOLATED = 1
"""The venue's `margin_mode` of an isolated position (`0` is cross)."""
MAX_LEVERAGE_SETTING = 255
"""The highest leverage a permit can carry: it commits to the value as a `uint8`."""
ISOLATED_UNOBSERVED = (
  'RISEx isolated positions are not supported yet: how the account summary counts '
  'their margin is unobserved'
)


async def fetch_positions(shared: Shared, account: str) -> list[BuilderPosition]:
  """Every page of `account.positions`, each page one translated request."""
  rows: list[BuilderPosition] = []
  pages = shared.client.account.positions_paged(account=account, page_size=100)
  async for page in pages.via(shared.call):
    rows.extend(page)
  return rows


async def positions(
  shared: Shared, *, ttl: timedelta | None
) -> Sequence[BuilderPosition]:
  """Every open position of the account, from `account.positions` (one row per open
  market; no row is flat)."""
  account = shared.require_account()
  return await shared.reads.read(
    ('positions', account),
    lambda: fetch_positions(shared, account),
    ttl=ttl,
  )


async def perp_position(
  shared: Shared, market_id: int, *, ttl: timedelta | None
) -> PerpPosition:
  """The signed position and entry price.

  `account.positions` sends both as 1e18-scaled integers, `size` already signed (a
  short is negative, beside `side: 'SELL'`). Not `account.position`, whose
  `avg_entry_price` is `''` while a position is open, nor `portfolio.details`, whose
  `side` read `0` for a short (testnet, 2026-11-17).
  """
  for p in await positions(shared, ttl=ttl):
    if p['market_id'] == market_id:
      return PerpPosition(size=wad(p['size']), entry_price=wad(p['avg_entry_price']))
  return PerpPosition()


async def leverage(shared: Shared, market_id: int, *, ttl: timedelta | None) -> Decimal:
  """The account's leverage on the market, which applies to new positions.

  `account.position`'s `leverage` is the setting, and the market's maximum where the
  account never set one: testnet SOL (never set) read `50`, and a 0.1 SOL position's
  initial margin was exactly 1/50 of its notional (2026-11-17). `portfolio.details`
  reads `0` for such markets, so it is not used.
  """
  account = shared.require_account()
  row = await shared.reads.read(
    ('position', account, market_id),
    lambda: shared.call(
      lambda: shared.client.account.position(market_id, account=account)
    ),
    ttl=ttl,
  )
  return row['position']['leverage']


async def set_leverage(shared: Shared, market_id: int, leverage: Decimal):
  """Set the account's leverage on the market (`account.update_leverage`).

  A signed permit, like orders, mined before the venue replies. The margin mode is a
  separate venue setting (`update_margin_mode`), so this leaves it alone. The value is
  checked against the market's `max_leverage` (the cached market configuration
  `rules()` reports) before signing: above it the permit reverts on chain with
  `InvalidLeverage` (testnet BTC, maximum 50: 51, 100 and 255 reverted, 50 was
  accepted, 2026-11-18). The shared `account.position` read is dropped, so the next
  `leverage()` reads the new setting.

  Raises:
    ValueError: `leverage` is not a positive whole number, is above 255, or is above
      the market's maximum.
    AuthError: The client has no signer key.
  """
  value = whole_leverage(leverage)
  if value > MAX_LEVERAGE_SETTING:
    raise ValueError(
      f'RISEx leverage is at most {MAX_LEVERAGE_SETTING} (a uint8 in the permit), '
      f'got {leverage}'
    )
  maximum = (await shared.market(market_id))['config']['max_leverage']
  if value > maximum:
    raise ValueError(
      f'RISEx market {market_id} allows leverage up to {maximum}, got {leverage}'
    )
  shared.require_signer()
  account = shared.require_account()
  await shared.call(
    lambda: shared.client.account.update_leverage(market_id, leverage=str(value))
  )
  shared.reads.forget(('position', account, market_id))


async def details(shared: Shared, *, ttl: timedelta | None) -> PortfolioDetails:
  """The account's portfolio summary and positions, shared for the caller's `ttl`."""
  account = shared.require_account()
  return await shared.reads.read(
    ('details', account),
    lambda: shared.call(lambda: shared.client.portfolio.details(account)),
    ttl=ttl,
  )


def bucket(d: PortfolioDetails) -> PerpCollateral:
  """The account's cross bucket from its portfolio summary.

  Equity is `cross_margin_balance` (the USDC balance plus the cross positions'
  unrealized PnL), free collateral `free_collateral`, the margins the summary's
  totals, and leverage `account_leverage`, the notional over equity.

  Raises:
    NotImplementedError: The account holds an isolated position.
  """
  if any(p['margin_mode'] == ISOLATED and p['size'] != 0 for p in d['positions']):
    raise NotImplementedError(ISOLATED_UNOBSERVED)
  s = d['summary']
  return PerpCollateral(
    equity=s['cross_margin_balance'],
    free_collateral=s['free_collateral'],
    initial_margin=s['total_initial_margin'],
    maintenance_margin=s['total_maintenance_margin'],
    leverage=s['account_leverage'],
    margin_mode='cross',
  )


async def collateral(shared: Shared, *, ttl: timedelta | None) -> PerpCollateral:
  """The account's one cross bucket, whatever the market."""
  return bucket(await details(shared, ttl=ttl))


def remaining_position_limit(
  market: MarketInfo, *, size: Decimal
) -> RemainingPositionLimit:
  """The room per direction under the market's two caps, as notional at its mark price.

  Both are in base units, like the venue's other sizes: `max_position_size` caps the
  account's position, so a direction has it less what the position holds in it; the
  market's `open_interest_limit` less its `open_interest` bounds both directions, as a
  new position on either side can raise open interest. On mainnet (2026-11-17) the
  open-interest limits were base amounts (BTC 750 beside 247.6 open) and every
  `max_position_size` was `100000000`, binding nowhere.
  """
  mark = market['mark_price']
  room = market['config']['open_interest_limit'] - market['open_interest']
  return RemainingPositionLimit.capped(
    max_notional=market['max_position_size'] * mark,
    position=size * mark,
    remaining=max(room, Decimal(0)) * mark,
  )
