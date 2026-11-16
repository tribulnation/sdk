"""Position headroom from open-interest caps and margin tiers, and the typed limit refusals."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from typing_extensions import Any, cast
from typed_hyperliquid import Hyperliquid

from tribulnation.hyperliquid.market.impl.mixin import PerpMarketMixin, PerpMeta, Shared
from tribulnation.hyperliquid.market.impl.orders import place_order, refusal
from tribulnation.hyperliquid.market.perps_market import PerpMarket
from tribulnation.sdk.core import (
  OpenInterestCapped,
  OrderRejected,
  PositionLimitExceeded,
)
from tribulnation.sdk.market import Order, PositionHeadroom

ADDRESS = '0x' + '1' * 40
TIERED: tuple[int, dict[str, Any]] = (
  51,
  {
    'description': 'tiered 10x',
    'marginTiers': [
      {'lowerBound': Decimal(0), 'maxLeverage': 10},
      {'lowerBound': Decimal(3000), 'maxLeverage': 5},
    ],
  },
)
"""A table whose second tier, from 3000 of notional, allows at most 5x."""


def market(
  *,
  capped: list[str],
  leverage: int = 10,
  table_id: int = 51,
  szi: str | None = None,
  value: str = '0',
  dex: str | None = None,
) -> tuple[PerpMarket, SimpleNamespace]:
  """A perpetual over a stub client, with the given caps, leverage and position."""
  coin = f'{dex}:SAGA' if dex else 'SAGA'
  asset: dict[str, Any] = {
    'name': coin,
    'maxLeverage': 10,
    'szDecimals': 1,
    'marginTableId': table_id,
  }
  positions: list[dict[str, Any]] = (
    []
    if szi is None
    else [
      {'position': {'coin': coin, 'szi': Decimal(szi), 'positionValue': Decimal(value)}}
    ]
  )
  info = SimpleNamespace(
    perps_at_open_interest_cap=AsyncMock(return_value=capped),
    perp_meta_and_asset_ctxs=AsyncMock(
      return_value=(
        {'universe': [asset], 'collateralToken': 0, 'marginTables': [TIERED]},
        [],
      )
    ),
    perp_dexs=AsyncMock(return_value=[None, {'name': dex}]),
    active_asset_data=AsyncMock(
      return_value={
        'user': ADDRESS,
        'coin': coin,
        'leverage': {'type': 'cross', 'value': leverage},
      }
    ),
    clearinghouse_state=AsyncMock(return_value={'assetPositions': positions}),
  )
  shared = Shared(
    client=cast(Hyperliquid, SimpleNamespace(info=info)), maybe_address=ADDRESS
  )
  meta = cast(
    PerpMeta, {'asset_idx': 0, 'asset_meta': asset, 'collateral_meta': {'index': 0}}
  )
  return PerpMarket(
    shared=shared, dex={'name': dex, 'idx': 1} if dex else None, meta=meta
  ), info


async def test_a_coin_at_its_open_interest_cap_has_no_headroom():
  """`perpsAtOpenInterestCap` makes the coin reduce-only: neither direction may grow."""
  m, info = market(capped=['CANTO', 'SAGA'], szi='-5', value='100')
  assert await m.position_headroom() == PositionHeadroom(
    long=Decimal(0), short=Decimal(0)
  )
  info.perps_at_open_interest_cap.assert_awaited_once_with(None)


async def test_builder_dex_coins_match_prefixed_or_not():
  """A HIP-3 dex's list is matched with or without the `dex:` prefix."""
  for listed in (['xyz:SAGA'], ['SAGA']):
    m, info = market(capped=listed, dex='xyz')
    assert await m.position_headroom() == PositionHeadroom(
      long=Decimal(0), short=Decimal(0)
    )
    info.perps_at_open_interest_cap.assert_awaited_once_with('xyz')


@pytest.mark.parametrize(
  'leverage,szi,value,expected',
  [
    (10, None, '0', PositionHeadroom(long=Decimal(3000), short=Decimal(3000))),
    (10, '2', '1000', PositionHeadroom(long=Decimal(2000), short=Decimal(3000))),
    (10, '-2', '1000', PositionHeadroom(long=Decimal(3000), short=Decimal(2000))),
    (5, '2', '1000', PositionHeadroom()),
  ],
)
async def test_margin_tier_limits_the_position_at_the_accounts_leverage(
  leverage: int, szi: str | None, value: str, expected: PositionHeadroom
):
  """At 10x the position may grow to the 5x tier's 3000; at 5x no tier binds."""
  m, _ = market(capped=['CANTO'], leverage=leverage, szi=szi, value=value)
  assert await m.position_headroom() == expected


async def test_single_tier_tables_have_no_limit():
  """Ids below 50 are single-tier tables, not listed: headroom is unknown."""
  m, _ = market(capped=[], table_id=3)
  assert await m.position_headroom() == PositionHeadroom()


@pytest.mark.parametrize(
  'error,expected',
  [
    ('Cannot increase position when open interest is at cap', OpenInterestCapped),
    (
      'Order would increase open interest while open interest is capped',
      OpenInterestCapped,
    ),
    (
      'Order rejected due to price more aggressive than oracle while at open interest cap',
      OpenInterestCapped,
    ),
    (
      'Order would cause position to exceed margin tier limit at current leverage',
      PositionLimitExceeded,
    ),
    ('Insufficient margin to place order.', OrderRejected),
  ],
)
def test_refusals_name_their_limit(error: str, expected: type[OrderRejected]):
  """Open-interest and margin-tier refusals get their own classes; others stay `OrderRejected`."""
  raised = refusal(error)
  assert type(raised) is expected and raised.args == (error,)


async def test_place_order_raises_the_typed_refusal():
  """A per-order error at the open-interest cap raises `OpenInterestCapped`."""
  error = 'Cannot increase position when open interest is at cap'
  endpoint = AsyncMock(
    return_value={
      'status': 'ok',
      'response': {'type': 'order', 'data': {'statuses': [{'error': error}]}},
    }
  )
  m = cast(
    PerpMarketMixin,
    SimpleNamespace(
      asset_id=3,
      tick_size=Decimal('0.0001'),
      client=SimpleNamespace(exchange=SimpleNamespace(order=endpoint)),
    ),
  )
  order: Order = {'qty': Decimal('1'), 'price': Decimal('10'), 'type': 'MARKET'}
  with pytest.raises(OpenInterestCapped):
    await place_order(m, order)
