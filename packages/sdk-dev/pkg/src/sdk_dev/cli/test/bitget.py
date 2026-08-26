"""CLI entry point for the Bitget UTA-detection integration test."""

from pathlib import Path
import os

import typer
from typing_extensions import Annotated

from .runner import run

SUITE = Path(__file__).parents[6] / 'impl' / 'bitget' / 'integration' / 'suite.py'
ACCOUNTS_CONFIG_ENV = 'SDK_DEV_ACCOUNTS_CONFIG'
"""Must match `impl/bitget/integration/conftest.py`; sdk-dev doesn't depend on the bitget
package, so the name can't be imported and shared directly."""


def test_bitget(
  accounts: Annotated[
    str,
    typer.Option(help='Path to the accounts configuration file'),
  ] = 'sdk.test.toml',
):
  """Test Bitget's UTA-mode auto-detection against its live accounts."""
  os.environ[ACCOUNTS_CONFIG_ENV] = accounts
  run([str(SUITE)])
