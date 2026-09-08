"""CLI entry point for report integration tests."""

from pathlib import Path

import typer
from typing_extensions import Annotated

from .runner import run


def test_report(
  venue: Annotated[
    str | None,
    typer.Argument(
      help='Only accounts whose id contains this (an account id or venue)'
    ),
  ] = None,
  accounts: Annotated[
    str,
    typer.Option(help='Path to the accounts configuration file'),
  ] = 'sdk.test.toml',
):
  """Test report implementations (snapshot and last-30-days history) against their live APIs."""
  suite = Path(__file__).parents[2] / 'integration' / 'report' / 'suite.py'
  args = [str(suite), '--accounts-config', accounts]
  if venue is not None:
    args += ['-k', venue]
  run(args)
