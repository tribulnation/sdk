"""Shared pytest runner for live integration suites."""

from pathlib import Path

import pytest
import typer


def run(args: list[str]):
  """Run pytest with `args` plus the shared reporting flags, propagating its exit status."""
  exit_code = pytest.main([*args, '--verbose', '--no-header', '--tb=line', '-ra'])
  if exit_code != pytest.ExitCode.OK:
    raise typer.Exit(code=int(exit_code))


def run_suite(name: str, accounts: str):
  """Run a named sdk-dev integration suite and propagate its exit status."""
  suite = Path(__file__).parents[2] / 'integration' / name / 'suite.py'
  run([str(suite), '--accounts-config', accounts])
