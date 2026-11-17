"""`PositionHeadroom.capped` and the `MarginMarket.position_headroom` default."""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from typing_extensions import Any, cast

from tribulnation.sdk.market import PerpMarket, PositionHeadroom, SpotMarket

D = Decimal


@pytest.mark.parametrize(
  'max_notional,position,remaining,expected',
  [
    (D(1000), D(0), None, PositionHeadroom(long=D(1000), short=D(1000))),
    (D(1000), D(400), None, PositionHeadroom(long=D(600), short=D(1000))),
    (D(1000), D(-400), None, PositionHeadroom(long=D(1000), short=D(600))),
    (D(1000), D(1200), None, PositionHeadroom(long=D(0), short=D(1000))),
    (D(1000), D(400), D(300), PositionHeadroom(long=D(300), short=D(300))),
    (None, D(400), D(300), PositionHeadroom(long=D(300), short=D(300))),
    (None, D(400), None, PositionHeadroom()),
  ],
)
def test_capped(
  max_notional: Decimal | None,
  position: Decimal,
  remaining: Decimal | None,
  expected: PositionHeadroom,
):
  """Each direction gets the cap less what it holds, bounded by the remaining allowance, floored at 0."""
  assert (
    PositionHeadroom.capped(
      max_notional=max_notional, position=position, remaining=remaining
    )
    == expected
  )


async def test_margin_default_knows_no_limits():
  """Venues that publish no limits answer `None` both ways: unknown, treated as unlimited."""
  market = SimpleNamespace(id='x:perp:BTC')
  assert await PerpMarket.position_headroom(cast(Any, market)) == PositionHeadroom()


def test_spot_markets_have_no_headroom():
  """Spot sizes on `balances()`: position limits are a margin concept."""
  assert not hasattr(SpotMarket, 'position_headroom')
