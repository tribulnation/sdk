"""Margin treatment in a Hyperliquid balance snapshot.

On a unified account the spot balance of a collateral token is the entire perp
equity backing that token — cross and isolated alike, unrealized PnL included.
So a snapshot subtracts every position's `unrealizedPnl` to leave collateral,
and never adds `leverage.rawUsd`: isolated margin is an allocation out of that
same balance, not a separate bucket to add on top.

This is easy to get backwards. `market/impl/collateral.py` describes isolated
margin as its own bucket (`rawUsd + unrealizedPnl`), which is true of the
per-position risk view but not of the account-level balance. Measured against a
live account holding an isolated position, `spot - sum(unrealizedPnl)` stayed at
`9027.73703382` across 2.5 minutes while unrealized PnL moved by ~21; excluding
the isolated leg made it drift by exactly that leg's change. These tests pin the
measured behaviour so the plausible-sounding version cannot be reintroduced.
"""
from decimal import Decimal

from tribulnation.hyperliquid.report.snapshots import Snapshots
from tribulnation.hyperliquid.report.subaccounts import STAKING, UNIFIED

USDC = '0'


def position(coin: str, *, upnl: str, isolated: str | None = None) -> dict:
  """One `assetPositions` entry; `isolated` supplies `rawUsd` when set."""
  leverage = (
    {'type': 'isolated', 'value': 5, 'rawUsd': isolated}
    if isolated is not None else {'type': 'cross', 'value': 5}
  )
  return {
    'position': {
      'coin': coin, 'szi': '1', 'entryPx': '100',
      'unrealizedPnl': upnl, 'leverage': leverage,
    }
  }


class StubInfo:
  """Minimal `Info` surface for snapshot assembly, main dex only."""

  def __init__(self, positions: list[dict], *, spot: str = '1000'):
    self.positions = positions
    self.spot = spot

  async def staking_summary(self, address: str):
    return {'delegated': '0', 'undelegated': '0'}

  async def spot_clearinghouse_state(self, address: str):
    return {'balances': [{'coin': 'USDC', 'token': 0, 'total': self.spot}]}

  async def perp_dexs(self):
    return [None]

  async def perp_meta_and_asset_ctxs(self, dex: str):
    return {'collateralToken': 0, 'universe': []}, []

  async def clearinghouse_state(self, address: str, dex: str = ''):
    return {'assetPositions': self.positions}


async def balances(positions: list[dict], *, spot: str = '1000') -> dict[str, Decimal]:
  record = await Snapshots(StubInfo(positions, spot=spot), '0xabc').snapshot()
  unified, = [s for s in record.snapshot.subaccounts if s.subaccount == UNIFIED]
  return unified.balances


async def test_cross_unrealized_pnl_is_removed_from_the_spot_balance():
  """Cross equity is part of the spot balance, so it already carries its PnL."""
  assert (await balances([position('BTC', upnl='40')]))[USDC] == Decimal('960')


async def test_isolated_unrealized_pnl_is_removed_too():
  """The spot balance carries isolated PnL as well; `rawUsd` is not added."""
  result = await balances([position('ETH', upnl='40', isolated='250')])

  assert result[USDC] == Decimal('960')


async def test_balance_is_invariant_to_price_with_an_isolated_position():
  """The measured property: collateral must not move when only the mark does.

  `spot` moves with unrealized PnL on a unified account, so a snapshot taken at
  two prices must report the same collateral. Here spot and PnL move together
  by 500 and the balance holds.
  """
  cheap = await balances([position('ETH', upnl='-500', isolated='250')], spot='500')
  dear = await balances([position('ETH', upnl='500', isolated='250')], spot='1500')

  assert cheap[USDC] == dear[USDC] == Decimal('1000')


async def test_cross_and_isolated_pnl_both_count():
  result = await balances([
    position('BTC', upnl='40'),
    position('ETH', upnl='-15', isolated='250'),
  ])

  assert result[USDC] == Decimal('975')   # 1000 - 40 + 15


async def test_staking_compartment_is_labelled():
  record = await Snapshots(StubInfo([]), '0xabc').snapshot()

  assert [s.subaccount for s in record.snapshot.subaccounts] == [UNIFIED, STAKING]
