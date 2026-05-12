"""Shared live-test setup for the Tribulnation SDK."""

from pathlib import Path
import os

from dotenv import load_dotenv
import pytest

SDK_ROOT = Path(__file__).resolve().parents[1]
TRIBULNATION_ROOT = SDK_ROOT.parents[1]
TYPED_DEV_ROOT = TRIBULNATION_ROOT / 'private' / 'typed-dev'

ALIASES = {
  'dydx': {
    'DYDX_TESTNET_MNEMONIC': 'DYDX_MNEMONIC',
    'DYDX_TESTNET_ADDRESS': 'DYDX_ADDRESS',
  },
  'hyperliquid': {
    'HYPERLIQUID_TESTNET_PRIVATE_KEY': 'HYPERLIQUID_PRIVATE_KEY',
    'HYPERLIQUID_TESTNET_ADDRESS': 'HYPERLIQUID_ADDRESS',
  },
}

def load_venue_env(venue: str, *, required: tuple[str, ...] = ()) -> None:
  """Load a venue `.env` file from typed-dev and require selected names."""
  path = TYPED_DEV_ROOT / 'clients' / venue / '.env'
  if not path.exists():
    pytest.skip(f'Missing typed-dev credential file for {venue}')

  load_dotenv(path, override=False)
  for source, target in ALIASES.get(venue, {}).items():
    if target not in os.environ and source in os.environ:
      os.environ[target] = os.environ[source]

  missing = [name for name in required if not os.environ.get(name)]
  if missing:
    pytest.skip(f'Missing required environment variables for {venue}: {", ".join(missing)}')
