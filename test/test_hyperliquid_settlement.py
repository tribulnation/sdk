"""Settlement-token resolution and subaccount attribution for Hyperliquid.

HIP-3 dexes settle in tokens other than USDC, and their universe entries are
already qualified with the dex name. Prefixing the dex name a second time built
keys (`flx:flx:TSLA`) that no fill ever matched, so every HIP-3 market fell
through a lookup default and booked its PnL in USDC. Nothing failed; the totals
still balanced in aggregate, and only a per-asset audit revealed it.
"""
from decimal import Decimal

import pytest

from tribulnation.hyperliquid.report.history.assets import (
  Assets, UnknownSettlementToken, settlement_token,
)
from tribulnation.hyperliquid.report.history.fills import parse_fills
from tribulnation.hyperliquid.report.history.funding import parse_fundings
from tribulnation.hyperliquid.report.history.main import History
from tribulnation.hyperliquid.report.subaccounts import UNIFIED

# `metaAndAssetCtxs` shapes, trimmed to the fields the code reads. The main dex
# names markets bare (`BTC`); named dexes qualify them (`flx:TSLA`).
METAS = {
  '': {'collateralToken': 0, 'universe': [{'name': 'BTC'}, {'name': 'ETH'}]},
  'flx': {'collateralToken': 360, 'universe': [{'name': 'flx:TSLA'}, {'name': 'flx:OIL'}]},
}

SPOT_META = {
  'tokens': [{'name': 'USDC', 'index': 0}, {'name': 'USDH', 'index': 360}],
  'universe': [{'index': 230, 'name': 'USDH/USDC', 'tokens': [360, 0]}],
}


class StubInfo:
  """Minimal `Info` surface for settlement resolution."""

  def __init__(self, metas=None, *, fail: str | None = None):
    self.metas = METAS if metas is None else metas
    self.fail = fail

  async def perp_dexs(self):
    return [None, {'name': 'flx'}]

  async def perp_meta_and_asset_ctxs(self, dex: str):
    if self.fail is not None and dex == self.fail:
      raise RuntimeError(f'dex {dex!r} unavailable')
    return self.metas[dex], []


def perp_fill(coin: str, *, tid: int = 1) -> dict:
  """One perp fill, opening from flat so realized PnL is defined."""
  return {
    'coin': coin, 'px': '100', 'sz': '1', 'side': 'B', 'time': 1_774_000_000_000,
    'startPosition': '0', 'oid': 1, 'tid': tid, 'hash': '0xabc',
    'fee': '0.1', 'feeToken': 'USDC', 'dir': 'Open Long',
  }


def funding_entry(coin: str) -> dict:
  return {
    'time': 1_774_000_000_000, 'hash': '0x0',
    'delta': {'type': 'funding', 'coin': coin, 'usdc': '1.5', 'szi': '-1',
              'fundingRate': '0.0000125', 'nSamples': 1},
  }


async def test_settlement_does_not_double_prefix_hip3_markets():
  """A named dex's universe is already qualified; prefixing again matches nothing."""
  settle = await History(StubInfo(), '0xabc').settlement()

  assert settle['flx:TSLA'] == '360'
  assert settle['flx:OIL'] == '360'
  assert settle['BTC'] == '0'
  assert not [key for key in settle if key.count(':') > 1]


async def test_settlement_propagates_an_unreadable_dex():
  """Skipping a dex would silently redenominate its markets to USDC."""
  with pytest.raises(RuntimeError, match='unavailable'):
    await History(StubInfo(fail='flx'), '0xabc').settlement()


def test_settlement_token_refuses_to_guess():
  with pytest.raises(UnknownSettlementToken, match='flx:OIL'):
    settlement_token({'BTC': '0'}, 'flx:OIL')


def test_parse_fills_raises_on_an_unmapped_market():
  """The default that hid the bug: an absent coin must not become USDC."""
  assets = Assets.of(SPOT_META)

  with pytest.raises(UnknownSettlementToken, match='flx:OIL'):
    parse_fills([perp_fill('flx:OIL')], assets=assets, settle={'BTC': '0'})


def test_parse_fundings_raises_on_an_unmapped_market():
  with pytest.raises(UnknownSettlementToken, match='flx:OIL'):
    parse_fundings([funding_entry('flx:OIL')], settle={'BTC': '0'})


def test_fills_settle_in_their_dex_token():
  """A HIP-3 fill denominates its realized PnL in the dex's collateral token."""
  assets = Assets.of(SPOT_META)
  settle = {'BTC': '0', 'flx:OIL': '360'}

  observations, _ = parse_fills(
    [perp_fill('BTC'), perp_fill('flx:OIL', tid=2)], assets=assets, settle=settle,
  )

  by_instrument = {o.instrument: o for o in observations}
  assert by_instrument['BTC'].settle == '0'
  assert by_instrument['flx:OIL'].settle == '360'


def test_observations_are_attributed_to_the_unified_compartment():
  """History must scope observations, or the snapshot's labels match nothing."""
  assets = Assets.of(SPOT_META)
  observations, _ = parse_fills(
    [perp_fill('BTC')], assets=assets, settle={'BTC': '0'},
  )
  fundings = parse_fundings([funding_entry('BTC')], settle={'BTC': '0'})

  assert observations[0].subaccount == UNIFIED
  assert fundings[0].subaccount == UNIFIED
  assert fundings[0].amount == Decimal('1.5')
