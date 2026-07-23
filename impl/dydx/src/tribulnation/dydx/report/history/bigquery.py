from dataclasses import dataclass, field
from datetime import datetime
from asyncer import asyncify
from google.cloud import bigquery
from google.cloud.bigquery import Client as BigQueryClient
import requests

from tribulnation.sdk import SDK, NetworkError
from tribulnation.sdk.reporting import Bonus, Record, source_id, ProvidersConfig
from tribulnation.dydx.core import parse_denom_amount
from .window import in_window

def estimate_query_cost(client: bigquery.Client, query: str, price_per_tib: float = 6.25) -> dict:
  """Estimate BigQuery on-demand cost without executing the query."""
  config = bigquery.QueryJobConfig(
  dry_run=True,
  use_query_cache=False,
  )
  job = client.query(query, job_config=config)

  bytes_processed = int(job.total_bytes_processed or 0)
  tib_processed = bytes_processed / 1024**4

  return {
    "bytes_processed": bytes_processed,
    "gib_processed": bytes_processed / 1024**3,
    "tib_processed": tib_processed,
    "estimated_cost_usd": tib_processed * price_per_tib,
  }

def run_query_with_cost(
  client: bigquery.Client,
  query: str,
  price_per_tib: float = 6.25,
  max_cost_usd: float | None = None,
) -> list[bigquery.Row]:
  """Run a query and return (results, cost_info)."""
  maximum_bytes_billed = None

  if max_cost_usd is not None:
    if max_cost_usd < 0:
      raise ValueError("max_cost_usd must be non-negative")

    maximum_bytes_billed = int(
      max_cost_usd / price_per_tib * 1024**4
    )

  config = bigquery.QueryJobConfig(
    maximum_bytes_billed=maximum_bytes_billed,
  )

  query_job = client.query(query, job_config=config)
  results = query_job.result()

  bytes_processed = query_job.total_bytes_processed or 0
  bytes_billed = query_job.total_bytes_billed or 0

  cost_info = {
    "job_id": query_job.job_id,
    "cache_hit": bool(query_job.cache_hit),
    "bytes_processed": bytes_processed,
    "gib_processed": bytes_processed / 1024**3,
    "bytes_billed": bytes_billed,
    "tib_billed": bytes_billed / 1024**4,
    "estimated_cost_usd": (
      bytes_billed / 1024**4 * price_per_tib
    ),
    "slot_millis": query_job.slot_millis,
  }

  return list(results), cost_info # type: ignore

run_query_with_cost_async = asyncify(run_query_with_cost)

def parse_row(row: bigquery.Row) -> Bonus:
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

  @classmethod
  def of(cls, address: str, client: bigquery.Client | None = None):
    if client is None:
      client = bigquery_client()
    if client is not None:
      return cls(address=address, client=client)

  @SDK.method
  async def reward_distributions(
    self, start: datetime | None = None, end: datetime | None = None,
  ):
    """Fetch trading reward distributions from BigQuery."""
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
      results, _ = await run_query_with_cost_async(self.client, query, max_cost_usd=self.max_cost_usd)
    except requests.ConnectionError as e:
      raise NetworkError(*e.args) from e

    rewards = [parse_row(row) for row in results]
    return [
      reward
      for reward in rewards
      if in_window(reward.time, start=start, end=end)
    ]

  
  async def history(
    self, start: datetime | None = None, end: datetime | None = None,
  ):
    rewards = await self.reward_distributions(start, end)
    id = source_id('bigquery')
    return [
      Record(observations=[r], provenance={'source': 'api', 'service': 'bigquery', 'id': id})
      for r in rewards
    ]


def bigquery_client(providers: ProvidersConfig | None = None) -> BigQueryClient | None:
  from google.auth.exceptions import DefaultCredentialsError
  provider = (providers or {}).get('bigquery')
  try:
    if provider is None:
      return bigquery.Client()
    from google.oauth2 import service_account
    credentials = service_account.Credentials.from_service_account_file(provider['credentials_path'])
    return bigquery.Client(credentials=credentials)
  except DefaultCredentialsError:
    ...
