"""Order expiry settings: absolute values are sent as is, deltas read the chain tip."""

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing_extensions import Any, cast
from unittest.mock import AsyncMock

import pydantic
import pytest

from typed_dydx.node.orders.types import Flags
from typed_dydx.protos.dydxprotocol import clob

from tribulnation.dydx.market.impl.mixin import MarketMixin
from tribulnation.dydx.market.impl.mixin import Settings as DydxSettings
from tribulnation.dydx.market.impl.orders import place_order
from tribulnation.sdk.market import Order, Settings

ORDER: Order = {'type': 'LIMIT', 'qty': Decimal('1'), 'price': Decimal('100')}
TIP_HEIGHT = 1_000
TIP_TIME = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)


def fake_market() -> tuple[MarketMixin, AsyncMock, AsyncMock]:
  """A market over mocked node and chain clients, with the mocks to inspect."""
  place = AsyncMock(
    return_value=SimpleNamespace(order=SimpleNamespace(order_id=clob.OrderId()))
  )
  latest = AsyncMock(
    return_value=SimpleNamespace(
      block=SimpleNamespace(header=SimpleNamespace(height=TIP_HEIGHT, time=TIP_TIME))
    )
  )
  market = SimpleNamespace(
    client=SimpleNamespace(
      node=SimpleNamespace(place_order=place),
      chain=SimpleNamespace(tendermint=SimpleNamespace(get_latest_block=latest)),
    ),
    perpetual_market=object(),
    subaccount=0,
  )
  return cast(MarketMixin, market), place, latest


async def placed(settings: DydxSettings) -> tuple[dict[str, Any], AsyncMock]:
  """Place `ORDER` with dYdX settings; the order params sent and the tip mock."""
  market, place, latest = fake_market()
  await place_order(market, ORDER, settings={'dydx': settings})
  assert place.await_args is not None
  return place.await_args.kwargs['order'], latest


async def test_absolute_good_til_block_is_sent_without_reading_the_tip():
  order, latest = await placed({'flags': 'SHORT_TERM', 'good_til_block': 12_345})

  assert order['good_til_block'] == 12_345
  latest.assert_not_awaited()


@pytest.mark.parametrize('flags', ['LONG_TERM', 'CONDITIONAL'])
async def test_absolute_good_til_block_time_is_sent_without_reading_the_tip(flags: Flags):
  expiry = datetime(2026, 10, 17, 12, 5, 30, 900_000, tzinfo=timezone.utc)

  order, latest = await placed({'flags': flags, 'good_til_block_time': expiry})

  assert order['good_til_block_time'] == int(expiry.timestamp())
  latest.assert_not_awaited()


async def test_short_term_delta_still_reads_the_tip():
  order, latest = await placed({'flags': 'SHORT_TERM', 'short_term_gtb': 5})

  assert order['good_til_block'] == TIP_HEIGHT + 5
  latest.assert_awaited_once()


async def test_long_term_delta_still_reads_the_tip():
  order, latest = await placed({'flags': 'LONG_TERM', 'long_term_gtbt': 60})

  assert order['good_til_block_time'] == int(TIP_TIME.timestamp()) + 60
  latest.assert_awaited_once()


async def test_no_expiry_settings_leave_the_default_to_the_client():
  order, latest = await placed({})

  assert 'good_til_block' not in order
  assert 'good_til_block_time' not in order
  latest.assert_not_awaited()


@pytest.mark.parametrize(
  'settings',
  [
    {'flags': 'SHORT_TERM', 'good_til_block': 1, 'short_term_gtb': 5},
    {'flags': 'LONG_TERM', 'good_til_block_time': TIP_TIME, 'long_term_gtbt': 60},
    {'flags': 'LONG_TERM', 'good_til_block': 1},
    {'flags': 'CONDITIONAL', 'good_til_block': 1},
    {'flags': 'SHORT_TERM', 'good_til_block_time': TIP_TIME},
  ],
)
async def test_invalid_expiry_combinations_are_rejected(settings: dict[str, Any]):
  market, place, latest = fake_market()

  with pytest.raises(ValueError, match='dYdX settings'):
    await place_order(market, ORDER, settings=cast(Settings, {'dydx': settings}))
  place.assert_not_awaited()
  latest.assert_not_awaited()


async def test_naive_good_til_block_time_is_rejected():
  market, place, _ = fake_market()
  naive = datetime(2026, 10, 17, 12, 5)

  with pytest.raises(pydantic.ValidationError):
    await place_order(
      market,
      ORDER,
      settings=cast(Settings, {'dydx': {'good_til_block_time': naive}}),
    )
  place.assert_not_awaited()
