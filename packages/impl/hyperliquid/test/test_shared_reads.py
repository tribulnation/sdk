"""Account-state reads shared between markets and concurrent callers."""

from dataclasses import dataclass, field
import asyncio

from typing_extensions import Any, cast
from typed_hyperliquid import Hyperliquid

from tribulnation.hyperliquid.market.impl.mixin import Shared

ADDRESS = '0xabc'


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
  """Concurrent reads of one dex (None and `''` alike) send one request; another dex its own."""
  client = Client()
  shared = Shared(client=cast(Hyperliquid, client), maybe_address=ADDRESS)
  states = await asyncio.gather(
    shared.clearinghouse_state(None),
    shared.clearinghouse_state(''),
    shared.clearinghouse_state(None),
    shared.clearinghouse_state('xyz'),
    shared.spot_clearinghouse_state(),
    shared.spot_clearinghouse_state(),
  )
  assert [s.get('dex') for s in states[:4]] == [None, None, None, 'xyz']
  assert sorted(client.info.calls, key=str) == [
    ('clearinghouseState', 'xyz'),
    ('clearinghouseState', None),
    ('spotClearinghouseState', None),
  ]
  await shared.clearinghouse_state(None)
  assert len(client.info.calls) == 3
