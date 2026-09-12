from typing_extensions import TYPE_CHECKING, Any, TypedDict
from dataclasses import dataclass, field
from datetime import datetime
from asyncer import asyncify
from google.cloud import bigquery
from google.cloud.bigquery import Client as BigQueryClient
import requests

from tribulnation.sdk import SDK, NetworkError, ValidationError
from tribulnation.sdk.reporting import Bonus, HistoryRecord, source_id, ProvidersConfig
from tribulnation.dydx.core import parse_denom_amount
from . import gcloud
from .window import in_window

if TYPE_CHECKING:
  from .cache import HistoryCache, BigQueryReward


class CostEstimate(TypedDict):
  """What a query would scan, and what BigQuery's on-demand pricing charges for it."""

  bytes_processed: int
  gib_processed: float
  tib_processed: float
  estimated_cost_usd: float


class QueryCost(TypedDict):
  """What a finished query job scanned, billed and cost."""

  job_id: str | None
  cache_hit: bool
  bytes_processed: int
  gib_processed: float
  bytes_billed: int
  tib_billed: float
  estimated_cost_usd: float
  slot_millis: int | None


class RewardRow(TypedDict):
  """One `dydx_reward_distribution` row, as read from BigQuery or from the cache."""

  block_timestamp: datetime
  token_denom: str
  token_amount: str
  """The integer amount in the denom's smallest unit, as its decimal string."""


def estimate_query_cost(
  client: bigquery.Client, query: str, price_per_tib: float = 6.25
) -> CostEstimate:
  """Estimate BigQuery on-demand cost without executing the query."""
  config = bigquery.QueryJobConfig(
    dry_run=True,
    use_query_cache=False,
  )
  job = client.query(query, job_config=config)

  bytes_processed = int(job.total_bytes_processed or 0)
  tib_processed = bytes_processed / 1024**4

  return {
    'bytes_processed': bytes_processed,
    'gib_processed': bytes_processed / 1024**3,
    'tib_processed': tib_processed,
    'estimated_cost_usd': tib_processed * price_per_tib,
  }


def run_query_with_cost(
  client: bigquery.Client,
  query: str,
  price_per_tib: float = 6.25,
  max_cost_usd: float | None = None,
) -> tuple[list[dict[str, Any]], QueryCost]:
  """Run a query and return its rows with the job's cost."""
  maximum_bytes_billed = None

  if max_cost_usd is not None:
    if max_cost_usd < 0:
      raise ValueError('max_cost_usd must be non-negative')

    maximum_bytes_billed = int(max_cost_usd / price_per_tib * 1024**4)

  config = bigquery.QueryJobConfig(
    maximum_bytes_billed=maximum_bytes_billed,
  )

  query_job = client.query(query, job_config=config)
  results = gcloud.rows(query_job)

  bytes_processed = query_job.total_bytes_processed or 0
  bytes_billed = query_job.total_bytes_billed or 0

  cost_info: QueryCost = {
    'job_id': gcloud.job_id(query_job),
    'cache_hit': gcloud.cache_hit(query_job),
    'bytes_processed': bytes_processed,
    'gib_processed': bytes_processed / 1024**3,
    'bytes_billed': bytes_billed,
    'tib_billed': bytes_billed / 1024**4,
    'estimated_cost_usd': (bytes_billed / 1024**4 * price_per_tib),
    'slot_millis': query_job.slot_millis,
  }

  return results, cost_info


run_query_with_cost_async = asyncify(run_query_with_cost)


def reward_row(row: dict[str, Any]) -> RewardRow:
  """
  Check the shape of one BigQuery reward row.

  Args:
    row: A `dydx_reward_distribution` row as `{column: value}`.

  Raises:
    ValidationError: A column is missing or not of the type the table declares.
  """
  time = row.get('block_timestamp')
  denom = row.get('token_denom')
  amount = row.get('token_amount')
  if not isinstance(time, datetime) or not isinstance(denom, str) or amount is None:
    raise ValidationError(f'Unexpected BigQuery reward row: {row!r}')
  return {'block_timestamp': time, 'token_denom': denom, 'token_amount': str(amount)}


def cached_reward_row(row: 'BigQueryReward') -> RewardRow:
  """The cache's copy of a reward row."""
  return {
    'block_timestamp': row.block_timestamp,
    'token_denom': row.token_denom,
    'token_amount': row.token_amount,
  }


def parse_row(row: RewardRow) -> Bonus:
  asset, amount = parse_denom_amount(row['token_denom'], row['token_amount'])
  return Bonus(
    time=row['block_timestamp'],
    asset=asset,
    amount=amount,
  )


@dataclass
class BigQueryHistory(SDK):
  address: str
  client: bigquery.Client = field(default_factory=bigquery.Client)
  max_cost_usd: float = 0.10
  cache: 'HistoryCache | None' = None

  @classmethod
  def of(
    cls,
    address: str,
    client: bigquery.Client | None = None,
    cache: 'HistoryCache | None' = None,
  ):
    if client is None:
      client = bigquery_client()
    if client is not None:
      return cls(address=address, client=client, cache=cache)

  @SDK.method
  async def reward_distributions(
    self,
    start: datetime | None = None,
    end: datetime | None = None,
  ):
    """Fetch trading reward distributions from BigQuery."""
    if self.cache is not None and self.cache.bigquery_has_cache(self.address):
      cached_rows = self.cache.read_bigquery_rewards(self.address)
      rewards = [parse_row(cached_reward_row(row)) for row in cached_rows]
      return [
        reward for reward in rewards if in_window(reward.time, start=start, end=end)
      ]

    query = f"""
      SELECT
        block_timestamp,
        recipient,
        token_amount,
        token_denom
      FROM
        `numia-data.dydx_mainnet.dydx_reward_distribution`
      WHERE
        recipient = '{self.address}'
    """
    try:
      results, _ = await run_query_with_cost_async(
        self.client, query, max_cost_usd=self.max_cost_usd
      )
    except requests.ConnectionError as e:
      raise NetworkError(*e.args) from e

    rows = [reward_row(row) for row in results]
    if self.cache is not None:
      self.cache.write_bigquery_rewards(
        self.address,
        [
          (row['block_timestamp'], row['token_denom'], row['token_amount'])
          for row in rows
        ],
      )

    rewards = [parse_row(row) for row in rows]
    return [
      reward for reward in rewards if in_window(reward.time, start=start, end=end)
    ]

  async def history(
    self,
    start: datetime | None = None,
    end: datetime | None = None,
  ):
    rewards = await self.reward_distributions(start, end)
    id = source_id('bigquery')
    return [
      HistoryRecord(
        observations=[r], provenance={'source': 'api', 'service': 'bigquery', 'id': id}
      )
      for r in rewards
    ]


def bigquery_client(providers: ProvidersConfig | None = None) -> BigQueryClient | None:
  from google.auth.exceptions import DefaultCredentialsError

  provider = (providers or {}).get('bigquery')
  try:
    if provider is None:
      return bigquery.Client()
    credentials = gcloud.service_account_credentials(provider['credentials_path'])
    return bigquery.Client(credentials=credentials)
  except DefaultCredentialsError:
    ...
