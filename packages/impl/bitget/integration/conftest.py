"""Shared pytest configuration for the Bitget UTA-detection integration test."""

from pathlib import Path
import os

from dotenv import load_dotenv
import pytest

ACCOUNTS_CONFIG_ENV = 'SDK_DEV_ACCOUNTS_CONFIG'
"""Env var `sdk-dev`'s `cli/test/bitget.py` sets to the accounts config path (must match it
literally, since sdk-dev doesn't depend on the bitget package). Avoids a second
`--accounts-config` pytest option, which would collide with `sdk_dev.integration.conftest`'s
when both are loaded in the same session, e.g. a plain `pytest` run at the repo root."""


def pytest_configure(config: pytest.Config):
  """Load credentials from the accounts configuration directory."""
  accounts = os.environ.get(ACCOUNTS_CONFIG_ENV, 'sdk.test.toml')
  dotenv = Path(accounts).expanduser().resolve().parent / '.env'
  load_dotenv(dotenv_path=dotenv)
