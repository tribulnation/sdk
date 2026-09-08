"""CLI entry point for market integration tests."""

from pathlib import Path

import typer
from typing_extensions import Annotated

from .runner import run

SUITES = Path(__file__).parents[2] / 'integration' / 'market'
HELPERS = {'__init__.py', 'conftest.py', 'suite.py', 'support.py'}


def venue_modules() -> list[Path]:
  """Every per-venue module under `integration/market/`, beside the shared `suite.py`."""
  return sorted(p for p in SUITES.glob('*.py') if p.name not in HELPERS)


def test_market(
  venue: Annotated[
    str | None,
    typer.Argument(
      help='Venue slug to run, e.g. `bitget`: its own module plus the shared suite '
      'narrowed to its accounts. Every venue when omitted.'
    ),
  ] = None,
  accounts: Annotated[
    str,
    typer.Option(help='Path to the accounts configuration file'),
  ] = 'sdk.test.toml',
):
  """Test market implementations against their live APIs."""
  suite = SUITES / 'suite.py'
  if venue is None:
    run([str(suite), *map(str, venue_modules()), '--accounts-config', accounts])
    return
  module = SUITES / f'{venue}.py'
  modules = [suite, module] if module.is_file() else [suite]
  run([*map(str, modules), '-k', venue, '--accounts-config', accounts])
