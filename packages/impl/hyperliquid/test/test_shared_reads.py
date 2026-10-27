"""Account-state reads shared between markets and concurrent callers."""

from dataclasses import dataclass, field
from datetime import timedelta
import asyncio

from typing_extensions import Any, cast
from typed_hyperliquid import Hyperliquid

from tribulnation.hyperliquid.market.impl.mixin import Shared

ADDRESS = '0xabc'
SECOND = timedelta(seconds=1)


@dataclass
class Info:
  """The `/info` requests the account reads make, counted per request type."""

  calls: list[tuple[str, Any]] = field(default_factory=list[tuple[str, Any]])

  async def clearinghouse_state(self, *, user: str, dex: str | None = None) -> Any:
    """A perp state naming its dex, after a pause so concurrent readers overlap."""
    self.calls.append(('clearinghouseState', dex))
    await asyncio.sleep(0.01)
    return {'user': user, 'dex': dex}

  async def spot_clearinghouse_state(self, *, user: str) -> Any:
    """A spot state."""
    self.calls.append(('spotClearinghouseState', None))
    await asyncio.sleep(0.01)
    return {'user': user, 'balances': []}


@dataclass
class Client:
  """The client attributes the reads reach."""

  info: Info = field(default_factory=Info)


async def test_markets_share_one_state_read_per_dex():
  """Concurrent shared reads of one dex (None and `''` alike) send one request; another
  dex its own."""
  client = Client()
  shared = Shared(client=cast(Hyperliquid, client), maybe_address=ADDRESS)
  states = await asyncio.gather(
    shared.clearinghouse_state(None, ttl=SECOND),
    shared.clearinghouse_state('', ttl=SECOND),
    shared.clearinghouse_state(None, ttl=timedelta(0)),
    shared.clearinghouse_state('xyz', ttl=SECOND),
    shared.spot_clearinghouse_state(ttl=SECOND),
    shared.spot_clearinghouse_state(ttl=SECOND),
  )
  assert [s.get('dex') for s in states[:4]] == [None, None, None, 'xyz']
  assert sorted(client.info.calls, key=str) == [
    ('clearinghouseState', 'xyz'),
    ('clearinghouseState', None),
    ('spotClearinghouseState', None),
  ]
  await shared.clearinghouse_state(None, ttl=SECOND)
  assert len(client.info.calls) == 3


async def test_fresh_state_reads_send_their_own_request():
  """`ttl=None` reads neither reuse a stored state nor join one in flight."""
  client = Client()
  shared = Shared(client=cast(Hyperliquid, client), maybe_address=ADDRESS)
  await shared.spot_clearinghouse_state(ttl=SECOND)
  await asyncio.gather(
    shared.spot_clearinghouse_state(ttl=None),
    shared.spot_clearinghouse_state(ttl=None),
  )
  assert len(client.info.calls) == 3
  await shared.spot_clearinghouse_state(ttl=SECOND)
  assert len(client.info.calls) == 3
