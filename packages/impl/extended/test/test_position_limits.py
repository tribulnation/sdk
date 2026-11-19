"""`remaining_position_limit` from the margin schedule at the account's leverage, the
market's `maxPositionValue` and its `openInterestLimit` (mainnet OP-USD's schedule,
2026-11-17)."""

import asyncio
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from typing_extensions import Any, cast

from tribulnation.extended.market.account import (
  leverage_cap,
  open_interest_room,
  remaining_position_limit,
)
from typed_extended import Extended
from tribulnation.extended.core import Shared
from tribulnation.extended.market.markets import ExtendedPerpMarket
from tribulnation.sdk.market import POSITION_LIMIT_TTL, RemainingPositionLimit

D = Decimal


def market(*, open_interest: str = '21332.87', limit: str | None = '5000000') -> Any:
  """OP-USD's row: brackets of 25x to 500k, 12.5x to 1.5M and 1x beyond, the last
  closed to users; position value capped at 2.5M."""
  config: dict[str, Any] = {
    'maxPositionValue': D('2500000'),
    'riskFactorConfig': [
      {'upperBound': D('500000'), 'riskFactor': D('0.04'), 'isAvailableForUsers': True},
      {
        'upperBound': D('1500000'),
        'riskFactor': D('0.08'),
        'isAvailableForUsers': True,
      },
      {'upperBound': D('2500000'), 'riskFactor': D('0.1')},
      {
        'upperBound': D('1000000000'),
        'riskFactor': D('1'),
        'isAvailableForUsers': False,
      },
    ],
  }
  if limit is not None:
    config['openInterestLimit'] = D(limit)
  return {
    'name': 'OP-USD',
    'tradingConfig': config,
    'marketStats': {'openInterest': D(open_interest), 'markPrice': D('0.0757')},
  }


def position(side: str, value: str, name: str = 'OP-USD') -> Any:
  """A positions row: `value` is absolute, beside `side`."""
  return {'market': name, 'side': side, 'value': D(value), 'size': D(1)}


@pytest.mark.parametrize(
  'leverage,cap',
  [
    (D(25), D('500000')),
    (D(20), D('500000')),
    (D('12.5'), D('1500000')),
    (D(10), D('2500000')),
    (D(1), D('2500000')),
    (D(50), D(0)),
  ],
)
def test_leverage_cap_is_the_highest_bracket_allowing_it(
  leverage: Decimal, cap: Decimal
):
  """Lower leverage reaches higher brackets, never past `maxPositionValue` or into a
  bracket closed to users; leverage above every bracket allows nothing."""
  assert leverage_cap(market(), leverage=leverage) == cap


def test_open_interest_room():
  """The limit less open interest, floored at 0; `0` or absent is unlimited."""
  assert open_interest_room(market()) == D('4978667.13')
  assert open_interest_room(market(open_interest='5000001')) == 0
  assert open_interest_room(market(limit='0')) is None
  assert open_interest_room(market(limit=None)) is None


@pytest.mark.parametrize(
  'rows,expected',
  [
    ([], RemainingPositionLimit(long=D('500000'), short=D('500000'))),
    (
      [position('LONG', '120000')],
      RemainingPositionLimit(long=D('380000'), short=D('500000')),
    ),
    (
      [position('SHORT', '120000')],
      RemainingPositionLimit(long=D('500000'), short=D('380000')),
    ),
    (
      [position('LONG', '900000', 'BTC-USD')],
      RemainingPositionLimit(long=D('500000'), short=D('500000')),
    ),
  ],
)
def test_room_per_direction_at_25x(rows: list[Any], expected: RemainingPositionLimit):
  """Each direction has the cap less what it holds; other markets' positions don't count."""
  assert remaining_position_limit(market(), rows, leverage=D(25)) == expected


def test_open_interest_bounds_both_directions():
  """Near the limit, its room binds either direction: a new position on either side
  can raise open interest."""
  m = market(open_interest='4900000')
  assert remaining_position_limit(
    m, [position('LONG', '120000')], leverage=D(25)
  ) == RemainingPositionLimit(long=D('100000'), short=D('100000'))


def test_at_the_open_interest_limit_nothing_grows():
  """At the limit the market is reduce-only: zero both ways."""
  m = cast(Any, market(open_interest='5000000'))
  assert remaining_position_limit(m, [], leverage=D(5)) == RemainingPositionLimit(
    long=D(0), short=D(0)
  )


def perp_row(name: str) -> Any:
  """OP-USD's row under another name, as the all-market read lists it."""
  return {**market(), 'name': name, 'type': 'PERPETUAL'}


async def test_every_market_shares_three_reads_per_ttl(monkeypatch: pytest.MonkeyPatch):
  """Every market's limit comes from one all-market `markets`, `positions` and
  `leverage` request each, shared for the default `ttl`; past it, they are read again."""
  now = [1000.0]
  monkeypatch.setattr(asyncio.get_running_loop(), 'time', lambda: now[0])
  names = [f'M{i:02d}-USD' for i in range(22)]
  client = SimpleNamespace(
    info=SimpleNamespace(markets=AsyncMock(return_value=[perp_row(n) for n in names])),
    account=SimpleNamespace(
      positions=AsyncMock(return_value=[position('SHORT', '100000', names[0])]),
      leverage=AsyncMock(
        return_value=[{'market': n, 'leverage': D('12.5')} for n in names]
      ),
    ),
  )
  shared = Shared(client=cast(Extended, client))
  perps = [ExtendedPerpMarket(shared=shared, name=n) for n in names]
  limits = await asyncio.gather(*(m.remaining_position_limit() for m in perps))
  assert limits[0] == RemainingPositionLimit(long=D('1500000'), short=D('1400000'))
  assert limits[1] == RemainingPositionLimit(long=D('1500000'), short=D('1500000'))
  for m in perps:
    now[0] += 1
    await m.remaining_position_limit()
  endpoints = [client.info.markets, client.account.positions, client.account.leverage]
  assert [e.await_count for e in endpoints] == [1, 1, 1]
  for e in endpoints:
    e.assert_awaited_with()
  now[0] += POSITION_LIMIT_TTL.total_seconds()
  await asyncio.gather(*(m.remaining_position_limit() for m in perps))
  assert [e.await_count for e in endpoints] == [2, 2, 2]
