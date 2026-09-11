"""Record every applicable read-only live suite without exporting account data."""

import ast
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
from .integration.market.public import READS
from .integration.market.support import CASES
from .repo import repo_root
from .support import load_impl_files
from .surface_evidence import Group, TESTS


class Case(StrictModel):
  """A public test identity, its source and expected parameterization."""

  surface: str
  path: Path
  test: str
  market: str | None = None
  method: str | None = None
  exclusion: str | None = None

  @property
  def id(self) -> str:
    """Never include the local account alias in recorded identifiers."""
    return f'{self.surface}.{self.test}' + json.dumps([self.market, self.method])


class Outcome(StrictModel):
  """One parameterized test, with only counters and a policy exclusion code."""

  id: str
  network: Literal['mainnet', 'testnet'] = 'mainnet'
  passed: int = Field(default=0, ge=0)
  failed: int = Field(default=0, ge=0)
  skipped: int = Field(default=0, ge=0)
  exclusion: str | None = None


class Payload(StrictModel):
  """All supported read suites for one selected account, not all account modes."""

  version: Literal[3] = 3
  scope: Literal['surfaces'] = 'surfaces'
  venue: str
  account_venue: str
  private_account_venue: str | None = None
  bitget_uta: bool | None = None
  completed: bool
  checks: list[Outcome]


def test_names(path: Path) -> set[str]:
  """Read suite inventories without importing fixtures or loading credentials."""
  return {
    node.name
    for node in ast.parse(path.read_text()).body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    and node.name.startswith('test_')
  }


def inventory(root: Path, venue: str) -> dict[str, Case]:
  """Reconstruct all required cases and narrow exclusions from committed support."""
  impl = load_impl_files(root / 'packages/impl').get(venue)
  if impl is None or venue.endswith('_testnet'):
    raise ValueError('Unknown mainnet implementation')
  base = root / 'packages/sdk-dev/pkg/src/sdk_dev/integration'
  cases: list[Case] = []
  for surface, methods in TESTS.items():
    support = impl.support.get(surface)
    if support is None or support.support == 'none':
      continue
    path = base / surface / 'suite.py'
    mapped = {test for tests in methods.values() for test in tests}
    extra: set[str] = {'test_mexc_history_sources'} if surface == 'report' else set()
    if test_names(path) != mapped | extra:
      raise ValueError(f'Unmapped live tests in {surface}')
    enabled = set(methods) if support.support == 'full' else set(support.methods or ())
    for method, tests in methods.items():
      for test in tests:
        cases.append(
          Case(
            surface=surface,
            path=path,
            test=test,
            exclusion=None if method in enabled else 'unsupported',
          )
        )
    if surface == 'report':
      cases.append(
        Case(
          surface=surface,
          path=path,
          test='test_mexc_history_sources',
          exclusion=None
          if venue == 'mexc' and 'history' in enabled
          else 'not_applicable',
        )
      )
  support = impl.support.get('market')
  if support is not None and support.support != 'none':
    references = CASES.get(venue, ())
    if not references:
      raise ValueError('Supported market implementation has no reference cases')
    enabled = (
      set(READS) | {'candles'}
      if support.support == 'full'
      else set(support.methods or ())
    )
    candle_path = base / 'market/suite.py'
    public_path = base / 'market/public.py'
    if test_names(public_path) != {'test_public_read'}:
      raise ValueError('Unmapped public market tests')
    for reference in references:
      for test in sorted(test_names(candle_path)):
        exclusion = None
        if 'candles' not in enabled:
          exclusion = 'unsupported'
        elif (
          test == 'test_window_straddling_two_pages_respects_contract'
          and reference.page is None
        ):
          exclusion = 'retention_single_page'
        cases.append(
          Case(
            surface='market',
            path=candle_path,
            test=test,
            market=reference.market_id,
            exclusion=exclusion,
          )
        )
      for method in READS:
        exclusion = None
        if reference.market_id.startswith('spot:') and method in {
          'index',
          'next_funding',
          'funding_rates',
          'perp_stats',
        }:
          exclusion = 'spot_only'
        elif method not in {'exchanges', 'markets'} and method not in enabled:
          exclusion = 'unsupported'
        elif (
          venue == 'mexc'
          and reference.market_id.startswith('perp:')
          and method == 'depth_stream'
        ):
          exclusion = 'unsupported_perp_stream'
        cases.append(
          Case(
            surface='market',
            path=public_path,
            test='test_public_read',
            market=reference.market_id,
            method=method,
            exclusion=exclusion,
          )
        )
    # New venue-specific modules must not silently disappear from qualification.
    modules = {path.name for path in (base / 'market').glob('*.py')}
    if modules - {
      '__init__.py',
      'conftest.py',
      'support.py',
      'suite.py',
      'public.py',
      'bitget.py',
    }:
      raise ValueError('Unmapped venue-specific market suite')
    if venue == 'bitget':
      for path in (
        base / 'market/bitget.py',
        root / 'packages/impl/bitget/integration/suite.py',
      ):
        for test in sorted(test_names(path)):
          cases.append(Case(surface='bitget', path=path, test=test))
  if not cases or len({case.id for case in cases}) != len(cases):
    raise ValueError('Missing or duplicate live test inventory')
  return {case.id: case for case in cases}


def group_inventory(root: Path, venue: str, group: Group) -> dict[str, Case]:
  """Split only Deribit public mainnet metadata from private testnet Report."""
  cases = inventory(root, venue)
  if group == 'all':
    return cases
  if venue != 'deribit':
    raise ValueError('Only Deribit permits split qualification')
  return {
    id: case
    for id, case in cases.items()
    if (case.surface == 'report') == (group == 'report_testnet')
  }


def verify_payload(payload: dict[str, object], *, root: Path):
  """Reject incomplete tests, unexpected skips, wrong scope and invented exclusions."""
  report = Payload.model_validate(payload)
  expected = inventory(root, report.venue)
  if not report.completed or report.account_venue != report.venue:
    raise ValueError('Read suites did not complete on the selected mainnet venue')
  split = report.private_account_venue is not None
  if split and (
    report.venue != 'deribit' or report.private_account_venue != 'deribit_testnet'
  ):
    raise ValueError('Only Deribit Report permits testnet evidence')
  if (report.venue == 'bitget') != (report.bitget_uta is not None):
    raise ValueError('Bitget qualification requires an explicit expected account mode')
  if len(report.checks) != len(expected) or {row.id for row in report.checks} != set(
    expected
  ):
    raise ValueError('Read-suite inventory is missing or duplicated')
  for row in report.checks:
    case = expected[row.id]
    network = 'testnet' if split and case.surface == 'report' else 'mainnet'
    if row.network != network or row.exclusion != case.exclusion:
      raise ValueError('Read-suite network or exclusion does not match policy')
    if case.exclusion is not None:
      if row.passed or row.failed or row.skipped:
        raise ValueError('Excluded checks must not be represented as executed tests')
    elif row.passed != 1 or row.failed or row.skipped:
      raise ValueError(f'Required read test did not pass: {row.id}')


class Recorder:
  """Match every collected parameterized case; discard private pytest diagnostics."""

  def __init__(
    self,
    cases: dict[str, Case],
    account: str,
    *,
    network: Literal['mainnet', 'testnet'] = 'mainnet',
  ):
    self.cases = cases
    self.account = account
    self.checks = {
      id: Outcome(id=id, network=network, exclusion=case.exclusion)
      for id, case in cases.items()
    }
    self.nodes: dict[str, str] = {}

  def pytest_collection_modifyitems(self, items: list[pytest.Item]):
    """Select exactly one node per required case, before any live fixture runs."""
    kept: list[pytest.Item] = []
    found: set[str] = set()
    for item in items:
      if not isinstance(item, pytest.Function):
        raise pytest.UsageError('Unexpected live test item')
      params = item.callspec.params if hasattr(item, 'callspec') else {}
      matches: list[str] = []
      for id, case in self.cases.items():
        if item.path.resolve() != case.path.resolve() or item.originalname != case.test:
          continue
        account_param = {
          'wallet': 'wallet_account',
          'earn': 'earn_account',
          'report': 'report_account',
          'bitget': 'account_id'
          if case.test == 'test_detect_uta'
          else 'market_account',
        }.get(case.surface)
        wanted = {account_param: self.account} if account_param else {}
        if case.market is not None:
          wanted['public_market' if case.method else 'candle_market'] = (
            f'{self.account}:{case.market}'
          )
        if case.method is not None:
          wanted['method'] = case.method
        if params == wanted:
          matches.append(id)
      if len(matches) != 1 or matches[0] in found:
        raise pytest.UsageError('Unexpected or duplicate live test parameterization')
      id = matches[0]
      found.add(id)
      if self.cases[id].exclusion is None:
        kept.append(item)
        self.nodes[item.nodeid] = id
    if found != set(self.cases):
      raise pytest.UsageError('Incomplete live test collection')
    items[:] = kept

  def pytest_runtest_logreport(self, report: pytest.TestReport):
    """Record setup/call/teardown outcomes without node IDs or exception text."""
    id = self.nodes.get(report.nodeid)
    if id is None:
      return
    row = self.checks[id]
    if report.failed:
      row.failed += 1
    elif report.skipped:
      row.skipped += 1
    elif report.when == 'call' and report.passed:
      row.passed += 1


def run_worker(
  venue: str, account: str, accounts: Path, group: Group = 'all'
) -> dict[str, object]:
  """Run the actual existing suites in an isolated, read-only pytest session."""
  from .cli.results import configured_sdk, select_account

  sdk = configured_sdk(accounts)
  selected = select_account(
    sdk, 'deribit_testnet' if group == 'report_testnet' else venue, account
  )
  configured = sdk.all_accounts[selected]
  mode = getattr(configured, 'uta', None) if venue == 'bitget' else None
  if venue == 'bitget' and (configured.public or not isinstance(mode, bool)):
    raise ValueError('Bitget requires a private account with expected uta mode')
  cases = group_inventory(repo_root(), venue, group)
  recorder = Recorder(
    cases, account, network='testnet' if group == 'report_testnet' else 'mainnet'
  )
  args = sorted({f'{case.path}::{case.test}' for case in cases.values()})
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
  os.environ['SDK_DEV_ACCOUNTS_CONFIG'] = str(accounts.resolve())
  os.environ['SDK_DEV_ACCOUNT_ID'] = account
  with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
    result = pytest.main(args, plugins=[recorder])
  return Payload(
    venue=venue,
    account_venue=configured.venue,
    bitget_uta=mode,
    completed=result == pytest.ExitCode.OK,
    checks=list(recorder.checks.values()),
  ).model_dump(mode='json')


def collect(
  venue: str, account: str, accounts: Path, group: Group = 'all'
) -> dict[str, object]:
  """Keep worker failures private and bounded; never turn them into skipped passes."""
  failed = Payload(
    venue=venue, account_venue=venue, completed=False, checks=[]
  ).model_dump(mode='json')
  try:
    result = subprocess.run(
      [
        sys.executable,
        '-m',
        'sdk_dev.read_evidence',
        venue,
        account,
        str(accounts.resolve()),
        group,
      ],
      cwd=repo_root(),
      capture_output=True,
      text=True,
      timeout=3600,
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
  """Combine actual networks without laundering testnet into mainnet evidence."""
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
    venue, account, path, raw_group = sys.argv[1:]
    if raw_group not in ('all', 'public_mainnet', 'report_testnet'):
      raise ValueError('Invalid qualification group')
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
      payload = run_worker(venue, account, Path(path), raw_group)
    print(json.dumps(payload))
  except Exception:
    sys.exit(1)
