"""Account reads and `market_stats` snapshots shared between markets and concurrent callers."""

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from decimal import Decimal
import asyncio

from typing_extensions import Any, AsyncIterator, cast
from typed_lighter import Lighter

from tribulnation.lighter.core import Shared
from tribulnation.lighter.market import stats
from tribulnation.lighter.market.markets import LighterPerpMarket

ACCOUNT = 7


def market_stats(market_id: int) -> dict[str, Any]:
  """One perp's `market_stats` row, with the fields tickers read."""
  return {
    'market_id': market_id,
    'last_trade_price': Decimal('1.5'),
    'best_bid_price': Decimal('1.4'),
    'best_ask_price': Decimal('1.6'),
    'daily_base_token_volume': 10,
    'daily_quote_token_volume': 15,
  }


@dataclass
class Streams:
  """`market_stats` that refuses a second subscription to an open channel, as the connection does."""

  open: set[str] = field(default_factory=set[str])
  subscriptions: int = 0

  @asynccontextmanager
  async def market_stats(self, selector: Any) -> AsyncIterator[AsyncIterator[Any]]:
    """Subscribe, yield the snapshot frame after a pause, then unsubscribe."""
    channel = f'market_stats/{selector}'
    if channel in self.open:
      raise RuntimeError(f'Already subscribed to channel "{channel}"')
    self.open.add(channel)
    self.subscriptions += 1

    async def frames() -> AsyncIterator[Any]:
      """The subscribe snapshot."""
      await asyncio.sleep(0.01)
      yield {'market_stats': {'33': market_stats(33), '53': market_stats(53)}}

    try:
      yield frames()
    finally:
      self.open.discard(channel)


@dataclass
class AccountApi:
  """`/account` by index, counting requests."""

  requests: int = 0

  async def get(self, request: dict[str, Any]) -> dict[str, Any]:
    """The account, after a pause so concurrent readers overlap."""
    self.requests += 1
    await asyncio.sleep(0.01)
    position: dict[str, Any] = {
      'market_id': 33,
      'sign': -1,
      'position': Decimal('2'),
      'avg_entry_price': Decimal('1.5'),
    }
    return {'accounts': [{'index': request['value'], 'positions': [position]}]}


@dataclass
class Api:
  """The REST API the reads reach."""

  account: AccountApi = field(default_factory=AccountApi)


@dataclass
class Client:
  """The client attributes the reads reach."""

  streams: Streams = field(default_factory=Streams)
  api: Api = field(default_factory=Api)
  account_index: int | None = ACCOUNT


def shared() -> tuple[Shared, Client]:
  """Shared state over a fake client."""
  client = Client()
  return Shared(client=cast(Lighter, client)), client


async def test_concurrent_tickers_share_one_subscription():
  """Readers of the same snapshot no longer subscribe twice ("Already subscribed")."""
  s, client = shared()
  results = await asyncio.gather(
    *(stats.perp_tickers(s, ['33']) for _ in range(4)), stats.perp_tickers(s, None)
  )
  assert [set(r) for r in results] == [{'33'}] * 4 + [{'33', '53'}]
  assert results[0]['33'].quote_volume_24h == 15
  assert client.streams.subscriptions == 1
  await stats.perp_tickers(s, ['53'])
  assert client.streams.subscriptions == 1


def position_of(acct: dict[str, Any], market: int) -> tuple[int, int]:
  """Which account and market a position was read from."""
  return acct['index'], market


async def test_markets_share_one_account_read(monkeypatch: Any):
  """Every market's position comes from one `/account` request per burst."""
  s, client = shared()
  monkeypatch.setattr('tribulnation.lighter.market.account.perp_position', position_of)
  markets = [LighterPerpMarket(shared=s, market_index=m) for m in (33, 53, 33)]
  positions = await asyncio.gather(*(m.perp_position() for m in markets))
  assert positions == [(ACCOUNT, 33), (ACCOUNT, 53), (ACCOUNT, 33)]
  assert client.api.account.requests == 1
