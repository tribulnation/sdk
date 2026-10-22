"""Account fees, positions, the cross collateral bucket and leverage, of the client's
trading sub-account."""

from decimal import Decimal

from typed_grvt.trading.account_summary import SubAccount
from tribulnation.sdk.market import Fees, PerpCollateral, PerpPosition

from ..core import FEE_UNIT, Shared
from .common import scope


async def fees(shared: Shared) -> Fees:
  """The account tier's futures maker and taker rates, the same for every perpetual and
  both sides (`ClientTier`, in millionths of notional)."""
  shared.require_session()
  summary = await shared.call(shared.client.trading.funding_account_summary)
  tier = summary['tier']
  return Fees.symmetric(
    maker=tier['futures_maker_fee'] * FEE_UNIT,
    taker=tier['futures_taker_fee'] * FEE_UNIT,
  )


async def perp_position(shared: Shared, instrument: str) -> PerpPosition:
  """The signed position and average entry; flat when the venue lists none."""
  shared.require_session()
  base, quote = scope(await shared.instrument(instrument))
  rows = await shared.call(
    lambda: shared.client.trading.positions(kind=['PERPETUAL'], base=base, quote=quote)
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

  Free collateral is `total_equity` less `initial_margin` (GRVT's equity required to
  open positions); leverage is the cross positions' notional over equity.
  """
  equity = s['total_equity']
  notional = sum(
    (abs(p['notional']) for p in s['positions'] if p['margin_type'] == 'CROSS'),
    Decimal(0),
  )
  return PerpCollateral(
    equity=equity,
    free_collateral=equity - s['initial_margin'],
    initial_margin=s['initial_margin'],
    maintenance_margin=s['maintenance_margin'],
    leverage=notional / equity if notional and equity > 0 else Decimal(0),
    margin_mode='cross',
  )


def market_bucket(s: SubAccount, instrument: str) -> PerpCollateral:
  """The bucket backing a market: cross, unless it holds an isolated position.

  Raises:
    NotImplementedError: The market holds an isolated position, whose bucket is
      unverified (no position could be made isolated to check it).
  """
  if any(
    p['instrument'] == instrument and p['margin_type'] == 'ISOLATED'
    for p in s['positions']
  ):
    raise NotImplementedError(
      f'GRVT isolated collateral is not supported: {instrument} holds an isolated position'
    )
  return cross_bucket(s)


async def leverage(
  shared: Shared, instrument: str, *, refetch: bool = False
) -> Decimal:
  """The account's initial leverage on the instrument (`all_initial_leverage`, 10 unless
  changed), cached per instrument.

  Raises:
    ValueError: The venue reports no leverage for the instrument.
  """
  if not refetch and (cached := shared.leverages.get(instrument)) is not None:
    return cached
  shared.require_session()
  response = await shared.call(shared.client.trading.all_initial_leverage)
  shared.leverages.update((r['instrument'], r['leverage']) for r in response['results'])
  if instrument not in shared.leverages:
    raise ValueError(f'GRVT reports no leverage for {instrument}')
  return shared.leverages[instrument]
