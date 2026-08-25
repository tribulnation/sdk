"""Hyperliquid reporting history."""

from typing_extensions import TYPE_CHECKING, AsyncContextManager, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
import asyncio

from tribulnation.sdk import SDK
from tribulnation.sdk.reporting import History as _History, Observation, HistoryRecord
from tribulnation.sdk.reporting.util import source_id
from typed_hyperliquid.core import timestamp_millis
from typed_hyperliquid.info import Info
from tribulnation.hyperliquid.core import wrap_exceptions

from .assets import Assets, USDC
from .fills import AnyFill, discontinuities, parse_fills
from .funding import parse_fundings
from .ledger import parse_entry
from .staking import parse_history, parse_rewards
from .window import dump_time, in_window

if TYPE_CHECKING:
  from .cache import HistoryCache

GENESIS_MS = 1672531200000
"""2023-01-01, safely before Hyperliquid mainnet launch."""

SERVICE = 'hyperliquid'


@dataclass
class History(_History):
  """Reporting history for one Hyperliquid account.

  Realized PnL is reconstructed by folding the account's complete fill stream,
  so `start` filters the output but never the fetch — a position opened before
  the window has no recoverable cost basis otherwise.
  """

  info: Info
  address: str
  assets: Assets | None = field(default=None, repr=False)
  cache: 'HistoryCache | None' = field(default=None, repr=False)
  """Durable archive of raw responses.

  Not merely a speed-up: Hyperliquid drops fills past its retention limits, so
  for an account read regularly this may hold the only surviving copy of its
  early history. See `cache.py`.
  """

  @classmethod
  def http(
    cls,
    address: str,
    *,
    validate: bool = True,
    mainnet: bool = True,
    cache: 'HistoryCache | None' = None,
  ):
    """Create a history client over HTTP."""
    return cls(Info.http(validate=validate, mainnet=mainnet), address, cache=cache)

  def since(self, source: str) -> datetime:
    """Return the timestamp to resume fetching a source from.

    Resumes *at* the watermark, not after it, so the boundary millisecond is
    refetched in full. Starting after it would drop any record sharing that
    millisecond which had not yet arrived — the same class of gap a `+1` cursor
    caused inside the client's own pagination.
    """
    if self.cache is None:
      return timestamp_millis.parse(GENESIS_MS)
    watermark = self.cache.watermark(source, self.address)
    return timestamp_millis.parse(GENESIS_MS if watermark is None else watermark)

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    yield self.info

  async def resolve_assets(self) -> Assets:
    """Fetch and memoise the token index, needed to canonicalise asset ids."""
    if self.assets is None:
      self.assets = await Assets.fetch(self.info)
    return self.assets

  @SDK.method
  @wrap_exceptions
  async def settlement(self) -> dict[str, str]:
    """Map each perp coin to its settlement token index.

    HIP-3 dexes settle in tokens other than USDC, so fees, funding and realized
    PnL for their markets are denominated differently.

    A dex whose metadata cannot be read raises rather than being skipped. Its
    markets would otherwise fall through to the USDC default at every lookup,
    misattributing their PnL to an asset they never settled in.
    """
    dexes = await self.info.perp_dexs()
    out: dict[str, str] = {}
    for dex in dexes:
      name = dex and dex['name']
      meta, _ = await self.info.perp_meta_and_asset_ctxs(dex=name or '')
      token = str(meta['collateralToken'])
      # Named dexes already qualify their universe entries (`flx:TSLA`); only the
      # main dex uses bare names (`BTC`). Prefixing the dex name again yields
      # `flx:flx:TSLA`, which no fill ever matches.
      for asset in meta['universe']:
        out[asset['name']] = token
    return out

  @SDK.method
  @wrap_exceptions
  async def fetch_fills(self) -> list[AnyFill]:
    """Fetch every fill for the account, including TWAP slices.

    TWAP slices come from a separate endpoint and do **not** appear in
    `userFillsByTime` — verified as zero overlap on a real account — so omitting
    them under-counts trades. That endpoint takes no time range, has no paged
    variant and caps at 2000 records, which is a retention limit with no
    workaround at this layer.
    """
    fresh: list[AnyFill] = []
    async for page in self.info.user_fills_by_time_paged(
      user=self.address,
      start_time=self.since('fills'),
    ):
      fresh.extend(page)
    twap = [
      slice['fill']
      for slice in await self.info.user_twap_slice_fills(user=self.address)
    ]

    if self.cache is None:
      return [*fresh, *twap]

    # Top the archive up, then read the whole stream back from it: the archive
    # may reach further back than the API still serves.
    if fresh:
      self.cache.write_fills(self.address, fresh, source='fills')
    if twap:
      self.cache.write_fills(self.address, twap, source='twap')
    cached = self.cache.read_fills(self.address, source='fills')
    cached_twap = self.cache.read_fills(self.address, source='twap')
    if not cached and not cached_twap:
      return [*fresh, *twap]  # no_cache_reads is write-only
    return [*cached, *cached_twap]

  async def trades(
    self, start: datetime | None, end: datetime | None
  ) -> list[HistoryRecord]:
    """Fetch fills and convert them to trade observations."""
    id = source_id(SERVICE)
    assets, settle = await asyncio.gather(self.resolve_assets(), self.settlement())
    fills = await self.fetch_fills()
    observations, _ = parse_fills(fills, assets=assets, settle=settle)
    return self.records(observations, start, end, id)

  async def funding(
    self, start: datetime | None, end: datetime | None
  ) -> list[HistoryRecord]:
    """Fetch funding payments and convert them to observations."""
    id = source_id(SERVICE)
    settle = await self.settlement()
    fresh = []
    async for page in self.info.user_funding_paged(
      user=self.address,
      start_time=self.since('funding'),
    ):
      fresh.extend(page)
    entries = fresh
    if self.cache is not None:
      if fresh:
        self.cache.write_funding(self.address, fresh)
      entries = self.cache.read_funding(self.address) or fresh
    return self.records(parse_fundings(entries, settle=settle), start, end, id)

  async def ledger(
    self, start: datetime | None, end: datetime | None
  ) -> list[HistoryRecord]:
    """Fetch non-funding ledger updates and convert them to observations.

    The un-paged call silently truncates at 2000 entries, keeping the oldest, so
    the paged helper is mandatory rather than an optimisation.
    """
    id = source_id(SERVICE)
    assets = await self.resolve_assets()
    fresh = []
    async for page in self.info.user_non_funding_ledger_updates_paged(
      user=self.address,
      start_time=self.since('ledger'),
    ):
      fresh.extend(page)
    entries = fresh
    if self.cache is not None:
      if fresh:
        self.cache.write_ledger(self.address, fresh)
      entries = self.cache.read_ledger(self.address) or fresh
    observations = [
      obs
      for index, entry in enumerate(entries)
      for obs in parse_entry(entry, index=index, address=self.address, assets=assets)
    ]
    return self.records(observations, start, end, id)

  async def staking(
    self, start: datetime | None, end: datetime | None
  ) -> list[HistoryRecord]:
    """Fetch staking rewards and delegation history."""
    id = source_id(SERVICE)
    rewards, entries = await asyncio.gather(
      self.info.staking_rewards(user=self.address),
      self.info.staking_history(user=self.address),
    )
    observations = [*parse_rewards(rewards), *parse_history(entries)]
    return self.records(observations, start, end, id)

  def records(
    self,
    observations: Sequence[Observation],
    start: datetime | None,
    end: datetime | None,
    id: str,
  ) -> list[HistoryRecord]:
    """Wrap observations in records, dropping those outside the window."""
    return [
      HistoryRecord(
        observations=[obs],
        provenance={'source': 'api', 'service': SERVICE, 'id': id},
      )
      for obs in observations
      if in_window(obs.time, start=start, end=end)
    ]

  async def history(self, start: datetime | None = None, end: datetime | None = None):
    """Fetch the account's reporting history.

    Sources run **sequentially**, unlike the concurrent fan-out other venue
    implementations use. There, each source is a different service; here all
    four hit the same rate-limited endpoint, and `userFillsByTime` charges
    additional weight per 20 items returned. Sweeping them concurrently
    multiplies that and reliably earns a 429 on an account of any size.
    """
    for source in (self.trades, self.funding, self.ledger, self.staking):
      for record in await source(start, end):
        yield record

  @SDK.method
  @wrap_exceptions
  async def audit(self, fills: Sequence[AnyFill] | None = None) -> dict[str, int]:
    """Report `startPosition` breaks per coin, as a fill-completeness check.

    Should be empty. A non-empty result means fills are missing, which makes
    realized PnL for those coins unrecoverable — worth surfacing rather than
    silently reconstructing from an incomplete stream.

    Args:
      fills: An already-fetched fill stream. Pass one where available; fetching
        again doubles the most expensive call this client makes.
    """
    return discontinuities(fills if fills is not None else await self.fetch_fills())
