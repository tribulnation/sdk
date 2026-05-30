from tribulnation.dydx.report.util import source_id
from typing_extensions import AsyncIterable, TYPE_CHECKING
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from tribulnation.sdk.reporting import ProvidersConfig, Report as _Report, Record, Snapshot

from dydx import Dydx
from dydx.chain import (
  Chain,
  DYDX_COMET_KINGNODES_ARCHIVE_RPC_URL,
  DYDX_GRPC_KINGNODES_ARCHIVE_HOST,
)
from .config import DydxConfig
from .history import History
from .history.constants import (
  DEFAULT_FILLS_SOURCE,
  DEFAULT_SUBACCOUNT_TRANSFERS_SOURCE,
  DEFAULT_FUNDING_SOURCE,
  DEFAULT_IBC_WALLET_TRANSFERS_SOURCE,
  DEFAULT_MEGAVAULT_SOURCE,
  DEFAULT_CHAIN_FEES_SOURCE,
  DEFAULT_COMMUNITY_TREASURY_DISTRIBUTIONS_SOURCE,
  DEFAULT_TRADING_REWARDS_SOURCE,
  DEFAULT_STAKING_SOURCE,
  DEFAULT_WALLET_TRANSFERS_SOURCE,
)
from .snapshots import Snapshots
from .util import source_id

if TYPE_CHECKING:
  from google.cloud.bigquery import Client as BigQueryClient

@dataclass(frozen=True)
class Report(Snapshots, History, _Report):
  """dYdX reporting client with snapshots and history."""
  address: str
  client: Dydx = field(default_factory=lambda: Dydx.mainnet(public=True))
  config: DydxConfig = field(default_factory=lambda: {})
  bigquery: 'BigQueryClient | None' = None
  
  @classmethod
  def new(
    cls, address: str, *,
    config: DydxConfig | None = None,
    providers: ProvidersConfig | None = None,
  ) -> 'Report':
    """
    Create a dYdX mainnet reporting client.

    Args:
      address: dYdX wallet address to report.
      config: dYdX node endpoint and history source configuration.
      providers: Shared reporting provider credentials.

    Raises:
      ValueError: A BigQuery-backed source is selected but BigQuery credentials are unavailable.
    """
    import os
    config = config or {}
    node = config.get('node', {})
    bigquery = bigquery_client(providers)
    validate_bigquery_sources(config, bigquery)
    comet_base_url = node.get('comet_base_url') or os.environ.get('DYDX_COMET_RPC_URL') or DYDX_COMET_KINGNODES_ARCHIVE_RPC_URL
    grpc_host = node.get('grpc_host') or os.environ.get('DYDX_GRPC_HOST') or DYDX_GRPC_KINGNODES_ARCHIVE_HOST

    chain = Chain.new(
      comet_base_url=comet_base_url,
      grpc_host=grpc_host,
      grpc_port=node.get('grpc_port', 443),
      grpc_ssl=node.get('grpc_ssl', True),
      validate=node.get('validate', True),
    )
    client = Dydx.new(chain=chain, public=True)
    return cls(address=address, client=client, config=config, bigquery=bigquery)


  async def records(self, start: datetime | None = None, end: datetime | None = None) -> AsyncIterable[Record]:
    start_time: datetime | None = None
    async for record in self.history(start, end):
      yield record
      for obs in record.observations:
        if obs.time is not None:
          start_time = obs.time if start_time is None else min(start_time, obs.time)

    if start is None and start_time is not None:
      start_time = start_time.astimezone()
      snapshot_time = start_time - timedelta(days=1)
      yield Record(
        snapshots=[Snapshot(time=snapshot_time, balances={})],
        provenance={
          'source': 'derived',
          'id': source_id('dydx'),
          'details': {
            'note': 'dYdX full-history reports imply zero balances before the first observed transaction.',
          }
        },
      )

    if end is None:
      yield await self.snapshots()

def bigquery_client(providers: ProvidersConfig | None) -> 'BigQueryClient | None':
  """
  Create a BigQuery client from explicit provider config or Google ADC.

  Args:
    providers: Shared reporting provider credentials.

  Returns:
    A BigQuery client when explicit credentials or Application Default Credentials are available.

  Raises:
    ValueError: `providers.bigquery` is present without `credentials_path`.
  """
  from google.auth.exceptions import DefaultCredentialsError
  from google.cloud import bigquery

  provider = (providers or {}).get('bigquery')
  try:
    if provider is None:
      return bigquery.Client()
    credentials_path = provider.get('credentials_path')
    if credentials_path is None:
      raise ValueError(
        'providers.bigquery requires credentials_path. '
        'Omit providers.bigquery to use GOOGLE_APPLICATION_CREDENTIALS or Google ADC.'
      )
    from google.oauth2 import service_account
    credentials = service_account.Credentials.from_service_account_file(credentials_path)
    return bigquery.Client(credentials=credentials)
  except DefaultCredentialsError:
    return None

def validate_bigquery_sources(config: DydxConfig, bigquery: 'BigQueryClient | None'):
  """
  Ensure selected BigQuery-backed dYdX sources have an available provider.

  Args:
    config: dYdX reporting configuration.
    bigquery: BigQuery client created from provider config or ADC.

  Raises:
    ValueError: Any selected source requires BigQuery but no client is available.
  """
  if bigquery is not None:
    return
  sources = config.get('sources', {})
  bigquery_sources: list[str] = []
  if sources.get('fills', DEFAULT_FILLS_SOURCE) == 'bigquery':
    bigquery_sources.append('fills')
  if sources.get('subaccount_transfers', DEFAULT_SUBACCOUNT_TRANSFERS_SOURCE) == 'bigquery':
    bigquery_sources.append('subaccount_transfers')
  if sources.get('funding', DEFAULT_FUNDING_SOURCE) == 'bigquery':
    bigquery_sources.append('funding')
  if sources.get('chain_fees', DEFAULT_CHAIN_FEES_SOURCE) == 'bigquery':
    bigquery_sources.append('chain_fees')
  if sources.get('trading_rewards', DEFAULT_TRADING_REWARDS_SOURCE) == 'bigquery':
    bigquery_sources.append('trading_rewards')
  if sources.get('staking', DEFAULT_STAKING_SOURCE) == 'bigquery':
    bigquery_sources.append('staking')
  if sources.get('community_treasury_distributions', DEFAULT_COMMUNITY_TREASURY_DISTRIBUTIONS_SOURCE) == 'bigquery':
    bigquery_sources.append('community_treasury_distributions')
  if sources.get('megavault', DEFAULT_MEGAVAULT_SOURCE) == 'bigquery':
    bigquery_sources.append('megavault')
  if sources.get('ibc_wallet_transfers', DEFAULT_IBC_WALLET_TRANSFERS_SOURCE) == 'bigquery':
    bigquery_sources.append('ibc_wallet_transfers')
  if sources.get('wallet_transfers', DEFAULT_WALLET_TRANSFERS_SOURCE) == 'bigquery':
    bigquery_sources.append('wallet_transfers')
  if bigquery_sources:
    selected = ', '.join(bigquery_sources)
    raise ValueError(
      f'dYdX reporting sources require BigQuery but no BigQuery credentials were found: {selected}. '
      'Configure providers.bigquery.credentials_path, Google Application Default Credentials, '
      'or choose non-BigQuery sources where available.'
    )

Reporting = Report
