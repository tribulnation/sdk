"""Account reads and `market_stats` snapshots shared between markets and concurrent callers."""

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
import asyncio

from typing_extensions import Any, AsyncIterator, cast
from typed_core.util import Stream, StreamManager
from typed_lighter import Lighter

from tribulnation.lighter.core import Shared
from tribulnation.lighter.market import stats
from tribulnation.lighter.market.markets import LighterPerpMarket
from tribulnation.sdk.market import RemainingPositionLimit

ACCOUNT = 7
SECOND = timedelta(seconds=1)


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

  def market_stats(self, selector: Any) -> StreamManager[Any, Any, Any]:
    """Subscribe, yield the snapshot frame after a pause, then unsubscribe."""
    channel = f'market_stats/{selector}'

    async def connect() -> Stream[Any, Any, Any]:
      """Open the channel, refusing a second subscription."""
      if channel in self.open:
        raise RuntimeError(f'Already subscribed to channel "{channel}"')
      self.open.add(channel)
      self.subscriptions += 1

      async def frames() -> AsyncIterator[Any]:
        """The subscribe snapshot."""
        await asyncio.sleep(0.01)
        yield {'market_stats': {'33': market_stats(33), '53': market_stats(53)}}

      async def unsubscribe():
        """Close the channel."""
        self.open.discard(channel)

      return Stream(None, frames(), unsubscribe)

    return StreamManager(connect)


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
  """Readers of the same snapshot never subscribe twice ("Already subscribed"), even fresh ones."""
  s, client = shared()
  results = await asyncio.gather(
    *(stats.perp_tickers(s, ['33'], ttl=None) for _ in range(4)),
    stats.perp_tickers(s, None, ttl=SECOND),
  )
  assert [set(r) for r in results] == [{'33'}] * 4 + [{'33', '53'}]
  assert results[0]['33'].quote_volume_24h == 15
  assert client.streams.subscriptions == 1


async def test_a_stored_snapshot_serves_callers_with_a_ttl_only():
  """A `ttl` reuses the stored snapshot; `None` subscribes again once none is in flight."""
  s, client = shared()
  await stats.perp_tickers(s, ['33'], ttl=None)
  await stats.perp_tickers(s, ['53'], ttl=timedelta(seconds=5))
  assert client.streams.subscriptions == 1
  await stats.perp_tickers(s, ['53'], ttl=None)
  assert client.streams.subscriptions == 2


def position_of(acct: dict[str, Any], market: int) -> tuple[int, int]:
  """Which account and market a position was read from."""
  return acct['index'], market


async def test_markets_share_one_account_read(monkeypatch: Any):
  """Every market's position comes from one `/account` request per burst of shared reads."""
  s, client = shared()
  monkeypatch.setattr('tribulnation.lighter.market.account.perp_position', position_of)
  markets = [LighterPerpMarket(shared=s, market_index=m) for m in (33, 53, 33)]
  positions = await asyncio.gather(*(m.perp_position(ttl=SECOND) for m in markets))
  assert positions == [(ACCOUNT, 33), (ACCOUNT, 53), (ACCOUNT, 33)]
  assert client.api.account.requests == 1
  await markets[1].perp_position(ttl=SECOND)
  assert client.api.account.requests == 1


async def test_fresh_account_reads_are_not_shared(monkeypatch: Any):
  """Each `ttl=None` read sends its own request; a shared reader joins one in flight."""
  s, client = shared()
  monkeypatch.setattr('tribulnation.lighter.market.account.perp_position', position_of)
  market = LighterPerpMarket(shared=s, market_index=33)
  await asyncio.gather(market.perp_position(), market.perp_position())
  assert client.api.account.requests == 2
  await asyncio.gather(market.perp_position(), market.perp_position(ttl=timedelta(0)))
  assert client.api.account.requests == 3
  await market.perp_position(ttl=timedelta(minutes=1))
  assert client.api.account.requests == 3


async def test_remaining_position_limit_reads_the_market_snapshot():
  """The market's `market_stats` row gives the open-interest room both ways: the raw
  6-decimal limit less one side's open interest in USDC (mainnet SPY, 2026-11-17)."""
  s, client = shared()

  def one(selector: Any) -> StreamManager[Any, Any, Any]:
    """SPY's snapshot."""

    async def connect() -> Stream[Any, Any, Any]:
      """Open the channel."""

      async def frames() -> AsyncIterator[Any]:
        """The subscribe snapshot of one market."""
        yield {
          'market_stats': {
            'market_id': 128,
            'open_interest': Decimal('11873351.69062'),
            'open_interest_limit': Decimal('100000000000000'),
          }
        }

      async def unsubscribe():
        """Close the channel."""

      return Stream(None, frames(), unsubscribe)

    return StreamManager(connect)

  client.streams.market_stats = one  # type: ignore[method-assign]
  market = LighterPerpMarket(shared=s, market_index=128)
  room = Decimal('88126648.30938')
  assert await market.remaining_position_limit() == RemainingPositionLimit(
    long=room, short=room
  )


def test_open_interest_room_caps_and_floors():
  """The uncapped sentinel is no known limit; past the cap is zero both ways."""
  row: Any = {'open_interest': Decimal(10), 'open_interest_limit': Decimal(2**56)}
  assert stats.open_interest_room(row) == RemainingPositionLimit()
  row = {'open_interest': Decimal(10), 'open_interest_limit': Decimal(5_000_000)}
  assert stats.open_interest_room(row) == RemainingPositionLimit(
    long=Decimal(0), short=Decimal(0)
  )
