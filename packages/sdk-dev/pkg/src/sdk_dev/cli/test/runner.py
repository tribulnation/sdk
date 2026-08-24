"""Shared pytest runner for live integration suites."""

from pathlib import Path

import pytest
import typer


def run_suite(name: str, accounts: str):
  """Run a named integration suite and propagate its exit status."""
  suite = Path(__file__).parents[2] / 'integration' / name / 'suite.py'
  exit_code = pytest.main(
    [
      str(suite),
      '--accounts-config',
      accounts,
      '--verbose',
      '--no-header',
      '--tb=line',
      '-ra',
    ]
  )
  if exit_code != pytest.ExitCode.OK:
    raise typer.Exit(code=int(exit_code))
