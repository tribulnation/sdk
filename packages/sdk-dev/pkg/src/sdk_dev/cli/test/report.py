"""CLI entry point for report integration tests."""

from pathlib import Path

import typer
from typing_extensions import Annotated

from .runner import run


def test_report(
  venue: Annotated[
    str | None,
    typer.Argument(help='Exact venue slug or configured account id'),
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
    args += ['--sdk-venue', venue]
  run(args)
