from __future__ import annotations
from typing_extensions import Any
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Dialect, Engine, String, TypeDecorator, create_engine, event, select
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session
from sqlalchemy.pool import ConnectionPoolEntry
from sqltypes import ValidatedJSON


class TZDateTime(TypeDecorator[datetime]):
  impl = String
  cache_ok = True

  def process_bind_param(self, value: datetime | None, dialect: Dialect) -> str | None:
    if value is None:
      return None
    return value.isoformat()

  def process_result_value(self, value: str | None, dialect: Dialect) -> datetime | None:
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


class IndexerFill(Base):
  __tablename__ = 'indexer_fills'
  address: Mapped[str] = mapped_column(primary_key=True)
  subaccount: Mapped[int] = mapped_column(primary_key=True)
  fill_id: Mapped[str] = mapped_column(primary_key=True)
  created_at_height: Mapped[int] = mapped_column(index=True)
  data: Mapped[Fill] = mapped_column(ValidatedJSON(Fill))  # type: ignore[type-var]


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
  def connect(cls, url: str, *, no_cache_reads: bool = False) -> HistoryCache:
    engine = create_engine(url)
    if engine.dialect.name == 'sqlite':
      @event.listens_for(engine, 'connect')
      def set_wal(dbapi_conn: DBAPIConnection, connection_record: ConnectionPoolEntry) -> None:
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

  def chain_watermark(self, address: str) -> int | None:
    wm = self._get_watermark('chain', address)
    return wm.height if wm is not None else None

  def read_chain_txs(
    self, address: str, *,
    start_height: int | None = None, end_height: int | None = None,
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
    self, address: str, txs: dict[str, TxResponse], *, end_height: int,
  ) -> None:
    with Session(self.engine) as session:
      for tx_hash, tx in txs.items():
        session.merge(ChainTransaction(
          address=address,
          tx_hash=tx_hash,
          height=int(tx['height']),  # type: ignore
          data=tx,
        ))
      session.merge(CacheWatermark(
        source='chain', address=address,
        height=end_height, fetched_at=datetime.now().astimezone(),
      ))
      session.commit()

  # -- Indexer --

  def indexer_watermark(self, address: str, subaccount: int) -> int | None:
    wm = self._get_watermark('indexer', f'{address}/{subaccount}')
    return wm.height if wm is not None else None

  def read_indexer_fills(self, address: str, subaccount: int) -> list[Fill]:
    if self.no_cache_reads:
      return []
    with Session(self.engine) as session:
      stmt = (
        select(IndexerFill)
        .where(IndexerFill.address == address)
        .where(IndexerFill.subaccount == subaccount)
      )
      rows = session.scalars(stmt).all()
      return [row.data for row in rows]

  def write_indexer_fills(
    self, address: str, subaccount: int, fills: list[Fill], *,
    watermark_height: int | None = None,
  ) -> None:
    with Session(self.engine) as session:
      for fill in fills:
        session.merge(IndexerFill(
          address=address,
          subaccount=subaccount,
          fill_id=fill['id'],
          created_at_height=int(fill['createdAtHeight']),
          data=fill,
        ))
      if watermark_height is not None:
        session.merge(CacheWatermark(
          source='indexer', address=f'{address}/{subaccount}',
          height=watermark_height, fetched_at=datetime.now().astimezone(),
        ))
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
    self, address: str, rewards: list[tuple[datetime, str, str]],
  ) -> None:
    with Session(self.engine) as session:
      for block_timestamp, token_denom, token_amount in rewards:
        session.merge(BigQueryReward(
          address=address,
          block_timestamp=block_timestamp,
          token_denom=token_denom,
          token_amount=token_amount,
        ))
      session.merge(CacheWatermark(
        source='bigquery', address=address,
        fetched_at=datetime.now().astimezone(),
      ))
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
        proposal_id = str(proposal.get('id') or proposal.get('proposal_id') or 'unknown')
        session.merge(GovernanceProposal(
          proposal_id=proposal_id,
          data=proposal,
        ))
      session.merge(CacheWatermark(
        source='governance', address='*',
        fetched_at=datetime.now().astimezone(),
      ))
      session.commit()
