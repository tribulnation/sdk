from typing_extensions import Literal as _Literal, Annotated as _Annotated
from dataclasses import dataclass as _dataclass
import pydantic as _pydantic


def resolve_env_var(value: str | None, *, require: bool) -> str | None:
  """Resolve an environment variable if the value is in the form $ENV_VAR."""
  import os
  if value is not None and value.startswith('$'):
    var = value.removeprefix('$')
    if (resolved := os.getenv(var)) is None and require:
      raise ValueError(f'Environment variable {var} is not set')
    return resolved
  return value

@_dataclass(kw_only=True)
class BaseAccount:
  public: bool = False
  """Whether to allow public usage (i.e. whether unset credentials are OK)."""
  def verify_env_vars(self):
    """Verify that all required environment variables are set."""
    raise NotImplementedError('Subclasses must implement verify_env_vars()')


@_dataclass
class Dydx(BaseAccount):
  venue: _Literal['dydx', 'dydx_testnet'] = 'dydx'
  address: str = '$DYDX_ADDRESS'
  """Account address (`dydx1...`)"""
  mnemonic: str = '$DYDX_MNEMONIC'
  """Account mnemonic (12-24 words)"""
  parent_subaccount: int = 0
  """dYdX parent subaccount number"""

  @property
  def resolved_address(self) -> str | None:
    return resolve_env_var(self.address, require=not self.public)

  @property
  def resolved_mnemonic(self) -> str | None:
    return resolve_env_var(self.mnemonic, require=not self.public)

  def verify_env_vars(self):
    self.resolved_address
    self.resolved_mnemonic


@_dataclass
class Hyperliquid(BaseAccount):
  venue: _Literal['hyperliquid', 'hyperliquid_testnet'] = 'hyperliquid'
  address: str = '$HYPERLIQUID_ADDRESS'
  """Wallet address (`0x...`). Read-only if no private key is provided."""
  private_key: str = '$HYPERLIQUID_PRIVATE_KEY'
  """Wallet private key (`0x...`)"""

  @property
  def resolved_address(self) -> str | None:
    return resolve_env_var(self.address, require=not self.public)

  @property
  def resolved_private_key(self) -> str | None:
    return resolve_env_var(self.private_key, require=not self.public)

  def verify_env_vars(self):
    self.resolved_address
    self.resolved_private_key


@_dataclass
class Mexc(BaseAccount):
  venue: _Literal['mexc'] = 'mexc'
  api_key: str = '$MEXC_API_KEY'
  """MEXC API key"""
  api_secret: str = '$MEXC_API_SECRET'
  """MEXC API secret"""
  validate: bool = True
  """Whether to type-validate incoming responses."""

  @property
  def resolved_api_key(self) -> str | None:
    return resolve_env_var(self.api_key, require=not self.public)

  @property
  def resolved_api_secret(self) -> str | None:
    return resolve_env_var(self.api_secret, require=not self.public)
  
  def verify_env_vars(self):
    self.resolved_api_key
    self.resolved_api_secret


@_dataclass
class Bitget(BaseAccount):
  venue: _Literal['bitget'] = 'bitget'
  access_key: str = '$BITGET_ACCESS_KEY'
  """Bitget API access key"""
  secret_key: str = '$BITGET_SECRET_KEY'
  """Bitget API secret key"""
  passphrase: str = '$BITGET_PASSPHRASE'
  """Bitget API passphrase"""
  validate: bool = True
  """Whether to type-validate incoming responses."""

  @property
  def resolved_access_key(self) -> str | None:
    return resolve_env_var(self.access_key, require=not self.public)

  @property
  def resolved_secret_key(self) -> str | None:
    return resolve_env_var(self.secret_key, require=not self.public)

  @property
  def resolved_passphrase(self) -> str | None:
    return resolve_env_var(self.passphrase, require=not self.public)

  def verify_env_vars(self):
    self.resolved_access_key
    self.resolved_secret_key
    self.resolved_passphrase

@_dataclass
class Binance(BaseAccount):
  venue: _Literal['binance'] = 'binance'
  api_key: str = '$BINANCE_API_KEY'
  """Binance API key"""
  api_secret: str = '$BINANCE_API_SECRET'
  """Binance API secret"""
  validate: bool = True
  """Whether to type-validate incoming responses."""

  @property
  def resolved_api_key(self) -> str | None:
    return resolve_env_var(self.api_key, require=not self.public)

  @property
  def resolved_api_secret(self) -> str | None:
    return resolve_env_var(self.api_secret, require=not self.public)

  def verify_env_vars(self):
    self.resolved_api_key
    self.resolved_api_secret


@_dataclass
class Evm(BaseAccount):
  Venue = _Literal['ethereum', 'arbitrum', 'polygon', 'bnb-chain', 'base', 'avalanche', 'optimism']
  
  venue: Venue
  address: str = '$EVM_ADDRESS'
  """Wallet address (`0x...`)"""

  @property
  def resolved_address(self) -> str | None:
    return resolve_env_var(self.address, require=not self.public)
  
  def verify_env_vars(self):
    self.resolved_address


Account = _Annotated[
  Dydx | Hyperliquid | Mexc | Bitget | Binance | Evm,
  _pydantic.Discriminator ('venue')
]
