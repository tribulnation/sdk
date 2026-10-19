"""Binance partial-depth streams keep only the newest snapshot for latest-only callers."""

from decimal import Decimal

import pytest
from typed_binance.spot.streams.partial_depth import PartialDepth as SpotPartialDepth
from typed_binance.usdm_futures.public_streams.partial_depth import (
  PartialDepth as PerpPartialDepth,
)
from typed_core.util import Stream, StreamManager
from typing_extensions import Any, AsyncIterator, Literal

from tribulnation.binance.market.impl.mixin import Shared
from tribulnation.binance.market.perp_market import PerpMarket
from tribulnation.binance.market.spot_market import SpotMarket
from tribulnation.sdk.core import OverflowPolicy, skipped

Scope = Literal['spot', 'perp']


class Feeds:
  """Fake partial-depth subscriptions, recording each one's `keep_latest` flag."""

  def __init__(self):
    self.keep_latest: list[bool] = []

  def install(self, monkeypatch: pytest.MonkeyPatch):
    """Route both exchanges' `partial_depth` to this fake."""

    def partial_depth(
      endpoint: object, symbol: str, *, keep_latest: bool = False, **_: Any
    ) -> StreamManager:
      """Replace the typed `partial_depth`."""
      return self.subscribe(keep_latest=keep_latest)

    monkeypatch.setattr(SpotPartialDepth, 'partial_depth', partial_depth)
    monkeypatch.setattr(PerpPartialDepth, 'partial_depth', partial_depth)

  def subscribe(self, *, keep_latest: bool) -> StreamManager:
    """Push one snapshot, pretending 4 older ones were dropped unread."""
    skips = 0

    async def connect() -> Stream:
      """Open the fake subscription."""
      self.keep_latest.append(keep_latest)

      async def rows() -> AsyncIterator[Any]:
        """Yield one snapshot in both exchanges' shapes."""
        nonlocal skips
        skips = 4
        level = [(Decimal(100), Decimal(1))]
        yield {'bids': level, 'asks': level, 'b': level, 'a': level}

      async def unsubscribe():
        """Nothing to release."""

      return Stream(None, rows(), unsubscribe, skipped_count=lambda: skips)

    return StreamManager(connect=connect)


def market(scope: Scope) -> SpotMarket | PerpMarket:
  """A market over a public client, without catalogue requests."""
  shared = Shared.new(public=True)
  cls = SpotMarket if scope == 'spot' else PerpMarket
  return cls(shared=shared, symbol='BTCUSDT')


@pytest.mark.parametrize('scope', ['spot', 'perp'])
@pytest.mark.parametrize(
  ('queue_size', 'overflow', 'keep_latest'),
  [(1, 'latest', True), (5, 'latest', False), (100, 'fail', False)],
)
async def test_keep_latest_only_for_latest_only_callers(
  scope: Scope,
  queue_size: int,
  overflow: OverflowPolicy,
  keep_latest: bool,
  monkeypatch: pytest.MonkeyPatch,
):
  """Only the default newest-book delivery conflates the typed subscription."""
  feeds = Feeds()
  feeds.install(monkeypatch)
  stream = market(scope).depth_stream(queue_size=queue_size, overflow=overflow)
  async with stream as books:
    book = await anext(aiter(books))
  assert feeds.keep_latest == [keep_latest]
  assert book.best_bid.price == Decimal(100)


@pytest.mark.parametrize('scope', ['spot', 'perp'])
async def test_skipped_reports_typed_skips(
  scope: Scope, monkeypatch: pytest.MonkeyPatch
):
  """The yielded stream reports the typed subscription's skipped frames."""
  Feeds().install(monkeypatch)
  async with market(scope).depth_stream() as books:
    assert skipped(books) == 0
    await anext(aiter(books))
    assert skipped(books) == 4
