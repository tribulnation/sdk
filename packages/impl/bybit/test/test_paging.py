"""A throttled page of a sweep must replay alone, not restart the sweep.

Every page is its own retriable `call_bybit` invocation. Fetch the pages inside one
retriable call and a `RateLimited` on page 2 of 3 re-requests page 1 as well -- more
load on the endpoint that just throttled. No live venue can be made to throttle one
page on demand.
"""

from typing_extensions import Any, cast
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from tribulnation.sdk.core import Context, RateLimited
from tribulnation.bybit.market import SpotMarket
from tribulnation.bybit.market.impl import Cache
from typed_bybit import Bybit
from typed_bybit.trade.trade_history import TradeHistoryResult

START = datetime(2025, 7, 20, tzinfo=timezone.utc)
END = datetime(2025, 7, 27, tzinfo=timezone.utc)

NEXT_PAGE: dict[str, str | None] = {'a': 'b', 'b': 'c', 'c': None}
"""Three cursor-linked pages; `c` is the last, so it carries no next cursor."""


def execution(exec_id: str) -> dict[str, Any]:
  """One spot fill, with only the fields the mapping reads."""
  return {
    'execId': exec_id,
    'execQty': Decimal('1'),
    'execPrice': Decimal('1'),
    'execTime': START,
    'side': 'Buy',
    'isMaker': True,
    'execFee': Decimal(0),
    'feeCurrency': 'USDC',
  }


@dataclass
class FakeTrade:
  """A `trade` endpoint serving three cursor-linked pages."""

  pages: list[str] = field(default_factory=list[str])
  fail_on: str = ''
  failures: int = 0

  async def trade_history(self, category: str, **kwargs: Any) -> TradeHistoryResult:
    """Serve the page named by `cursor`, failing once on `fail_on`.

    Pages are named `a`, `b` and `c`; the first request of a window carries no
    cursor at all, which is page `a`.
    """
    page = cast('str | None', kwargs.get('cursor')) or 'a'
    self.pages.append(page)
    if page == self.fail_on:
      self.fail_on = ''
      self.failures += 1
      raise RateLimited(10006, 'too many visits')
    result: dict[str, Any] = {'category': category, 'list': [execution(page)]}
    following = NEXT_PAGE[page]
    if following is not None:
      result['nextPageCursor'] = following
    return cast(TradeHistoryResult, result)


@dataclass
class FakeClient:
  """Just enough of `Bybit` for the trade-history sweep."""

  trade: FakeTrade = field(default_factory=FakeTrade)


def market(client: FakeClient) -> SpotMarket:
  """A spot market wired to a fake client."""
  return SpotMarket(client=cast(Bybit, client), cache=Cache(), symbol='BTCUSDT')


async def test_a_throttled_page_retries_in_place():
  """A throttled page 2 of 3 retries itself; pages 1 and 3 are fetched once each."""
  client = FakeClient(trade=FakeTrade(fail_on='b'))
  context = Context().retried(RateLimited, max_retries=2, base_delay=0)
  with context.use():
    trades = await market(client).trades_history(START, END)
  assert client.trade.failures == 1
  # `b` twice -- the retry -- and every other page exactly once. A sweep-level retry
  # would have restarted from the top and refetched page `a` as well.
  assert client.trade.pages == ['a', 'b', 'b', 'c']
  assert [t.id for t in trades] == ['a', 'b', 'c']
