"""dYdX reporting history orchestration."""

from typing_extensions import AsyncIterable, Awaitable, TYPE_CHECKING
from dataclasses import dataclass, field
import asyncio
from datetime import datetime

from tribulnation.dydx.core import wrap_exceptions
from tribulnation.sdk.reporting import History as _History, Record

from dydx import Dydx
from .bigquery import BigQueryHistory
from .comet import CometHistory
from .constants import (
  COMET_FUNDING_SEARCH_PER_PAGE,
  COMET_TX_SEARCH_PER_PAGE,
  DEFAULT_CHAIN_FEES_SOURCE,
  DEFAULT_COMMUNITY_TREASURY_DISTRIBUTIONS_SOURCE,
  DEFAULT_FILLS_SOURCE,
  DEFAULT_FUNDING_SOURCE,
  DEFAULT_IBC_WALLET_TRANSFERS_SOURCE,
  DEFAULT_MEGAVAULT_SOURCE,
  DEFAULT_STAKING_SOURCE,
  DEFAULT_SUBACCOUNT_TRANSFERS_SOURCE,
  DEFAULT_TRADING_REWARDS_SOURCE,
  DEFAULT_WALLET_TRANSFERS_SOURCE,
)
from .governance import GovernanceHistory
from .indexer import IndexerHistory
from ..config import DydxConfig

if TYPE_CHECKING:
  from google.cloud.bigquery import Client as BigQueryClient

@dataclass(frozen=True)
class History(IndexerHistory, CometHistory, BigQueryHistory, GovernanceHistory, _History):
  """dYdX reporting history from the configured evidence sources."""
  address: str
  client: Dydx
  config: DydxConfig
  bigquery: 'BigQueryClient | None'
  comet_block_times: dict[str, datetime | None] = field(default_factory=dict)
  comet_block_time_tasks: dict[str, asyncio.Task[datetime | None]] = field(default_factory=dict)

  def source(self, key: str, default: str) -> str:
    """Return the configured source for one dYdX history bucket."""
    return self.config.get('sources', {}).get(key, default)

  @wrap_exceptions
  async def history(self, start: datetime | None = None, end: datetime | None = None) -> AsyncIterable[Record]:
    """Fetch dYdX account history records."""
    start = start.astimezone() if start is not None else None
    end = end.astimezone() if end is not None else None
    fills_source = self.source('fills', DEFAULT_FILLS_SOURCE)
    subaccount_transfers_source = self.source('subaccount_transfers', DEFAULT_SUBACCOUNT_TRANSFERS_SOURCE)
    funding_source = self.source('funding', DEFAULT_FUNDING_SOURCE)
    chain_fees_source = self.source('chain_fees', DEFAULT_CHAIN_FEES_SOURCE)
    trading_rewards_source = self.source('trading_rewards', DEFAULT_TRADING_REWARDS_SOURCE)
    staking_source = self.source('staking', DEFAULT_STAKING_SOURCE)
    community_treasury_source = self.source(
      'community_treasury_distributions',
      DEFAULT_COMMUNITY_TREASURY_DISTRIBUTIONS_SOURCE,
    )
    megavault_source = self.source('megavault', DEFAULT_MEGAVAULT_SOURCE)
    ibc_wallet_transfers_source = self.source('ibc_wallet_transfers', DEFAULT_IBC_WALLET_TRANSFERS_SOURCE)
    wallet_transfers_source = self.source('wallet_transfers', DEFAULT_WALLET_TRANSFERS_SOURCE)
    if fills_source != 'indexer':
      raise NotImplementedError('dYdX fills currently support only the indexer source.')
    queue: asyncio.Queue[Record | Exception | None] = asyncio.Queue()
    producers: list[asyncio.Task[None]] = []

    async def produce(records: Awaitable[list[Record]]):
      """Yield one record-producing task into the history queue."""
      try:
        for record in await records:
          await queue.put(record)
      except Exception as exc:
        await queue.put(exc)
      finally:
        await queue.put(None)

    async def produce_indexer_records():
      """Yield indexer records as each subaccount completes."""
      subaccounts = await self.subaccounts()
      subaccount_tasks = [
        asyncio.create_task(self.subaccount_records(
          subaccount['subaccountNumber'],
          start=start,
          end=end,
          include_fills=fills_source == 'indexer',
          include_transfers=subaccount_transfers_source == 'indexer',
        ))
        for subaccount in subaccounts
      ]
      try:
        for task in asyncio.as_completed(subaccount_tasks):
          subaccount_records, _subaccount_hashes = await task
          for record in subaccount_records:
            await queue.put(record)
      except Exception as exc:
        await queue.put(exc)
      finally:
        for task in subaccount_tasks:
          if not task.done():
            task.cancel()
        await queue.put(None)

    signed_txs_task = (
      asyncio.create_task(self.fetch_comet_txs(
        f"tx.fee_payer='{self.address}'",
        per_page=COMET_TX_SEARCH_PER_PAGE,
      ))
      if (
        subaccount_transfers_source == 'node'
        or chain_fees_source == 'node'
        or staking_source == 'node'
        or megavault_source == 'node'
        or ibc_wallet_transfers_source == 'node'
      )
      else None
    )
    subaccount_txs_task = (
      asyncio.create_task(self.fetch_comet_txs_many([
        f"deposit_to_subaccount.sender='{self.address}'",
        f"deposit_to_subaccount.recipient='{self.address}'",
        f"withdraw_from_subaccount.sender='{self.address}'",
        f"withdraw_from_subaccount.recipient='{self.address}'",
        f"create_transfer.sender='{self.address}'",
        f"create_transfer.recipient='{self.address}'",
      ], per_page=COMET_TX_SEARCH_PER_PAGE))
      if subaccount_transfers_source == 'node'
      else None
    )
    funding_task = (
      asyncio.create_task(self.fetch_comet_txs(
        f"settled_funding.subaccount='{self.address}'",
        per_page=COMET_FUNDING_SEARCH_PER_PAGE,
      ))
      if funding_source == 'node'
      else None
    )
    inbound_ibc_task = (
      asyncio.create_task(self.fetch_comet_txs(
        f"fungible_token_packet.receiver='{self.address}'",
        per_page=COMET_TX_SEARCH_PER_PAGE,
      ))
      if ibc_wallet_transfers_source == 'node'
      else None
    )

    async def node_funding_records() -> list[Record]:
      """Collect node-backed funding records."""
      txs = await funding_task if funding_task is not None else []
      return await self.chain_funding(txs, start=start, end=end)

    async def node_fee_records() -> list[Record]:
      """Collect node-backed chain fee records."""
      txs = await signed_txs_task if signed_txs_task is not None else []
      return await self.chain_fees(txs, start=start, end=end)

    async def node_staking_records() -> list[Record]:
      """Collect node-backed staking records."""
      txs = await signed_txs_task if signed_txs_task is not None else []
      return await self.chain_staking_transfers(txs, start=start, end=end)

    async def node_subaccount_records() -> list[Record]:
      """Collect node-backed subaccount transfer records."""
      txs = await subaccount_txs_task if subaccount_txs_task is not None else []
      return await self.chain_subaccount_transfers(txs, start=start, end=end)

    async def node_megavault_records() -> list[Record]:
      """Collect node-backed Megavault records."""
      txs = await signed_txs_task if signed_txs_task is not None else []
      return await self.chain_megavault_transfers(txs, start=start, end=end)

    async def node_ibc_records() -> list[Record]:
      """Collect node-backed IBC wallet transfer records."""
      outbound = await signed_txs_task if signed_txs_task is not None else []
      inbound = await inbound_ibc_task if inbound_ibc_task is not None else []
      return await self.chain_ibc_transfers(outbound + inbound, start=start, end=end)

    producers.append(asyncio.create_task(produce_indexer_records()))
    if subaccount_transfers_source == 'node':
      producers.append(asyncio.create_task(produce(node_subaccount_records())))
    elif subaccount_transfers_source == 'bigquery':
      producers.append(asyncio.create_task(produce(self.bigquery_subaccount_transfers(start=start, end=end))))
    if funding_source == 'bigquery':
      producers.append(asyncio.create_task(produce(self.bigquery_funding(start=start, end=end))))
    else:
      producers.append(asyncio.create_task(produce(node_funding_records())))
    if chain_fees_source == 'node':
      producers.append(asyncio.create_task(produce(node_fee_records())))
    if staking_source == 'bigquery':
      producers.append(asyncio.create_task(produce(self.bigquery_staking_transfers(start=start, end=end))))
    else:
      producers.append(asyncio.create_task(produce(node_staking_records())))
    if trading_rewards_source == 'bigquery':
      producers.append(asyncio.create_task(produce(self.bigquery_trading_rewards(start=start, end=end))))
    if community_treasury_source == 'governance':
      producers.append(asyncio.create_task(produce(
        self.governance_community_treasury_distributions(start=start, end=end),
      )))
    elif community_treasury_source == 'bigquery':
      producers.append(asyncio.create_task(produce(
        self.bigquery_community_treasury_distributions(start=start, end=end),
      )))
    if megavault_source == 'node':
      producers.append(asyncio.create_task(produce(node_megavault_records())))
    elif megavault_source == 'bigquery':
      producers.append(asyncio.create_task(produce(self.bigquery_megavault_transfers(start=start, end=end))))
    if ibc_wallet_transfers_source == 'node':
      producers.append(asyncio.create_task(produce(node_ibc_records())))
    elif ibc_wallet_transfers_source == 'bigquery':
      producers.append(asyncio.create_task(produce(self.bigquery_ibc_wallet_transfers(start=start, end=end))))
    if wallet_transfers_source == 'bigquery':
      producers.append(asyncio.create_task(produce(self.bigquery_wallet_transfers(start=start, end=end))))

    try:
      seen_ids: set[str] = set()
      remaining = len(producers)
      while remaining:
        record = await queue.get()
        if record is None:
          remaining -= 1
          continue
        if isinstance(record, Exception):
          raise record
        ids = [observation.id for observation in record.observations if observation.id is not None]
        if ids and all(observation_id in seen_ids for observation_id in ids):
          continue
        seen_ids.update(ids)
        yield record
    finally:
      for producer in producers:
        if not producer.done():
          producer.cancel()
      if signed_txs_task is not None and not signed_txs_task.done():
        signed_txs_task.cancel()
      if subaccount_txs_task is not None and not subaccount_txs_task.done():
        subaccount_txs_task.cancel()
      if funding_task is not None and not funding_task.done():
        funding_task.cancel()
      if inbound_ibc_task is not None and not inbound_ibc_task.done():
        inbound_ibc_task.cancel()
      await asyncio.gather(*producers, return_exceptions=True)
      await asyncio.gather(*[
        task for task in (signed_txs_task, funding_task, inbound_ibc_task)
        if task is not None
      ], return_exceptions=True)
