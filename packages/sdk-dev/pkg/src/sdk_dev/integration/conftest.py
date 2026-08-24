"""Shared pytest configuration for live SDK integration tests."""

from pathlib import Path

from dotenv import load_dotenv
import pytest
from typing_extensions import cast


def pytest_addoption(parser: pytest.Parser):
  """Register integration-test command-line options."""
  integration = parser.getgroup('sdk-dev')
  integration.addoption(
    '--accounts-config',
    default='sdk.test.toml',
    help='Path to the accounts configuration file.',
  )


def pytest_configure(config: pytest.Config):
  """Load credentials from the accounts configuration directory."""
  accounts = cast(str, config.getoption('accounts_config'))
  dotenv = Path(accounts).expanduser().resolve().parent / '.env'
  load_dotenv(dotenv_path=dotenv)
