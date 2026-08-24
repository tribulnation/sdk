"""CLI entry point for earn integration tests."""

import typer
from typing_extensions import Annotated

from .runner import run_suite


def test_earn(
  accounts: Annotated[
    str,
    typer.Option(help='Path to the accounts configuration file'),
  ] = 'sdk.test.toml',
):
  """Test earn implementations against their live APIs."""
  run_suite('earn', accounts)
