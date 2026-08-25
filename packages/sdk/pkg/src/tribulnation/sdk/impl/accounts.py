from typing_extensions import Literal as _Literal, Annotated as _Annotated
from dataclasses import dataclass as _dataclass
from pathlib import Path as _Path
import tomllib as _tomllib
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
class Bit2Me(BaseAccount):
  venue: _Literal['bit2me'] = 'bit2me'
  api_key: str = '$BIT2ME_API_KEY'
  """Bit2Me API key"""
  api_secret: str = '$BIT2ME_SECRET_KEY'
  """Bit2Me API secret (note: the client reads `BIT2ME_SECRET_KEY`, not `BIT2ME_API_SECRET`)"""
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
  uta: bool | None = None
  """Is this account in UTA mode? If None, it will be auto-detected on first use."""

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
  secret_key: str = '$BINANCE_SECRET_KEY'
  """Binance API secret"""
  validate: bool = True
  """Whether to type-validate incoming responses."""

  @property
  def resolved_api_key(self) -> str | None:
    return resolve_env_var(self.api_key, require=not self.public)

  @property
  def resolved_secret_key(self) -> str | None:
    return resolve_env_var(self.secret_key, require=not self.public)

  def verify_env_vars(self):
    self.resolved_api_key
    self.resolved_secret_key


@_dataclass
class Evm(BaseAccount):
  Venue = _Literal[
    'ethereum',
    'arbitrum',
    'polygon',
    'bnb-chain',
    'base',
    'avalanche',
    'optimism',
    'hyperevm',
  ]

  venue: Venue
  address: str = '$EVM_ADDRESS'
  """Wallet address (`0x...`)"""

  @property
  def resolved_address(self) -> str | None:
    return resolve_env_var(self.address, require=not self.public)

  def verify_env_vars(self):
    self.resolved_address


Account = _Annotated[
  Dydx | Hyperliquid | Mexc | Bitget | Bit2Me | Binance | Evm,
  _pydantic.Discriminator('venue'),
]


def load_accounts(path: _Path | str) -> dict[str, Account]:
  """Load and validate accounts from a TOML file's `[accounts.<id>]` tables.

  Mirrors the fail-fast behavior expected of any accounts source: every parsed
  account has `verify_env_vars()` called immediately, so a missing required
  environment variable raises here rather than on first use.

  Args:
    path: Path to a TOML file with an `[accounts]` table, e.g.:
      ```toml
      [accounts.hl]
      venue = "hyperliquid"
      address = "$HYPERLIQUID_ADDRESS"
      private_key = "$HYPERLIQUID_PRIVATE_KEY"
      ```

  Returns:
    Accounts keyed by id, ready to pass as an SDK's `accounts` field.

  Raises:
    ValueError: If the file does not exist.
  """
  p = _Path(path)
  if not p.exists():
    raise ValueError(f'Config file not found at "{p}"')
  with open(p, 'rb') as f:
    data = _tomllib.load(f)
  accounts = _pydantic.TypeAdapter(dict[str, Account]).validate_python(
    data.get('accounts', {})
  )
  for acc in accounts.values():
    acc.verify_env_vars()
  return accounts
