"""Shared reporting provider configuration types."""

from typing_extensions import TypedDict, NotRequired


class BigQueryProviderConfig(TypedDict):
  """BigQuery provider configuration."""
  credentials_path: str
  """Path to a Google service-account JSON file. Defaults to Google ADC."""

class AlchemyProviderConfig(TypedDict):
  """Alchemy provider configuration."""
  api_key: str
  """Alchemy API key."""

class EtherscanProviderConfig(TypedDict):
  """Etherscan provider configuration."""
  api_key: str
  """Etherscan API key."""
  rate_limit: NotRequired[int]
  """Etherscan rate limit (calls per second)."""

class MoralisProviderConfig(TypedDict):
  """Moralis provider configuration."""
  api_key: str
  """Moralis API key. Defaults to `MORALIS_API_KEY`."""

class ProvidersConfig(TypedDict, total=False):
  """Shared provider credentials used by reporting clients."""
  bigquery: BigQueryProviderConfig
  """Google BigQuery provider configuration."""
  alchemy: AlchemyProviderConfig
  """Alchemy provider configuration."""
  etherscan: EtherscanProviderConfig
  """Etherscan provider configuration."""
  moralis: MoralisProviderConfig
  """Moralis provider configuration."""
