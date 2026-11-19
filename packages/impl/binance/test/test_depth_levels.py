"""`levels` is an upper bound: Binance serves at most that many, up to its fixed tiers."""

from decimal import Decimal

import pytest
from typed_binance.spot.streams.partial_depth import PartialDepth as SpotPartialDepth
from typed_binance.usdm_futures.http.market.depth import Depth as PerpDepth
from typed_binance.usdm_futures.public_streams.partial_depth import (
  PartialDepth as PerpPartialDepth,
)
from typed_core.util import Stream, StreamManager
from typing_extensions import Any, AsyncIterator

from tribulnation.binance.market.impl.mixin import Shared
from tribulnation.binance.market.perp_market import PerpMarket, rest_levels
from tribulnation.binance.market.spot_market import SpotMarket


def side(n: int, start: int, step: int) -> list[tuple[Decimal, Decimal]]:
  """`n` levels of one unit, best first."""
  return [(Decimal(start + step * i), Decimal(1)) for i in range(n)]


def install_stream(monkeypatch: pytest.MonkeyPatch, tiers: list[int]):
  """Route both `partial_depth`s to a fake serving the subscribed tier's levels."""

  def partial_depth(
    endpoint: object, symbol: str, *, levels: int, **_: Any
  ) -> StreamManager:
    """Record the tier and push one snapshot of exactly that many levels a side."""

    async def connect() -> Stream:
      """Open the fake subscription."""
      tiers.append(levels)

      async def rows() -> AsyncIterator[Any]:
        """One snapshot in both exchanges' shapes."""
        bids, asks = side(levels, 99, -1), side(levels, 101, 1)
        yield {'bids': bids, 'asks': asks, 'b': bids, 'a': asks}

      async def unsubscribe():
        """Nothing to release."""

      return Stream(None, rows(), unsubscribe)

    return StreamManager(connect=connect)

  monkeypatch.setattr(SpotPartialDepth, 'partial_depth', partial_depth)
  monkeypatch.setattr(PerpPartialDepth, 'partial_depth', partial_depth)


@pytest.mark.parametrize('cls', [SpotMarket, PerpMarket])
@pytest.mark.parametrize(
  ('levels', 'tier', 'served'), [(3, 5, 3), (7, 10, 7), (50, 20, 20), (10**6, 20, 20)]
)
async def test_stream_subscribes_smallest_tier_and_trims(
  cls: type[SpotMarket] | type[PerpMarket],
  levels: int,
  tier: int,
  served: int,
  monkeypatch: pytest.MonkeyPatch,
):
  """Above the 20-level maximum the stream serves 20; below it, exactly `levels`."""
  tiers: list[int] = []
  install_stream(monkeypatch, tiers)
  market = cls(shared=Shared.new(public=True), symbol='BTCUSDT')
  async with market.depth_stream(levels=levels) as books:
    book = await anext(aiter(books))
  assert tiers == [tier]
  assert len(book.bids) == len(book.asks) == served


def test_perp_rest_levels_cap_at_the_deepest_tier():
  """Requests above 1000 levels ask for 1000 rather than an unsupported limit."""
  assert rest_levels(3) == 5
  assert rest_levels(1000) == 1000
  assert rest_levels(1001) == rest_levels(10**6) == 1000


async def test_perp_depth_trims_the_tier_to_levels(monkeypatch: pytest.MonkeyPatch):
  """The REST tier is trimmed to `levels`, and above 1000 serves the 1000 tier."""
  limits: list[int | None] = []

  async def depth(endpoint: object, *, symbol: str, limit: int | None = None, **_: Any):
    """Answer with exactly `limit` levels a side."""
    limits.append(limit)
    n = limit or 500
    return {'bids': side(n, 99, -1), 'asks': side(n, 101, 1)}

  monkeypatch.setattr(PerpDepth, 'depth', depth)
  market = PerpMarket(shared=Shared.new(public=True), symbol='BTCUSDT')
  small = await market.depth(levels=3)
  large = await market.depth(levels=10**6)
  assert limits == [5, 1000]
  assert len(small.bids) == len(small.asks) == 3
  assert len(large.bids) == len(large.asks) == 1000
