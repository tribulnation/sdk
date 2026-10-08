"""Spot balances, perpetual collateral buckets, notional caps and open interest.

Fixtures follow mainnet payload shapes observed on 2026-10-08, with invented values.
"""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock
from typing_extensions import Any

import pytest
from typed_aster.futures.account.info_with_join_margin import InfoWithJoinMargin
from typed_aster.futures.market.exchange_info import ExchangeInfoEndpoint
from typed_aster.futures.market.funding_info import FundingInfoEndpoint
from typed_aster.futures.market.open_interest import OpenInterestEndpoint
from typed_aster.futures.market.premium_index import PremiumIndex
from typed_aster.futures.market.remaining_openable_notional_value import (
  RemainingOpenableNotionalValue,
)
from typed_aster.futures.position.risk import Risk
from typed_aster.spot.account.info import Info as SpotInfo
from typed_aster.spot.market.exchange_info import ExchangeInfo as SpotExchangeInfo
from tribulnation.aster import AsterMarket
from tribulnation.aster.market import exchanges
from tribulnation.aster.market.markets import (
  PerpMarket,
  SpotMarket,
  cross_collateral,
  isolated_collateral,
)
from tribulnation.sdk.core import MissingData
from tribulnation.sdk.market import Collateral, PerpCollateral, Position

TIME = datetime(2026, 10, 8, tzinfo=timezone.utc)


def pair(symbol: str = 'ASTERUSDT') -> dict[str, Any]:
  """A native spot pair with the filters `rules` maps."""
  return {
    'symbol': symbol,
    'status': 'TRADING',
    'baseAsset': symbol.removesuffix('USDT'),
    'quoteAsset': 'USDT',
    'filters': [
      {
        'filterType': 'PRICE_FILTER',
        'tickSize': Decimal('0.0001'),
        'minPrice': Decimal('0.0001'),
        'maxPrice': Decimal(1000),
      },
      {
        'filterType': 'LOT_SIZE',
        'stepSize': Decimal('0.01'),
        'minQty': Decimal('0.01'),
        'maxQty': Decimal(100000),
      },
    ],
  }


def spot_market(monkeypatch: pytest.MonkeyPatch, *, mainnet: bool = True) -> SpotMarket:
  """A spot market over a credential-free client with its pair cached."""
  monkeypatch.setattr(
    SpotExchangeInfo, 'exchange_info', AsyncMock(return_value={'symbols': [pair()]})
  )
  shared = AsterMarket.new(public=True, mainnet=mainnet).shared
  return SpotMarket(shared=shared, symbol='ASTERUSDT')


def spot_info(*balances: tuple[str, str, str]) -> dict[str, Any]:
  """A spot `account.info` payload with the given free and locked balances."""
  return {
    'feeTier': 0,
    'canTrade': True,
    'canDeposit': True,
    'canWithdraw': True,
    'canBurnAsset': True,
    'updateTime': TIME,
    'balances': [
      {'asset': asset, 'free': Decimal(free), 'locked': Decimal(locked)}
      for asset, free, locked in balances
    ],
  }


async def test_spot_balances_are_free_plus_locked(monkeypatch: pytest.MonkeyPatch):
  """Base is the position; the quote is the collateral, free when not in orders."""
  market = spot_market(monkeypatch)
  info = spot_info(('ASTER', '10', '2.5'), ('USDT', '100', '40'), ('USDC', '7', '0'))
  monkeypatch.setattr(SpotInfo, 'info', AsyncMock(return_value=info))
  assert await market.position() == Position(size=Decimal('12.5'))
  assert await market.collateral() == Collateral(
    equity=Decimal(140), free_collateral=Decimal(100)
  )
  assert await market.available_notional() == Decimal(100)


async def test_unlisted_spot_assets_hold_zero(monkeypatch: pytest.MonkeyPatch):
  """The venue lists only assets with a balance."""
  market = spot_market(monkeypatch)
  monkeypatch.setattr(SpotInfo, 'info', AsyncMock(return_value=spot_info()))
  assert await market.position() == Position(size=Decimal(0))
  assert await market.collateral() == Collateral(
    equity=Decimal(0), free_collateral=Decimal(0)
  )


async def test_testnet_spot_balances_raise(monkeypatch: pytest.MonkeyPatch):
  """Testnet account information omits funded balances; zero would mislead."""
  market = spot_market(monkeypatch, mainnet=False)
  info = AsyncMock(return_value=spot_info())
  monkeypatch.setattr(SpotInfo, 'info', info)
  for method in (market.position, market.collateral, market.available_notional):
    with pytest.raises(NotImplementedError, match='testnet'):
      await method()
  assert info.await_count == 0


async def test_spot_fee_asset_depends_on_the_fill(monkeypatch: pytest.MonkeyPatch):
  """Buys pay in the base asset and sells in the quote asset (ADR 0028)."""
  rules = await spot_market(monkeypatch).rules()
  assert rules.fee_asset is None and rules.tick_size == Decimal('0.0001')


def position(symbol: str, **fields: Any) -> Any:
  """One flat one-way cross row of the join-margin account view."""
  row: dict[str, Any] = {
    'symbol': symbol,
    'initialMargin': Decimal(0),
    'maintMargin': Decimal(0),
    'unrealizedProfit': Decimal(0),
    'positionInitialMargin': Decimal(0),
    'openOrderInitialMargin': Decimal(0),
    'leverage': 5,
    'isolated': False,
    'entryPrice': Decimal(0),
    'maxNotional': Decimal(1000000),
    'positionSide': 'BOTH',
    'positionAmt': Decimal(0),
    'notional': Decimal(0),
    'isolatedWallet': Decimal(0),
    'updateTime': TIME,
  }
  row.update(fields)
  return row


def account(*positions: Any, **totals: str) -> Any:
  """A join-margin account view with invented totals."""
  row: dict[str, Any] = {
    'feeTier': 0,
    'canTrade': True,
    'canDeposit': True,
    'canWithdraw': True,
    'updateTime': TIME,
    'totalInitialMargin': Decimal(150),
    'totalMaintMargin': Decimal(30),
    'totalWalletBalance': Decimal(980),
    'totalUnrealizedProfit': Decimal(20),
    'totalMarginBalance': Decimal(1000),
    'totalPositionInitialMargin': Decimal(150),
    'totalOpenOrderInitialMargin': Decimal(0),
    'totalCrossWalletBalance': Decimal(980),
    'totalCrossUnPnl': Decimal(20),
    'availableBalance': Decimal(800),
    'maxWithdrawAmount': Decimal(800),
    'assets': [],
    'positions': list(positions),
  }
  row.update({k: Decimal(v) for k, v in totals.items()})
  return row


LONG = position(
  'BTCUSDT',
  positionAmt=Decimal('0.01'),
  notional=Decimal(1200),
  initialMargin=Decimal(120),
  maintMargin=Decimal(24),
)
SHORT = position(
  'ETHUSDT',
  positionAmt=Decimal('-0.1'),
  notional=Decimal(-300),
  initialMargin=Decimal(30),
  maintMargin=Decimal(6),
)


def test_cross_bucket_uses_join_margin_totals():
  """Equity, margins and free balance are the account totals; notional is unsigned."""
  assert cross_collateral(account(LONG, SHORT, position('SOLUSDT'))) == PerpCollateral(
    equity=Decimal(1000),
    free_collateral=Decimal(800),
    initial_margin=Decimal(150),
    maintenance_margin=Decimal(30),
    leverage=Decimal('1.5'),
    margin_mode='cross',
  )


def test_cross_bucket_excludes_isolated_positions():
  """An isolated position's own margin and requirements leave the cross bucket."""
  isolated = position(
    'SOLUSDT',
    isolated=True,
    positionAmt=Decimal(2),
    notional=Decimal(500),
    isolatedWallet=Decimal(110),
    unrealizedProfit=Decimal(-10),
    initialMargin=Decimal(50),
    maintMargin=Decimal(5),
  )
  bucket = cross_collateral(
    account(LONG, isolated, totalInitialMargin='170', totalMaintMargin='29')
  )
  assert (bucket.equity, bucket.initial_margin, bucket.maintenance_margin) == (
    Decimal(900),
    Decimal(120),
    Decimal(24),
  )
  assert bucket.leverage == Decimal(1200) / Decimal(900)
  assert isolated_collateral(isolated) == PerpCollateral(
    equity=Decimal(100),
    free_collateral=Decimal(50),
    initial_margin=Decimal(50),
    maintenance_margin=Decimal(5),
    leverage=Decimal(5),
    margin_mode='isolated',
  )


def test_buckets_match_venue_figures_with_live_isolated_shape():
  """Testnet-observed shape: the buckets match the venue's own cross and isolated figures.

  The account's wallet total includes the isolated wallet, while
  `totalCrossWalletBalance` and `totalCrossUnPnl` exclude it; `positionRisk` reports the
  isolated equity as `isolatedMargin`. Amounts are scaled stand-ins, not account data.
  """
  isolated = position(
    'BTCUSDT',
    isolated=True,
    positionAmt=Decimal('0.001'),
    notional=Decimal(80),
    isolatedWallet=Decimal(6),
    unrealizedProfit=Decimal('0.05'),
    initialMargin=Decimal(4),
    positionInitialMargin=Decimal(4),
    maintMargin=Decimal('0.2'),
    leverage=20,
  )
  cross = position(
    'ETHUSDT',
    positionAmt=Decimal('0.003'),
    notional=Decimal(8),
    unrealizedProfit=Decimal('0.01'),
    initialMargin=Decimal('0.4'),
    positionInitialMargin=Decimal('0.4'),
    maintMargin=Decimal('0.02'),
    leverage=20,
  )
  venue = account(
    isolated,
    cross,
    totalInitialMargin='4.4',
    totalMaintMargin='0.22',
    totalWalletBalance='1006',
    totalUnrealizedProfit='0.06',
    totalMarginBalance='1006.06',
    totalPositionInitialMargin='4.4',
    totalCrossWalletBalance='1000',
    totalCrossUnPnl='0.01',
    availableBalance='999.6',
    maxWithdrawAmount='999.6',
  )
  isolated_margin = Decimal('6.05')  # positionRisk's isolatedMargin for the row
  bucket = cross_collateral(venue)
  assert bucket == PerpCollateral(
    equity=venue['totalCrossWalletBalance'] + venue['totalCrossUnPnl'],
    free_collateral=Decimal('999.6'),
    initial_margin=Decimal('0.4'),
    maintenance_margin=Decimal('0.02'),
    leverage=Decimal(8) / Decimal('1000.01'),
    margin_mode='cross',
  )
  assert isolated_collateral(isolated) == PerpCollateral(
    equity=isolated_margin,
    free_collateral=Decimal('2.05'),
    initial_margin=Decimal(4),
    maintenance_margin=Decimal('0.2'),
    leverage=Decimal(80) / isolated_margin,
    margin_mode='isolated',
  )


def test_buckets_without_equity_report_zero_leverage():
  """Leverage is notional over positive equity, else zero, as on other venues."""
  assert cross_collateral(account(LONG, totalMarginBalance='0')).leverage == 0
  drained = position('SOLUSDT', isolated=True, notional=Decimal(10))
  assert isolated_collateral(drained).leverage == 0
  assert isolated_collateral(drained).free_collateral == 0


def perp(symbol: str = 'BTCUSDT') -> PerpMarket:
  """A mainnet perpetual over a credential-free client; requests are mocked."""
  return PerpMarket(shared=AsterMarket.new(public=True).shared, symbol=symbol)


async def test_perp_collateral_follows_the_symbols_margin_mode(
  monkeypatch: pytest.MonkeyPatch,
):
  """Cross symbols share the account bucket; isolated ones report their own."""
  isolated = position('SOLUSDT', isolated=True, isolatedWallet=Decimal(10))
  view = AsyncMock(return_value=account(LONG, isolated))
  monkeypatch.setattr(InfoWithJoinMargin, 'info_with_join_margin', view)
  cross = await perp('BTCUSDT').perp_collateral()
  assert cross.margin_mode == 'cross' and cross.equity == Decimal(990)
  own = await perp('SOLUSDT').collateral()
  assert isinstance(own, PerpCollateral)
  assert own.margin_mode == 'isolated' and own.equity == Decimal(10)
  venue = AsterMarket(shared=perp().shared)
  assert await venue.perp.perp_collateral() == cross
  assert await venue.perp.collateral() == cross


async def test_hedge_mode_and_missing_rows_are_not_guessed(
  monkeypatch: pytest.MonkeyPatch,
):
  """Hedge-mode legs raise; a symbol absent from the account view is missing data."""
  legs = account(
    position('BTCUSDT', positionSide='LONG'), position('BTCUSDT', positionSide='SHORT')
  )
  monkeypatch.setattr(
    InfoWithJoinMargin, 'info_with_join_margin', AsyncMock(return_value=legs)
  )
  with pytest.raises(NotImplementedError, match='hedge'):
    await perp().perp_collateral()
  assert (await AsterMarket(shared=perp().shared).perp.perp_collateral()).equity == 1000
  with pytest.raises(MissingData):
    await perp('ETHUSDT').perp_collateral()


def risk(leverage: int) -> list[dict[str, Any]]:
  """The `positionRisk` row `leverage()` reads."""
  return [
    {
      'symbol': 'BTCUSDT',
      'leverage': leverage,
      'marginType': 'cross',
      'positionSide': 'BOTH',
      'positionAmt': Decimal(0),
      'entryPrice': Decimal(0),
    }
  ]


@pytest.mark.parametrize(
  'available,max_notional,remaining,expected',
  [
    ('800', '1000000', '-1', '4000'),
    ('800', '2000', '-1', '800'),
    ('800', '1000000', '2500', '2500'),
    ('800', '1000', '-1', '0'),
  ],
)
async def test_available_notional_applies_bracket_and_open_interest_caps(
  available: str,
  max_notional: str,
  remaining: str,
  expected: str,
  monkeypatch: pytest.MonkeyPatch,
):
  """Free balance x leverage, the bracket's room and the symbol's remaining cap."""
  monkeypatch.setattr(Risk, 'risk', AsyncMock(return_value=risk(5)))
  row: dict[str, Any] = {**LONG, 'maxNotional': Decimal(max_notional)}
  monkeypatch.setattr(
    InfoWithJoinMargin,
    'info_with_join_margin',
    AsyncMock(return_value=account(row, availableBalance=available)),
  )
  cap = AsyncMock(return_value={'remainingOpenableNotionalValue': Decimal(remaining)})
  monkeypatch.setattr(
    RemainingOpenableNotionalValue, 'remaining_openable_notional_value', cap
  )
  assert await perp().available_notional() == Decimal(expected)
  assert cap.await_args is not None and cap.await_args.kwargs == {'leverage': 5}


def contract(symbol: str) -> dict[str, Any]:
  """A trading perpetual definition."""
  return {
    'symbol': symbol,
    'status': 'TRADING',
    'contractType': 'PERPETUAL',
    'marginAsset': 'USDT',
    'filters': [],
  }


SYMBOLS = [f'S{i}USDT' for i in range(7)]


@pytest.mark.parametrize(
  'markets,reads', [(SYMBOLS[:2], 2), (SYMBOLS[:5], 5), (SYMBOLS[:6], 0), (None, 0)]
)
async def test_perp_stats_read_open_interest_for_few_explicit_markets(
  markets: list[str] | None, reads: int, monkeypatch: pytest.MonkeyPatch
):
  """At most five named contracts get one open-interest read each; bulk stays unset."""
  monkeypatch.setattr(
    ExchangeInfoEndpoint,
    'exchange_info',
    AsyncMock(return_value={'symbols': [contract(s) for s in SYMBOLS]}),
  )
  premiums: list[Any] = [
    {
      'symbol': s,
      'markPrice': Decimal(2),
      'indexPrice': Decimal(2),
      'lastFundingRate': Decimal(0),
      'nextFundingTime': TIME,
    }
    for s in SYMBOLS
  ]
  monkeypatch.setattr(PremiumIndex, 'premium_index', AsyncMock(return_value=premiums))
  monkeypatch.setattr(FundingInfoEndpoint, 'funding_info', AsyncMock(return_value=[]))

  async def open_interest(symbol: str, **kwargs: Any) -> dict[str, Any]:
    """The native per-symbol row."""
    return {'symbol': symbol, 'openInterest': Decimal(len(symbol)), 'time': TIME}

  endpoint = AsyncMock(side_effect=open_interest)
  monkeypatch.setattr(OpenInterestEndpoint, 'open_interest', endpoint)
  stats = await AsterMarket.new(public=True).perp.perp_stats(markets)
  assert endpoint.await_count == reads
  assert len(stats) == len(markets or SYMBOLS)
  for symbol, row in stats.items():
    assert row.open_interest == (Decimal(len(symbol)) if reads else None)
  assert exchanges.OPEN_INTEREST_MARKETS == 5
