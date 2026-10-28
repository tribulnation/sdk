"""Account fees, positions, the cross and isolated collateral buckets, leverage and the
spot wallet, of the client's trading sub-account."""

from datetime import timedelta
from decimal import Decimal

from typing_extensions import Literal

from typed_grvt.schemas import ClientTier, Position, SpotBalance
from typed_grvt.trading.account_summary import SubAccount
from tribulnation.sdk.core import MissingData
from tribulnation.sdk.market import Balance, Fees, PerpCollateral, PerpPosition

from ..core import FEE_UNIT, Shared
from .common import scope


async def fees(shared: Shared) -> Fees:
  """The account tier's futures maker and taker rates, the same for every perpetual and
  both sides (`ClientTier`, in millionths of notional)."""
  tier = await client_tier(shared)
  return Fees.symmetric(
    maker=tier['futures_maker_fee'] * FEE_UNIT,
    taker=tier['futures_taker_fee'] * FEE_UNIT,
  )


async def spot_fees(shared: Shared) -> Fees:
  """The account tier's spot maker and taker rates, the same for every spot instrument
  and both sides (`ClientTier`, in millionths of notional like the futures rates)."""
  tier = await client_tier(shared)
  return Fees.symmetric(
    maker=tier['spot_maker_fee'] * FEE_UNIT, taker=tier['spot_taker_fee'] * FEE_UNIT
  )


async def client_tier(shared: Shared) -> ClientTier:
  """The account's fee tier, from the funding account summary."""
  shared.require_session()
  summary = await shared.call(shared.client.trading.funding_account_summary)
  return summary['tier']


async def spot_wallet(
  shared: Shared, *, ttl: timedelta | None = None
) -> list[SpotBalance]:
  """The trading sub-account's spot wallet: one row per currency it has held.

  This is `spot_account_summary`, not `account_summary`'s `spot_balances` (the
  futures wallet's cash). Spot fills settle here: GRVT's exchange contract moves a
  spot trade's base and quote in the sub-account's spot wallet and refuses one that
  would leave either negative, so it holds no borrow. One answer serves every market,
  shared for the caller's `ttl`.
  """
  shared.require_session()
  summary = await shared.reads.read(
    ('spot_account_summary',),
    lambda: shared.call(shared.client.trading.spot_account_summary),
    ttl=ttl,
  )
  return summary['spot_balances']


def spot_balance(rows: list[SpotBalance], asset: str) -> Balance:
  """One currency's spot balance, zero when the wallet lists none.

  `total` is the venue's `balance`; `free` its `available_to_transfer`, what can
  leave the wallet. Whether that excludes what open spot orders hold is unverified:
  no account read had an open spot order.
  """
  for b in rows:
    if b['currency'] == asset:
      return Balance(total=b['balance'], free=b['available_to_transfer'])
  return Balance(total=Decimal(0), free=Decimal(0))


async def perp_position(shared: Shared, instrument: str) -> PerpPosition:
  """The signed position and average entry; flat when the venue lists none."""
  shared.require_session()
  kind, base, quote = scope(await shared.instrument(instrument))
  rows = await shared.call(
    lambda: shared.client.trading.positions(kind=kind, base=base, quote=quote)
  )
  for p in rows:
    if p['instrument'] == instrument:
      return PerpPosition(size=p['size'], entry_price=p['entry_price'])
  return PerpPosition()


async def summary(shared: Shared) -> SubAccount:
  """The trading sub-account's summary: equity, margins, balances and positions."""
  shared.require_session()
  return await shared.call(shared.client.trading.account_summary)


def cross_bucket(s: SubAccount) -> PerpCollateral:
  """The cross bucket, in the settlement currency (USDT).

  Equity is `total_cross_equity`: `total_equity` less every isolated position's own
  balance and unrealized PnL. `initial_margin` and `maintenance_margin` are the cross
  positions' alone (an isolated position's are its `isolated_im`/`isolated_mm`).

  Free collateral is `margin_balance` (the cross equity at each asset's collateral
  value ratio, 99.8% for USDT in multi-asset mode) less `initial_margin`, floored at
  zero: on testnet it equalled `position_margin_limits`' `max_addable_amount`, the
  margin the venue lets a position draw from the pool, with and without cross
  positions. Leverage is the cross positions' notional over equity.
  """
  equity = s['total_cross_equity']
  notional = sum(
    (abs(p['notional']) for p in s['positions'] if p['margin_type'] == 'CROSS'),
    Decimal(0),
  )
  return PerpCollateral(
    equity=equity,
    free_collateral=max(s['margin_balance'] - s['initial_margin'], Decimal(0)),
    initial_margin=s['initial_margin'],
    maintenance_margin=s['maintenance_margin'],
    leverage=notional / equity if notional and equity > 0 else Decimal(0),
    margin_mode='cross',
  )


def isolated_figure(
  p: Position, field: Literal['isolated_balance', 'isolated_im', 'isolated_mm']
) -> Decimal:
  """One of an isolated position's own figures, which the venue sends only for isolated
  positions.

  Raises:
    MissingData: The venue omitted it.
  """
  value = p.get(field)
  if value is None:
    raise MissingData(
      'GRVT omitted an isolated position figure', market_id=p['instrument'], field=field
    )
  return value


def isolated_bucket(p: Position) -> PerpCollateral:
  """An isolated position's own bucket, in its quote currency (USDT).

  Equity is the position's `isolated_balance` (the wallet balance moved out of the
  cross pool into it) plus its unrealized PnL; the margins are `isolated_im` and
  `isolated_mm`. Free collateral is equity above the initial margin, floored at zero,
  which matched `position_margin_limits`' `max_removable_amount` on testnet. Leverage is
  the position's notional over equity.

  Raises:
    MissingData: The venue omitted an isolated figure from an isolated position.
  """
  balance = isolated_figure(p, 'isolated_balance')
  initial = isolated_figure(p, 'isolated_im')
  maintenance = isolated_figure(p, 'isolated_mm')
  equity = balance + p['unrealized_pnl']
  return PerpCollateral(
    equity=equity,
    free_collateral=max(equity - initial, Decimal(0)),
    initial_margin=initial,
    maintenance_margin=maintenance,
    leverage=abs(p['notional']) / equity if equity > 0 else Decimal(0),
    margin_mode='isolated',
  )


def market_bucket(s: SubAccount, instrument: str) -> PerpCollateral:
  """The bucket backing a market: its isolated position's own, else cross.

  A market without a position draws on the cross pool even when its margin type is
  set to isolated: an isolated position's margin is moved out of the cross pool when
  it opens.
  """
  for p in s['positions']:
    if p['instrument'] == instrument and p['margin_type'] == 'ISOLATED':
      return isolated_bucket(p)
  return cross_bucket(s)


async def leverage(
  shared: Shared, instrument: str, *, ttl: timedelta | None = None
) -> Decimal:
  """The account's initial leverage on the instrument (`all_initial_leverage`, 10 unless
  changed). It is the instrument's setting in either margin type: an isolated position
  opens with it too. One account-wide answer serves every instrument, shared for the
  caller's `ttl`.

  Raises:
    ValueError: The venue reports no leverage for the instrument.
  """
  shared.require_session()
  response = await shared.reads.read(
    ('all_initial_leverage',),
    lambda: shared.call(shared.client.trading.all_initial_leverage),
    ttl=ttl,
  )
  for row in response['results']:
    if row['instrument'] == instrument:
      return row['leverage']
  raise ValueError(f'GRVT reports no leverage for {instrument}')
