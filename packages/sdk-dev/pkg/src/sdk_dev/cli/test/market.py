"""CLI entry point for market integration tests."""

import typer
from typing_extensions import Annotated

from .runner import run_suite


def test_market(
  accounts: Annotated[
    str,
    typer.Option(help='Path to the accounts configuration file'),
  ] = 'sdk.test.toml',
):
  """Test market implementations against their live APIs."""
  run_suite('market', accounts)
