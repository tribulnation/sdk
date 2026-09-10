"""Fingerprintable, privacy-preserving results from existing read-only live suites."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys

from pydantic import Field
import pytest
from typing_extensions import Literal

from .consistency import StrictModel
from .repo import repo_root
from .support import load_impl_files

Group = Literal['all', 'public_mainnet', 'report_testnet']

# Required checks are explicit: optional venue-specific tests and skips cannot
# silently replace required evidence. No trading or transfer methods run here.
TESTS: dict[str, dict[str, tuple[str, ...]]] = {
  'wallet': {
    'deposit_methods': (
      'test_deposit_methods_can_be_fetched',
      'test_deposit_methods_not_empty',
    ),
    'withdrawal_methods': (
      'test_withdrawal_methods_can_be_fetched',
      'test_withdrawal_methods_not_empty',
    ),
  },
  'earn': {
    'instruments': ('test_instruments_can_be_fetched', 'test_instruments_not_empty'),
  },
  'report': {
    'snapshot': (
      'test_snapshot_can_be_fetched',
      'test_snapshot_time_is_tz_aware',
      'test_snapshot_balances_are_finite_decimals',
    ),
    'history': (
      'test_history_can_be_fetched',
      'test_history_times_are_tz_aware_and_within_bounds',
      'test_history_provenance_is_valid',
    ),
  },
}


class Outcome(StrictModel):
  """Only aggregate test outcomes; never node IDs, raw errors or account records."""

  id: str
  network: Literal['mainnet', 'testnet'] = 'mainnet'
  passed: int = Field(default=0, ge=0)
  failed: int = Field(default=0, ge=0)
  skipped: int = Field(default=0, ge=0)


class Payload(StrictModel):
  """One package's supported non-market reads on one selected mainnet account."""

  version: Literal[2] = 2
  scope: Literal['surfaces'] = 'surfaces'
  venue: str
  account_venue: str
  private_account_venue: str | None = None
  completed: bool
  checks: list[Outcome]


def inventory(root: Path, venue: str) -> dict[str, Path]:
  """Reconstruct required tests from supported read methods, not recorded outcomes."""
  impl = load_impl_files(root / 'packages/impl').get(venue)
  if impl is None or venue.endswith('_testnet'):
    raise ValueError('Unknown mainnet implementation')
  checks: dict[str, Path] = {}
  for surface, methods in TESTS.items():
    support = impl.support.get(surface)
    if support is None or support.support == 'none':
      continue
    enabled = set(methods) if support.support == 'full' else set(support.methods or ())
    for method, tests in methods.items():
      if method in enabled:
        for test in tests:
          checks[f'{surface}.{test}'] = (
            Path(__file__).parent / 'integration' / surface / 'suite.py'
          )
  if not checks:
    raise ValueError('No supported non-market read checks')
  return checks


def group_inventory(root: Path, venue: str, group: Group) -> dict[str, Path]:
  """The approved split applies only to Deribit, never to market consistency."""
  checks = inventory(root, venue)
  if group == 'all':
    return checks
  if venue != 'deribit' or group not in ('public_mainnet', 'report_testnet'):
    raise ValueError('Unsupported split qualification')
  return {
    id: path
    for id, path in checks.items()
    if id.startswith('report.') == (group == 'report_testnet')
  }


def verify_payload(payload: dict[str, object], *, root: Path):
  """Reject missing, duplicate, skipped, failed or non-mainnet qualification."""
  report = Payload.model_validate(payload)
  expected = inventory(root, report.venue)
  if report.account_venue != report.venue or not report.completed:
    raise ValueError('Surface evidence did not complete on the requested mainnet venue')
  split = report.private_account_venue is not None
  if split and (
    report.venue != 'deribit' or report.private_account_venue != 'deribit_testnet'
  ):
    raise ValueError('Only Deribit private Report checks permit testnet qualification')
  actual = {check.id for check in report.checks}
  if len(actual) != len(report.checks) or actual != set(expected):
    raise ValueError('Surface evidence inventory is incomplete or duplicated')
  if any(check.passed != 1 or check.failed or check.skipped for check in report.checks):
    raise ValueError('Required surface checks must pass without skips')
  for check in report.checks:
    expected_network = (
      'testnet' if split and check.id.startswith('report.') else 'mainnet'
    )
    if check.network != expected_network:
      raise ValueError('Surface check network does not match the approved scope')


class Recorder:
  """Discard pytest details and record only fixed test IDs and phase outcomes."""

  def __init__(
    self, checks: dict[str, Path], *, network: Literal['mainnet', 'testnet'] = 'mainnet'
  ):
    self.root = Path.cwd()
    self.checks = {id: Outcome(id=id, network=network) for id in checks}
    self.lookup = {(str(path), id.split('.', 1)[1]): id for id, path in checks.items()}

  def pytest_configure(self, config: pytest.Config):
    """Pytest node paths are relative to its root, which may differ from cwd."""
    self.root = config.rootpath

  def pytest_runtest_logreport(self, report: pytest.TestReport):
    """Setup/teardown failures count too; successful setup is not a passing test."""
    path, name = report.nodeid.split('::', 1)
    key = self.lookup.get((str((self.root / path).resolve()), name.split('[', 1)[0]))
    if key is None:
      return
    check = self.checks[key]
    if report.failed:
      check.failed += 1
    elif report.skipped:
      check.skipped += 1
    elif report.when == 'call' and report.passed:
      check.passed += 1


def run_worker(
  venue: str, account: str, accounts: Path, group: Group = 'all'
) -> dict[str, object]:
  """Run real suites in an isolated process; capture and discard private diagnostics."""
  checks = group_inventory(repo_root(), venue, group)
  recorder = Recorder(
    checks, network='testnet' if group == 'report_testnet' else 'mainnet'
  )
  args = [f'{path}::{id.split(".", 1)[1]}' for id, path in checks.items()]
  args += [
    '--accounts-config',
    str(accounts),
    '--sdk-venue',
    account,
    '-p',
    'no:terminal',
    '-p',
    'no:cacheprovider',
    '-o',
    'addopts=',
  ]
  # Account parsing is identical to the consistency CLI. Validate identity here
  # too, before pytest can use a selector that accidentally matches another venue.
  from .cli.results import configured_sdk, select_account

  sdk = configured_sdk(accounts)
  selected = select_account(
    sdk, 'deribit_testnet' if group == 'report_testnet' else venue, account
  )
  with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
    result = pytest.main(args, plugins=[recorder])
  return Payload(
    venue=venue,
    account_venue=sdk.all_accounts[selected].venue,
    completed=result == pytest.ExitCode.OK,
    checks=list(recorder.checks.values()),
  ).model_dump(mode='json')


def collect(
  venue: str, account: str, accounts: Path, group: Group = 'all'
) -> dict[str, object]:
  """Bound suite execution; worker crashes/timeouts remain sanitized failed evidence."""
  checks = group_inventory(repo_root(), venue, group)
  failed = Payload(
    venue=venue,
    account_venue=venue,
    completed=False,
    checks=[Outcome(id=id, failed=1) for id in checks],
  ).model_dump(mode='json')
  try:
    result = subprocess.run(
      [
        sys.executable,
        '-m',
        'sdk_dev.surface_evidence',
        venue,
        account,
        str(accounts.resolve()),
        group,
      ],
      cwd=repo_root(),
      capture_output=True,
      text=True,
      timeout=1800,
      env={**os.environ, 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1', 'PYTEST_ADDOPTS': ''},
    )
    if result.returncode != 0:
      return failed
    return Payload.model_validate_json(result.stdout).model_dump(mode='json')
  except (subprocess.SubprocessError, OSError, ValueError):
    return failed


def collect_deribit(
  account: str, testnet_account: str, accounts: Path
) -> dict[str, object]:
  """Combine mainnet metadata and testnet private reads without laundering networks."""
  public = Payload.model_validate(
    collect('deribit', account, accounts, 'public_mainnet')
  )
  private = Payload.model_validate(
    collect('deribit', testnet_account, accounts, 'report_testnet')
  )
  return Payload(
    venue='deribit',
    account_venue=public.account_venue,
    private_account_venue=private.account_venue,
    completed=public.completed and private.completed,
    checks=[*public.checks, *private.checks],
  ).model_dump(mode='json')


if __name__ == '__main__':
  try:
    group = sys.argv[4] if len(sys.argv) > 4 else 'all'
    if group not in ('all', 'public_mainnet', 'report_testnet'):
      raise ValueError('Unknown qualification group')
    print(json.dumps(run_worker(sys.argv[1], sys.argv[2], Path(sys.argv[3]), group)))
  except Exception:
    # Never let configuration validation or private fixture errors reach stdout.
    sys.exit(1)
