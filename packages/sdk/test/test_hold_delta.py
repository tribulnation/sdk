"""Default `delta()` and `hold()` on spot and margin markets (ADR 0058)."""

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from typing_extensions import Any, cast

from tribulnation.sdk.market import (
  Balance,
  Hold,
  MarginMarket,
  Market,
  Position,
  SpotBalances,
  SpotCollateralIds,
  SpotMarket,
)

TTL = timedelta(seconds=2)


def spot_market() -> Any:
  """A spot market holding 3 base (1 of it in orders) and 50 quote."""
  return SimpleNamespace(
    balances=AsyncMock(
      return_value=SpotBalances(
        base=Balance(total=Decimal(3), free=Decimal(2)),
        quote=Balance(total=Decimal(50), free=Decimal(50)),
      )
    ),
    collateral_ids=AsyncMock(
      return_value=SpotCollateralIds(base='hl:spot:197', quote='hl:spot:0')
    ),
  )


def margin_market(size: str) -> Any:
  """A margin market with a position of `size`, at 5x, funded by `hl:spot:0`."""
  return SimpleNamespace(
    id='hl::BTC',
    position=AsyncMock(return_value=Position(size=Decimal(size))),
    collateral_id=AsyncMock(return_value='hl:spot:0'),
    leverage=AsyncMock(return_value=Decimal(5)),
  )


async def test_spot_delta_is_the_total_base_balance():
  """What open orders hold still counts: a resting sell owns its base."""
  market = spot_market()
  assert await SpotMarket.delta(market, ttl=TTL) == Decimal(3)
  market.balances.assert_awaited_once_with(ttl=TTL)


@pytest.mark.parametrize(
  ('qty', 'expected'),
  [
    ('2', Hold(collateral_id='hl:spot:0', amount=Decimal(200))),
    ('-2', Hold(collateral_id='hl:spot:197', amount=Decimal(2))),
  ],
)
async def test_spot_buy_holds_quote_and_sell_holds_base(qty: str, expected: Hold):
  """A buy holds `qty * price` of the quote, a sell `|qty|` of the base."""
  market = spot_market()
  assert await SpotMarket.hold(market, qty=Decimal(qty), price=Decimal(100)) == expected
  market.balances.assert_not_awaited()


@pytest.mark.parametrize('size', ['-1.5', '0', '1.5'])
async def test_margin_delta_is_the_position_size(size: str):
  """Signed, in base units, with the caller's `ttl`."""
  market = margin_market(size)
  assert await MarginMarket.delta(market, ttl=TTL) == Decimal(size)
  market.position.assert_awaited_once_with(ttl=TTL)


@pytest.mark.parametrize(
  ('size', 'qty', 'opening'),
  [
    ('0', '2', '2'),  # opening long from flat
    ('0', '-2', '2'),  # opening short from flat
    ('1', '2', '2'),  # growing a long
    ('-1', '-2', '2'),  # growing a short
    ('3', '-2', '0'),  # partly closing a long
    ('-3', '2', '0'),  # partly closing a short
    ('2', '-2', '0'),  # closing exactly
    ('1', '-3', '2'),  # flipping long to short through zero
    ('-1', '3', '2'),  # flipping short to long through zero
  ],
)
async def test_margin_hold_is_the_opening_part_over_leverage(
  size: str, qty: str, opening: str
):
  """`opening * price / leverage()` of `collateral_id()`; closing holds nothing."""
  market = margin_market(size)
  hold = await MarginMarket.hold(market, qty=Decimal(qty), price=Decimal(100), ttl=TTL)
  assert hold == Hold(
    collateral_id='hl:spot:0', amount=Decimal(opening) * Decimal(100) / Decimal(5)
  )
  market.position.assert_awaited_once_with(ttl=TTL)


async def test_margin_closing_hold_reads_no_leverage():
  """A closing order needs no collateral, so venues without `leverage()` answer it."""
  market = margin_market('3')
  market.leverage = AsyncMock(side_effect=NotImplementedError)
  hold = await MarginMarket.hold(market, qty=Decimal(-3), price=Decimal(100))
  assert hold == Hold(collateral_id='hl:spot:0', amount=Decimal(0))


async def test_margin_opening_hold_passes_ttl_to_leverage():
  """The same `ttl` reaches the position and leverage reads."""
  market = margin_market('0')
  await MarginMarket.hold(market, qty=Decimal(1), price=Decimal(100), ttl=TTL)
  market.leverage.assert_awaited_once_with(ttl=TTL)


def test_every_market_declares_delta_and_hold_without_abstracting_them():
  """Callers need not narrow a `Market`; unmigrated venues still instantiate."""
  for name in ('delta', 'hold'):
    assert name in vars(Market)
    assert name not in Market.__abstractmethods__
    assert name in vars(SpotMarket) and name in vars(MarginMarket)
    assert name not in SpotMarket.__abstractmethods__
    assert name not in MarginMarket.__abstractmethods__


async def test_plain_markets_raise_not_implemented():
  """A venue subclassing `Market` directly has neither balances nor a position."""
  market = SimpleNamespace(id='binance::BTCUSDT')
  with pytest.raises(NotImplementedError, match='binance::BTCUSDT'):
    await Market.delta(cast(Any, market), ttl=TTL)
  with pytest.raises(NotImplementedError, match='binance::BTCUSDT'):
    await Market.hold(cast(Any, market), qty=Decimal(1), price=Decimal(100))


def test_hold_is_frozen():
  """A hold is a value: it cannot change after it is computed."""
  hold = Hold(collateral_id='hl:spot:0', amount=Decimal(1))
  with pytest.raises(AttributeError):
    cast(Any, hold).amount = Decimal(2)
