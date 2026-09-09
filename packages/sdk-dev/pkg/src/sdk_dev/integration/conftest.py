"""Shared pytest configuration for live SDK integration tests."""

from pathlib import Path

from dotenv import load_dotenv
import pytest
from typing_extensions import cast
from .runtime import LOOP


def pytest_addoption(parser: pytest.Parser):
  """Register integration-test command-line options."""
  integration = parser.getgroup('sdk-dev')
  integration.addoption(
    '--accounts-config',
    default='sdk.test.toml',
    help='Path to the accounts configuration file.',
  )
  integration.addoption(
    '--sdk-venue',
    default=None,
    help='Exact venue slug or configured account id to test.',
  )


def pytest_configure(config: pytest.Config):
  """Load credentials from the accounts configuration directory."""
  accounts = cast(str, config.getoption('accounts_config'))
  dotenv = Path(accounts).expanduser().resolve().parent / '.env'
  load_dotenv(dotenv_path=dotenv)


def pytest_unconfigure(config: pytest.Config):
  """Close the session loop after all owned SDK contexts have exited."""
  if (loop := config.stash.get(LOOP, None)) is not None:
    loop.run_until_complete(loop.shutdown_asyncgens())
    loop.run_until_complete(loop.shutdown_default_executor())
    loop.close()
