"""Durable cache of raw Hyperliquid API responses.

This is **not** an optimisation. Hyperliquid retains only the 10000 most recent
fills, and `userTwapSliceFills` caps at 2000 with no time range at all. Once an
account passes those limits the older records are gone from the API, and exact
cost basis for positions opened before then becomes unrecoverable. A client that
has been reading an account regularly still holds that history here.

So the cache is an archive of record, and two rules follow:

- **Never evict.** Cached rows may be the only surviving copy.
- **Never refresh by discarding.** A refetch cannot recover what has aged out.
  `no_cache_reads` is a write-only refresh mode, not a way to clear the cache.

Only raw responses are stored, never derived values. Realized PnL is recomputed
by folding the cached fill stream on every read: the fold is cheap against a
local database, and a stored checkpoint would be the one piece of state that
could silently go stale if the fold logic ever changed.

Payloads round-trip through `sqltypes.ValidatedJSON`, which requires that it
**preserve explicit nulls**. Several Hyperliquid fields are required but
nullable — `nSamples` is null on 2794 of 3361 real funding entries, and
`spotTransfer.nonce` on roughly 60% of transfers — and dropping those on write
makes them come back missing and fail validation on read.

Writes expect **validated** records, as an `Info` client with `validate=True`
returns. Handing in raw payloads still round-trips correctly, because pydantic
coerces on the way back, but it emits serializer warnings: the raw form carries
decimals as strings, and the stored schema declares them as `Decimal`.
"""
from typing_extensions import Any, Sequence
from dataclasses import dataclass

from sqlalchemy import Engine, create_engine, event, select
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session
from sqlalchemy.pool import ConnectionPoolEntry
from sqltypes import ValidatedJSON

from hyperliquid.info.methods.user_fills_by_time import UserFill
from hyperliquid.info.perps.user_funding import UserFundingEntry
from hyperliquid.info.perps.user_non_funding_ledger_updates import UserNonFundingLedgerEntry

from .fills import AnyFill


class Base(DeclarativeBase):
  """Declarative base for the Hyperliquid history cache."""

cache_metadata = Base.metadata


class Fill(Base):
  """One cached fill.

  Keyed on `(address, time, sequence)`, where `sequence` is the fill's position
  within its millisecond **in the order the API returned it**. That order is
  load-bearing: `startPosition` only chains in API order, so a cache that
  restores rows in any other order silently breaks realized-PnL reconstruction.
  Reading back ordered only by time produced 2382 chain breaks across 27 coins.

  None of Hyperliquid's own identifiers can substitute. `tid` is a sentinel 0 on
  dust conversions, and many fills share both a millisecond and a hash.
  """
  __tablename__ = 'fills'
  address: Mapped[str] = mapped_column(primary_key=True)
  source: Mapped[str] = mapped_column(primary_key=True)
  """Which endpoint the fill came from: `'fills'` or `'twap'`.

  TWAP slices are a separate stream that does not overlap `userFillsByTime`, but
  they share its shape and can land on the same millisecond, so they would
  otherwise collide on `(time, sequence)` and silently overwrite each other.
  """
  time: Mapped[int] = mapped_column(primary_key=True, index=True)
  sequence: Mapped[int] = mapped_column(primary_key=True)
  """Position within the millisecond, in API order."""
  hash: Mapped[str] = mapped_column()
  tid: Mapped[int] = mapped_column()
  data: Mapped[UserFill] = mapped_column(ValidatedJSON(UserFill))  # type: ignore[type-var]


class Funding(Base):
  """One cached funding payment."""
  __tablename__ = 'funding'
  address: Mapped[str] = mapped_column(primary_key=True)
  time: Mapped[int] = mapped_column(primary_key=True, index=True)
  coin: Mapped[str] = mapped_column(primary_key=True)
  data: Mapped[UserFundingEntry] = mapped_column(ValidatedJSON(UserFundingEntry))  # type: ignore[type-var]


class LedgerEntry(Base):
  """One cached non-funding ledger entry.

  `(time, hash)` is not unique — a single transaction can emit several deltas,
  one per margin bucket — so the position within the response is part of the key.
  """
  __tablename__ = 'ledger_entries'
  address: Mapped[str] = mapped_column(primary_key=True)
  time: Mapped[int] = mapped_column(primary_key=True, index=True)
  sequence: Mapped[int] = mapped_column(primary_key=True)
  """Position within the millisecond, in API order."""
  hash: Mapped[str] = mapped_column()
  data: Mapped[UserNonFundingLedgerEntry] = mapped_column(ValidatedJSON(UserNonFundingLedgerEntry))  # type: ignore[type-var]


class Watermark(Base):
  """How far a source has been fetched for one address."""
  __tablename__ = 'cache_watermarks'
  source: Mapped[str] = mapped_column(primary_key=True)
  address: Mapped[str] = mapped_column(primary_key=True)
  time: Mapped[int | None] = mapped_column(default=None)
  """Millisecond timestamp of the newest record fetched."""


@dataclass
class HistoryCache:
  """SQLAlchemy-backed archive of raw Hyperliquid responses."""
  engine: Engine
  no_cache_reads: bool = False
  """Bypass reads while still writing. Refreshes the archive; never clears it."""

  @classmethod
  def connect(cls, url: str, *, no_cache_reads: bool = False) -> 'HistoryCache':
    """Open (and create if needed) a cache database."""
    engine = create_engine(url)
    if engine.dialect.name == 'sqlite':
      @event.listens_for(engine, 'connect')
      def set_wal(conn: DBAPIConnection, record: ConnectionPoolEntry) -> None:
        cursor = conn.cursor()
        cursor.execute('PRAGMA journal_mode=WAL')
        cursor.close()
    cache_metadata.create_all(engine)
    return cls(engine=engine, no_cache_reads=no_cache_reads)

  def watermark(self, source: str, address: str) -> int | None:
    """Return the newest cached timestamp for a source, if any."""
    if self.no_cache_reads:
      return None
    with Session(self.engine) as session:
      row = session.get(Watermark, (source, address))
      return row.time if row is not None else None

  def _advance(self, session: Session, source: str, address: str, time: int | None) -> None:
    """Move a watermark forward. Never backwards — that would refetch and, worse,
    imply history is missing that the archive actually holds."""
    row = session.get(Watermark, (source, address))
    if row is None:
      session.add(Watermark(source=source, address=address, time=time))
    elif time is not None and (row.time is None or time > row.time):
      row.time = time

  def read_fills(self, address: str, *, source: str = 'fills') -> list['AnyFill']:
    """Return every cached fill for an address and source, oldest first."""
    if self.no_cache_reads:
      return []
    with Session(self.engine) as session:
      stmt = (select(Fill)
              .where(Fill.address == address, Fill.source == source)
              .order_by(Fill.time, Fill.sequence))
      return [row.data for row in session.scalars(stmt)]

  def write_fills(
    self, address: str, fills: Sequence['AnyFill'], *, source: str = 'fills',
  ) -> None:
    """Merge fills into the archive and advance the watermark.

    `fills` must be in API order: their position within a millisecond is stored
    and is what makes the `startPosition` chain reconstructable on read.
    """
    with Session(self.engine) as session:
      seen: dict[int, int] = {}
      for fill in fills:
        time = fill['time']
        sequence = seen[time] = seen.get(time, -1) + 1
        session.merge(Fill(
          address=address, source=source, time=time, sequence=sequence,
          hash=fill['hash'], tid=fill['tid'], data=fill,
        ))
      self._advance(session, source, address,
                    max((f['time'] for f in fills), default=None))
      session.commit()

  def read_funding(self, address: str) -> list[UserFundingEntry]:
    """Return every cached funding payment for an address, oldest first."""
    if self.no_cache_reads:
      return []
    with Session(self.engine) as session:
      stmt = select(Funding).where(Funding.address == address).order_by(Funding.time)
      return [row.data for row in session.scalars(stmt)]

  def write_funding(self, address: str, entries: Sequence[UserFundingEntry]) -> None:
    """Merge funding payments into the archive and advance the watermark."""
    with Session(self.engine) as session:
      for entry in entries:
        session.merge(Funding(
          address=address, time=entry['time'],
          coin=entry['delta']['coin'], data=entry,
        ))
      self._advance(session, 'funding', address,
                    max((e['time'] for e in entries), default=None))
      session.commit()

  def read_ledger(self, address: str) -> list[UserNonFundingLedgerEntry]:
    """Return every cached ledger entry for an address, oldest first."""
    if self.no_cache_reads:
      return []
    with Session(self.engine) as session:
      stmt = (select(LedgerEntry).where(LedgerEntry.address == address)
              .order_by(LedgerEntry.time, LedgerEntry.sequence))
      return [row.data for row in session.scalars(stmt)]

  def write_ledger(self, address: str, entries: Sequence[UserNonFundingLedgerEntry]) -> None:
    """Merge ledger entries into the archive and advance the watermark."""
    with Session(self.engine) as session:
      seen: dict[int, int] = {}
      for entry in entries:
        time = entry['time']
        sequence = seen[time] = seen.get(time, -1) + 1
        session.merge(LedgerEntry(
          address=address, time=time, sequence=sequence,
          hash=entry['hash'], data=entry,
        ))
      self._advance(session, 'ledger', address,
                    max((e['time'] for e in entries), default=None))
      session.commit()
