"""Offline mapping tests: venue rows (already validated by `typed_margintrade`) to SDK
types, with the client's methods replaced by fakes."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

from typing_extensions import Any

import pytest
from tribulnation.sdk.core import ApiError
from tribulnation.sdk.market import ExchangeTrade

from tribulnation.margintrade import MarginTradeMarket
from tribulnation.margintrade.market.history import FILLS_CAP

USER = 'TestAccount1111111111111111111111111111111'
T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
D = Decimal


def meta() -> dict[str, Any]:
  """A two-market universe."""
  return {
    'universe': [
      {
        'name': 'BTC',
        'index': 0,
        'szDecimals': 5,
        'maxLeverage': 20,
        'category': 'Crypto',
        'takerFee': D('0.0005'),
        'makerFee': D('0.0001'),
      },
      {
        'name': 'PRL',
        'index': 8,
        'szDecimals': 2,
        'maxLeverage': 3,
        'category': 'Crypto',
        'takerFee': D('0.001'),
        'makerFee': D('-0.0002'),
      },
    ],
    'marginTables': [],
  }


def fill(
  coin: str, minutes: int, *, side: str = 'B', taker: bool = True, tid: int = 1
) -> dict[str, Any]:
  """One validated fill row."""
  return {
    'coin': coin,
    'px': D('100'),
    'sz': D('2'),
    'side': side,
    'time': T0 + timedelta(minutes=minutes),
    'startPosition': D(0),
    'dir': 'Open Long',
    'closedPnl': D(0),
    'oid': 7,
    'tid': tid,
    'crossed': True,
    'isTaker': taker,
    'fee': D('-0.01'),
    'feeToken': 'USD',
  }


def state(*, leverage_type: str = 'cross') -> dict[str, Any]:
  """A clearinghouse state with one BTC position."""
  return {
    'assetPositions': [
      {
        'type': 'oneWay',
        'position': {
          'coin': 'BTC',
          'szi': D('-0.5'),
          'entryPx': D('60000'),
          'positionValue': D('30000'),
          'unrealizedPnl': D('100'),
          'returnOnEquity': D(0),
          'liquidationPx': None,
          'marginUsed': D('1500'),
          'maxLeverage': 20,
          'leverage': {'type': leverage_type, 'value': 20, 'rawUsd': D('1400')},
          'cumFunding': {'allTime': D(0), 'sinceOpen': D(0), 'sinceChange': D(0)},
        },
      }
    ],
    'crossMaintenanceMarginUsed': D('750'),
    'crossMarginSummary': {
      'accountValue': D('10000'),
      'totalNtlPos': D('30000'),
      'totalRawUsd': D('10000'),
      'totalMarginUsed': D('1500'),
    },
    'marginSummary': {
      'accountValue': D('10000'),
      'totalNtlPos': D('30000'),
      'totalRawUsd': D('10000'),
      'totalMarginUsed': D('1500'),
    },
    'time': T0,
    'withdrawable': D('8500'),
  }


@pytest.fixture
def venue():
  """A venue for `USER` whose client calls are fakes."""
  venue = MarginTradeMarket.new(USER, public=True)
  venue.shared.client.info.meta = AsyncMock(return_value=meta())
  return venue


async def test_rules(venue: MarginTradeMarket):
  """Steps from `szDecimals`, the band from `maxLeverage`, fees from the market."""
  rules = await (await venue.perp_market('perp:BTC')).rules()
  assert (rules.tick_size, rules.step_size, rules.fee_asset) == (
    D('0.1'),
    D('0.00001'),
    'USDC',
  )
  assert (rules.rel_min_price, rules.rel_max_price) == (D('0.975'), D('1.025'))
  assert rules.fees is not None and (rules.fees.taker_buy, rules.fees.maker_sell) == (
    D('0.0005'),
    D('0.0001'),
  )
  prl = await (await venue.perp_market('perp:PRL')).rules()
  assert prl.tick_size == D('0.0001')
  assert prl.rel_min_price is not None and abs(prl.rel_min_price - (1 - D(1) / 6)) < D(
    '1e-20'
  )


async def test_unknown_market(venue: MarginTradeMarket):
  """A coin outside the universe raises."""
  with pytest.raises(ValueError):
    await venue.perp_market('perp:DOGE')


async def test_trades_history_filters_and_signs(venue: MarginTradeMarket):
  """Only perpetual fills of the market within the range; `isTaker` decides the role."""
  rows = [
    fill('BTC', 50, side='A', taker=False, tid=3),
    fill('PRL/USDC', 40),
    fill('PRL', 30),
    fill('BTC', 20, tid=2),
    fill('BTC', -5),
  ]
  venue.shared.client.info.user_fills_by_time = AsyncMock(return_value=rows)
  market = await venue.perp_market('perp:BTC')
  trades = await market.trades_history(T0, T0 + timedelta(hours=1))
  assert [(t.id, t.qty, t.maker) for t in trades] == [
    ('3', D('-2'), True),
    ('2', D('2'), False),
  ]
  assert trades[0].fee is not None and (trades[0].fee.amount, trades[0].fee.asset) == (
    D('-0.01'),
    'USDC',
  )
  exchange = await venue.perp_exchange('perp')
  everything = await exchange.trades_history(None, T0, T0 + timedelta(hours=1))
  assert [t.market_id for t in everything if isinstance(t, ExchangeTrade)] == [
    'BTC',
    'PRL',
    'BTC',
  ]


async def test_trades_history_refuses_a_truncated_range(venue: MarginTradeMarket):
  """A full response whose oldest fill is after `start` cut older fills off."""
  rows = [fill('BTC', 60 - n // 1000) for n in range(FILLS_CAP)]
  venue.shared.client.info.user_fills_by_time = AsyncMock(return_value=rows)
  market = await venue.perp_market('perp:BTC')
  with pytest.raises(ApiError):
    await market.trades_history(T0, T0 + timedelta(hours=2))


async def test_funding_payments(venue: MarginTradeMarket):
  """Received-positive amounts, per market or exchange-wide."""
  rows: list[dict[str, Any]] = [
    {
      'time': T0,
      'hash': 'x',
      'delta': {
        'type': 'funding',
        'coin': 'BTC',
        'usdc': D('-1.5'),
        'szi': D('1'),
        'fundingRate': D('0.0001'),
      },
    },
    {
      'time': T0,
      'hash': 'y',
      'delta': {
        'type': 'funding',
        'coin': 'PRL',
        'usdc': D('0.2'),
        'szi': D('-5'),
        'fundingRate': D('0.0001'),
      },
    },
  ]
  venue.shared.client.info.user_funding = AsyncMock(return_value=rows)
  market = await venue.perp_market('perp:BTC')
  payments = await market.funding_payments(T0, T0)
  assert [p.amount for p in payments] == [D('-1.5')]
  exchange = await venue.perp_exchange('perp')
  everything = await exchange.funding_payments(None, T0, T0)
  assert [(p.market_id, p.amount) for p in everything] == [
    ('BTC', D('-1.5')),
    ('PRL', D('0.2')),
  ]


async def test_position_and_cross_collateral(venue: MarginTradeMarket):
  """The signed size, and cross collateral from the account summary."""
  venue.shared.client.info.clearinghouse_state = AsyncMock(return_value=state())
  market = await venue.perp_market('perp:BTC')
  position = await market.perp_position()
  assert (position.size, position.entry_price) == (D('-0.5'), D('60000'))
  collateral = await market.perp_collateral()
  assert (collateral.margin_mode, collateral.equity, collateral.free_collateral) == (
    'cross',
    D('10000'),
    D('8500'),
  )
  assert (collateral.maintenance_margin, collateral.leverage) == (D('750'), D('3'))
  flat = await (await venue.perp_market('perp:PRL')).perp_position()
  assert flat.size == 0


async def test_isolated_collateral(venue: MarginTradeMarket):
  """An isolated position reports its own bucket, maintenance at notional / (2 * maxLeverage)."""
  venue.shared.client.info.clearinghouse_state = AsyncMock(
    return_value=state(leverage_type='isolated')
  )
  collateral = await (await venue.perp_market('perp:BTC')).perp_collateral()
  assert (collateral.margin_mode, collateral.equity, collateral.maintenance_margin) == (
    'isolated',
    D('1500'),
    D('750'),
  )


async def test_open_orders_and_query(venue: MarginTradeMarket):
  """Open orders of this market; a looked-up order of another market is not returned."""
  order: dict[str, Any] = {
    'coin': 'BTC',
    'side': 'A',
    'limitPx': D('61000'),
    'sz': D('0.3'),
    'oid': 11,
    'timestamp': T0,
    'origSz': D('0.5'),
    'orderType': 'Limit',
    'reduceOnly': False,
    'isTrigger': False,
    'isPositionTpsl': False,
    'triggerCondition': 'N/A',
    'triggerPx': None,
  }
  venue.shared.client.info.frontend_open_orders = AsyncMock(
    return_value=[order, {**order, 'coin': 'PRL'}]
  )
  market = await venue.perp_market('perp:BTC')
  [state_] = await market.open_orders()
  assert (state_.id, state_.qty, state_.filled_qty, state_.active) == (
    '11',
    D('-0.5'),
    D('-0.2'),
    True,
  )
  found: dict[str, Any] = {
    'status': 'order',
    'order': {
      'order': {
        **order,
        'children': [],
        'tif': 'Gtc',
        'cloid': None,
        'fillPx': None,
        'limitPx': None,
      },
      'status': 'filled',
      'statusTimestamp': T0,
    },
  }
  venue.shared.client.info.order_status = AsyncMock(return_value=found)
  result = await market.query_order('11')
  assert result is not None and (result.price, result.active) == (D(0), False)
  assert await (await venue.perp_market('perp:PRL')).query_order('11') is None


async def test_candles_drop_the_inclusive_upper_bound(venue: MarginTradeMarket):
  """The venue includes the candle opening at `end`; the SDK range excludes it."""
  rows: list[dict[str, Any]] = [
    {
      't': T0 + timedelta(hours=h),
      'T': T0 + timedelta(hours=h + 1),
      's': 'BTC',
      'i': '1h',
      'o': D(1),
      'c': D(2),
      'h': D(3),
      'l': D(0),
      'v': D(5),
      'n': 4,
    }
    for h in range(3)
  ]
  venue.shared.client.info.candle_snapshot = AsyncMock(return_value=rows)
  market = await venue.perp_market('perp:BTC')
  candles = await market.candles('1h', T0, T0 + timedelta(hours=2))
  assert [c.time for c in candles] == [T0, T0 + timedelta(hours=1)]
  assert candles[0].trades == 4


async def test_unsupported_methods(venue: MarginTradeMarket):
  """Trading and the unverified surfaces raise `NotImplementedError`."""
  market = await venue.perp_market('perp:BTC')
  with pytest.raises(NotImplementedError):
    await market.place_order({'qty': '1', 'price': '1', 'type': 'LIMIT'})
  with pytest.raises(NotImplementedError):
    await market.cancel_order('1')
  with pytest.raises(NotImplementedError):
    market.funding_rates()
