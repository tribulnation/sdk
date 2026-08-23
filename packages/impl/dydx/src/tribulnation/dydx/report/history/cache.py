from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import (
  Dialect,
  Engine,
  String,
  TypeDecorator,
  create_engine,
  delete,
  event,
  select,
)
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import ConnectionPoolEntry
from sqltypes import ValidatedJSON
from typing_extensions import Any


class TZDateTime(TypeDecorator[datetime]):
  impl = String
  cache_ok = True

  def process_bind_param(self, value: datetime | None, dialect: Dialect) -> str | None:
    if value is None:
      return None
    return value.isoformat()

  def process_result_value(
    self, value: str | None, dialect: Dialect
  ) -> datetime | None:
    if value is None:
      return None
    return datetime.fromisoformat(value)


from dydx.chain.comet.types import TxResponse
from dydx.indexer.data.get_fills import Fill


class Base(DeclarativeBase):
  pass


cache_metadata = Base.metadata


class BlockTime(Base):
  __tablename__ = 'block_times'
  height: Mapped[int] = mapped_column(primary_key=True)
  time: Mapped[datetime] = mapped_column(TZDateTime())


class ChainTransaction(Base):
  __tablename__ = 'chain_transactions'
  address: Mapped[str] = mapped_column(primary_key=True)
  tx_hash: Mapped[str] = mapped_column(primary_key=True)
  height: Mapped[int] = mapped_column(index=True)
  data: Mapped[TxResponse] = mapped_column(ValidatedJSON(TxResponse))  # type: ignore[type-var]


class ChainCacheCoverage(Base):
  """One verified inclusive chain-cache height interval."""

  __tablename__ = 'chain_cache_coverage'
  address: Mapped[str] = mapped_column(primary_key=True)
  start_height: Mapped[int] = mapped_column(primary_key=True)
  end_height: Mapped[int] = mapped_column(primary_key=True)


class IndexerFill(Base):
  """Legacy unsequenced indexer-fill cache."""

  __tablename__ = 'indexer_fills'
  address: Mapped[str] = mapped_column(primary_key=True)
  subaccount: Mapped[int] = mapped_column(primary_key=True)
  fill_id: Mapped[str] = mapped_column(primary_key=True)
  created_at_height: Mapped[int] = mapped_column(index=True)
  data: Mapped[Fill] = mapped_column(ValidatedJSON(Fill))  # type: ignore[type-var]


class SequencedIndexerFill(Base):
  """One indexer fill with its verified chronological sequence."""

  __tablename__ = 'sequenced_indexer_fills'
  address: Mapped[str] = mapped_column(primary_key=True)
  subaccount: Mapped[int] = mapped_column(primary_key=True)
  fill_id: Mapped[str] = mapped_column(primary_key=True)
  sequence: Mapped[int] = mapped_column(index=True)
  created_at: Mapped[datetime] = mapped_column(TZDateTime(), index=True)
  data: Mapped[Fill] = mapped_column(ValidatedJSON(Fill))  # type: ignore[type-var]


class IndexerFillCoverage(Base):
  """Verified indexer-fill coverage from genesis through a timestamp."""

  __tablename__ = 'indexer_fill_coverage'
  address: Mapped[str] = mapped_column(primary_key=True)
  subaccount: Mapped[int] = mapped_column(primary_key=True)
  through: Mapped[datetime] = mapped_column(TZDateTime())


class BigQueryReward(Base):
  __tablename__ = 'bigquery_rewards'
  address: Mapped[str] = mapped_column(primary_key=True)
  block_timestamp: Mapped[datetime] = mapped_column(TZDateTime(), primary_key=True)
  token_denom: Mapped[str] = mapped_column(primary_key=True)
  token_amount: Mapped[str] = mapped_column()


class GovernanceProposal(Base):
  __tablename__ = 'governance_proposals'
  proposal_id: Mapped[str] = mapped_column(primary_key=True)
  data: Mapped[dict[str, Any]] = mapped_column(ValidatedJSON(dict[str, Any]))  # type: ignore[type-var]


class CacheWatermark(Base):
  __tablename__ = 'cache_watermarks'
  source: Mapped[str] = mapped_column(primary_key=True)
  address: Mapped[str] = mapped_column(primary_key=True)
  height: Mapped[int | None] = mapped_column(default=None)
  fetched_at: Mapped[datetime | None] = mapped_column(TZDateTime(), default=None)


@dataclass
class HistoryCache:
  engine: Engine
  no_cache_reads: bool = False

  @classmethod
  def connect(cls, url: str, *, no_cache_reads: bool = False) -> 'HistoryCache':
    engine = create_engine(url)
    if engine.dialect.name == 'sqlite':

      @event.listens_for(engine, 'connect')
      def set_wal(
        dbapi_conn: DBAPIConnection, connection_record: ConnectionPoolEntry
      ) -> None:
        cursor = dbapi_conn.cursor()
        cursor.execute('PRAGMA journal_mode=WAL')
        cursor.close()

    cache_metadata.create_all(engine)
    return cls(engine=engine, no_cache_reads=no_cache_reads)

  # -- Block times --

  def get(self, height: int) -> datetime | None:
    if self.no_cache_reads:
      return None
    with Session(self.engine) as session:
      row = session.get(BlockTime, height)
      return row.time if row is not None else None

  def set(self, height: int, time: datetime) -> None:
    with Session(self.engine) as session:
      session.merge(BlockTime(height=height, time=time))
      session.commit()

  # -- Watermark helpers --

  def _get_watermark(self, source: str, address: str) -> CacheWatermark | None:
    if self.no_cache_reads:
      return None
    with Session(self.engine) as session:
      return session.get(CacheWatermark, (source, address))

  # -- Chain --

  def chain_coverage(self, address: str) -> list[tuple[int, int]]:
    """Return verified chain-cache intervals for an address."""
    if self.no_cache_reads:
      return []
    with Session(self.engine) as session:
      stmt = (
        select(ChainCacheCoverage)
        .where(ChainCacheCoverage.address == address)
        .order_by(ChainCacheCoverage.start_height)
      )
      rows = session.scalars(stmt).all()
      return [(row.start_height, row.end_height) for row in rows]

  def chain_gaps(
    self,
    address: str,
    *,
    start_height: int,
    end_height: int,
  ) -> list[tuple[int, int]]:
    """Return uncovered inclusive ranges inside a requested interval."""
    gaps: list[tuple[int, int]] = []
    cursor = start_height
    for covered_start, covered_end in self.chain_coverage(address):
      if covered_end < cursor:
        continue
      if covered_start > end_height:
        break
      if covered_start > cursor:
        gaps.append((cursor, covered_start - 1))
      cursor = max(cursor, covered_end + 1)
      if cursor > end_height:
        break
    if cursor <= end_height:
      gaps.append((cursor, end_height))
    return gaps

  def read_chain_txs(
    self,
    address: str,
    *,
    start_height: int | None = None,
    end_height: int | None = None,
  ) -> dict[str, TxResponse]:
    if self.no_cache_reads:
      return {}
    with Session(self.engine) as session:
      stmt = select(ChainTransaction).where(ChainTransaction.address == address)
      if start_height is not None:
        stmt = stmt.where(ChainTransaction.height >= start_height)
      if end_height is not None:
        stmt = stmt.where(ChainTransaction.height <= end_height)
      rows = session.scalars(stmt).all()
      return {row.tx_hash: row.data for row in rows}

  def write_chain_txs(
    self,
    address: str,
    txs: dict[str, TxResponse],
    *,
    start_height: int,
    end_height: int,
  ) -> None:
    """Atomically store chain transactions and their verified coverage."""
    with Session(self.engine) as session:
      for tx_hash, tx in txs.items():
        session.merge(
          ChainTransaction(
            address=address,
            tx_hash=tx_hash,
            height=int(tx['height']),  # type: ignore
            data=tx,
          )
        )
      stmt = (
        select(ChainCacheCoverage)
        .where(ChainCacheCoverage.address == address)
        .order_by(ChainCacheCoverage.start_height)
      )
      rows = list(session.scalars(stmt).all())
      intervals = [(row.start_height, row.end_height) for row in rows] + [
        (start_height, end_height)
      ]
      merged: list[tuple[int, int]] = []
      for interval_start, interval_end in sorted(intervals):
        if merged and interval_start <= merged[-1][1] + 1:
          previous_start, previous_end = merged[-1]
          merged[-1] = (previous_start, max(previous_end, interval_end))
        else:
          merged.append((interval_start, interval_end))
      for row in rows:
        session.delete(row)
      session.flush()
      session.add_all(
        [
          ChainCacheCoverage(
            address=address,
            start_height=interval_start,
            end_height=interval_end,
          )
          for interval_start, interval_end in merged
        ]
      )
      session.commit()

  # -- Indexer --

  def indexer_fill_coverage(
    self,
    address: str,
    subaccount: int,
  ) -> datetime | None:
    """Return the end of verified fill coverage beginning at genesis."""
    if self.no_cache_reads:
      return None
    with Session(self.engine) as session:
      row = session.get(IndexerFillCoverage, (address, subaccount))
      return row.through if row is not None else None

  def read_indexer_fills(
    self,
    address: str,
    subaccount: int,
    *,
    end: datetime | None = None,
  ) -> list[Fill]:
    """Read cached fills in their verified chronological sequence."""
    if self.no_cache_reads:
      return []
    with Session(self.engine) as session:
      stmt = (
        select(SequencedIndexerFill)
        .where(SequencedIndexerFill.address == address)
        .where(SequencedIndexerFill.subaccount == subaccount)
        .order_by(SequencedIndexerFill.sequence)
      )
      if end is not None:
        stmt = stmt.where(SequencedIndexerFill.created_at <= end)
      rows = session.scalars(stmt).all()
      return [row.data for row in rows]

  def replace_indexer_fills(
    self,
    address: str,
    subaccount: int,
    fills: list[Fill],
    *,
    through: datetime,
  ) -> None:
    """Atomically replace sequenced fills and their genesis coverage."""
    with Session(self.engine) as session:
      session.execute(
        delete(SequencedIndexerFill)
        .where(SequencedIndexerFill.address == address)
        .where(SequencedIndexerFill.subaccount == subaccount)
      )
      session.add_all(
        [
          SequencedIndexerFill(
            address=address,
            subaccount=subaccount,
            fill_id=fill['id'],
            sequence=sequence,
            created_at=fill['createdAt'],
            data=fill,
          )
          for sequence, fill in enumerate(fills)
        ]
      )
      session.merge(
        IndexerFillCoverage(
          address=address,
          subaccount=subaccount,
          through=through,
        )
      )
      session.commit()

  # -- BigQuery --

  def bigquery_has_cache(self, address: str) -> bool:
    return self._get_watermark('bigquery', address) is not None

  def read_bigquery_rewards(self, address: str) -> list[BigQueryReward]:
    if self.no_cache_reads:
      return []
    with Session(self.engine) as session:
      stmt = select(BigQueryReward).where(BigQueryReward.address == address)
      return list(session.scalars(stmt).all())

  def write_bigquery_rewards(
    self,
    address: str,
    rewards: list[tuple[datetime, str, str]],
  ) -> None:
    with Session(self.engine) as session:
      for block_timestamp, token_denom, token_amount in rewards:
        session.merge(
          BigQueryReward(
            address=address,
            block_timestamp=block_timestamp,
            token_denom=token_denom,
            token_amount=token_amount,
          )
        )
      session.merge(
        CacheWatermark(
          source='bigquery',
          address=address,
          fetched_at=datetime.now().astimezone(),
        )
      )
      session.commit()

  # -- Governance --

  def governance_has_cache(self) -> bool:
    return self._get_watermark('governance', '*') is not None

  def read_governance_proposals(self) -> list[dict[str, Any]]:
    if self.no_cache_reads:
      return []
    with Session(self.engine) as session:
      stmt = select(GovernanceProposal)
      rows = session.scalars(stmt).all()
      return [row.data for row in rows]

  def write_governance_proposals(self, proposals: list[dict[str, Any]]) -> None:
    with Session(self.engine) as session:
      for proposal in proposals:
        proposal_id = str(
          proposal.get('id') or proposal.get('proposal_id') or 'unknown'
        )
        session.merge(
          GovernanceProposal(
            proposal_id=proposal_id,
            data=proposal,
          )
        )
      session.merge(
        CacheWatermark(
          source='governance',
          address='*',
          fetched_at=datetime.now().astimezone(),
        )
      )
      session.commit()
