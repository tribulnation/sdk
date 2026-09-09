"""CLI entry point for wallet integration tests."""

import typer
from typing_extensions import Annotated

from .runner import run_suite


def test_wallet(
  venue: Annotated[
    str | None,
    typer.Argument(help='Exact venue slug or configured account id'),
  ] = None,
  accounts: Annotated[
    str,
    typer.Option(help='Path to the accounts configuration file'),
  ] = 'sdk.test.toml',
):
  """Test wallet implementations against their live APIs."""
  run_suite('wallet', accounts, venue)
