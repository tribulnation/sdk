"""`RemainingPositionLimit.capped` and the `MarginMarket.remaining_position_limit` default."""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from typing_extensions import Any, cast

from tribulnation.sdk.market import PerpMarket, RemainingPositionLimit, SpotMarket

D = Decimal


@pytest.mark.parametrize(
  'max_notional,position,remaining,expected',
  [
    (D(1000), D(0), None, RemainingPositionLimit(long=D(1000), short=D(1000))),
    (D(1000), D(400), None, RemainingPositionLimit(long=D(600), short=D(1000))),
    (D(1000), D(-400), None, RemainingPositionLimit(long=D(1000), short=D(600))),
    (D(1000), D(1200), None, RemainingPositionLimit(long=D(0), short=D(1000))),
    (D(1000), D(400), D(300), RemainingPositionLimit(long=D(300), short=D(300))),
    (None, D(400), D(300), RemainingPositionLimit(long=D(300), short=D(300))),
    (None, D(400), None, RemainingPositionLimit()),
  ],
)
def test_capped(
  max_notional: Decimal | None,
  position: Decimal,
  remaining: Decimal | None,
  expected: RemainingPositionLimit,
):
  """Each direction gets the cap less what it holds, bounded by the remaining allowance, floored at 0."""
  assert (
    RemainingPositionLimit.capped(
      max_notional=max_notional, position=position, remaining=remaining
    )
    == expected
  )


async def test_margin_default_knows_no_limits():
  """Venues that publish no limits answer `None` both ways: unknown, treated as unlimited."""
  market = SimpleNamespace(id='x:perp:BTC')
  assert (
    await PerpMarket.remaining_position_limit(cast(Any, market))
    == RemainingPositionLimit()
  )


def test_spot_markets_have_no_position_limit():
  """Spot sizes on `balances()`: position limits are a margin concept."""
  assert not hasattr(SpotMarket, 'remaining_position_limit')
