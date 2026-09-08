"""Settlement-token resolution and subaccount attribution for Hyperliquid.

HIP-3 dexes settle in tokens other than USDC, and their universe entries are
already qualified with the dex name. Prefixing the dex name a second time built
keys (`flx:flx:TSLA`) that no fill ever matched, so every HIP-3 market fell
through a lookup default and booked its PnL in USDC. Nothing failed; the totals
still balanced in aggregate, and only a per-asset audit revealed it.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from typing_extensions import Mapping, cast

from typed_hyperliquid.info import Info
from typed_hyperliquid.info.perp_dexs import PerpDex
from typed_hyperliquid.info.perp_meta_and_asset_ctxs import (
  PerpAssetContext,
  PerpDexMeta,
)
from typed_hyperliquid.info.spot_meta import SpotMeta
from typed_hyperliquid.info.user_fills_by_time import UserFill
from typed_hyperliquid.info.user_funding import UserFundingEntry

from tribulnation.hyperliquid.report.history.assets import (
  Assets,
  UnknownSettlementToken,
  settlement_token,
)
from tribulnation.hyperliquid.report.history.fills import parse_fills
from tribulnation.hyperliquid.report.history.funding import parse_fundings
from tribulnation.hyperliquid.report.history.main import History
from tribulnation.hyperliquid.report.subaccounts import UNIFIED

TIME = datetime(2026, 3, 20, 8, 26, 40, tzinfo=timezone.utc)
"""One millisecond timestamp, shared by every fixture row."""

# `metaAndAssetCtxs` shapes, trimmed to the fields the code reads. The main dex
# names markets bare (`BTC`); named dexes qualify them (`flx:TSLA`).
METAS: Mapping[str, PerpDexMeta] = {
  '': {
    'collateralToken': 0,
    'marginTables': [],
    'universe': [
      {'name': 'BTC', 'maxLeverage': 40, 'szDecimals': 5},
      {'name': 'ETH', 'maxLeverage': 25, 'szDecimals': 4},
    ],
  },
  'flx': {
    'collateralToken': 360,
    'marginTables': [],
    'universe': [
      {'name': 'flx:TSLA', 'maxLeverage': 5, 'szDecimals': 2},
      {'name': 'flx:OIL', 'maxLeverage': 5, 'szDecimals': 2},
    ],
  },
}

SPOT_META: SpotMeta = {
  'tokens': [
    {
      'name': 'USDC',
      'index': 0,
      'szDecimals': 2,
      'weiDecimals': 8,
      'tokenId': '0x' + '0' * 32,
      'isCanonical': True,
      'evmContract': None,
      'fullName': None,
    },
    {
      'name': 'USDH',
      'index': 360,
      'szDecimals': 2,
      'weiDecimals': 8,
      'tokenId': '0x' + '1' * 32,
      'isCanonical': True,
      'evmContract': None,
      'fullName': None,
    },
  ],
  'universe': [
    {'index': 230, 'name': 'USDH/USDC', 'tokens': (360, 0), 'isCanonical': True}
  ],
}


class StubInfo:
  """Minimal `Info` surface for settlement resolution."""

  def __init__(
    self,
    metas: Mapping[str, PerpDexMeta] | None = None,
    *,
    fail: str | None = None,
  ):
    self.metas = METAS if metas is None else metas
    self.fail = fail

  async def perp_dexs(self) -> list[PerpDex | None]:
    return [
      None,
      {
        'name': 'flx',
        'fullName': 'Felix',
        'deployer': '0xdead',
        'feeRecipient': None,
        'oracleUpdater': None,
        'assetToFundingMultiplier': [],
        'assetToStreamingOiCap': [],
      },
    ]

  async def perp_meta_and_asset_ctxs(
    self, dex: str
  ) -> tuple[PerpDexMeta, list[PerpAssetContext]]:
    if self.fail is not None and dex == self.fail:
      raise RuntimeError(f'dex {dex!r} unavailable')
    return self.metas[dex], []


def history(info: StubInfo) -> History:
  """Build a `History` over a stubbed client."""
  return History(cast(Info, info), '0xabc')


def perp_fill(coin: str, *, tid: int = 1) -> UserFill:
  """One perp fill, opening from flat so realized PnL is defined."""
  return {
    'coin': coin,
    'px': Decimal('100'),
    'sz': Decimal('1'),
    'side': 'B',
    'time': TIME,
    'startPosition': Decimal(0),
    'oid': 1,
    'tid': tid,
    'hash': '0xabc',
    'fee': Decimal('0.1'),
    'feeToken': 'USDC',
    'dir': 'Open Long',
    'closedPnl': Decimal(0),
    'crossed': True,
    'twapId': None,
  }


def funding_entry(coin: str) -> UserFundingEntry:
  """One funding payment on `coin`."""
  return {
    'time': TIME,
    'hash': '0x0',
    'delta': {
      'type': 'funding',
      'coin': coin,
      'usdc': Decimal('1.5'),
      'szi': Decimal('-1'),
      'fundingRate': Decimal('0.0000125'),
      'nSamples': 1,
    },
  }


async def test_settlement_does_not_double_prefix_hip3_markets():
  """A named dex's universe is already qualified; prefixing again matches nothing."""
  settle = await history(StubInfo()).settlement()

  assert settle['flx:TSLA'] == '360'
  assert settle['flx:OIL'] == '360'
  assert settle['BTC'] == '0'
  assert not [key for key in settle if key.count(':') > 1]


async def test_settlement_propagates_an_unreadable_dex():
  """Skipping a dex would silently redenominate its markets to USDC."""
  with pytest.raises(RuntimeError, match='unavailable'):
    await history(StubInfo(fail='flx')).settlement()


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
    [perp_fill('BTC'), perp_fill('flx:OIL', tid=2)],
    assets=assets,
    settle=settle,
  )

  by_instrument = {o.instrument: o for o in observations if o.type == 'future_trade'}
  assert by_instrument['BTC'].settle == '0'
  assert by_instrument['flx:OIL'].settle == '360'


def test_observations_are_attributed_to_the_unified_compartment():
  """History must scope observations, or the snapshot's labels match nothing."""
  assets = Assets.of(SPOT_META)
  observations, _ = parse_fills(
    [perp_fill('BTC')],
    assets=assets,
    settle={'BTC': '0'},
  )
  fundings = parse_fundings([funding_entry('BTC')], settle={'BTC': '0'})

  assert observations[0].subaccount == UNIFIED
  assert fundings[0].subaccount == UNIFIED
  assert fundings[0].amount == Decimal('1.5')
