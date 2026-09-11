"""All supported read suites must pass; omitted cases and forged skips fail closed."""

from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
from unittest.mock import Mock

import pytest
from typing_extensions import Literal

from sdk_dev import read_evidence as evidence
from sdk_dev.cli import results
from sdk_dev.repo import repo_root


def passing(venue: str) -> evidence.Payload:
  """Synthetic results are used only to exercise the offline verifier."""
  return evidence.Payload(
    venue=venue,
    account_venue=venue,
    bitget_uta=True if venue == 'bitget' else None,
    completed=True,
    checks=[
      evidence.Outcome(
        id=id, passed=0 if case.exclusion else 1, exclusion=case.exclusion
      )
      for id, case in evidence.inventory(repo_root(), venue).items()
    ],
  )


@pytest.mark.parametrize('venue', results.required_venues(repo_root(), 'sdk'))
def test_all_implementations_have_complete_read_inventories(venue: str):
  """Every declared implementation has a nonempty independently checked inventory."""
  report = passing(venue)
  evidence.verify_payload(report.model_dump(mode='json'), root=repo_root())


def test_market_packages_require_account_surfaces_too():
  """Market success does not replace Wallet/Earn/Report qualification."""
  cases = evidence.inventory(repo_root(), 'binance')
  assert {case.surface for case in cases.values()} == {
    'market',
    'wallet',
    'earn',
    'report',
  }
  assert results.required_scopes(repo_root(), 'binance') == ['surfaces', 'consistency']
  assert results.required_scopes(repo_root(), 'ethereum') == ['surfaces']
  methods = {case.method for case in cases.values() if not case.exclusion}
  assert {'rules', 'funding_rates', 'depth_stream', 'perp_stats'} <= methods


def test_parameterized_missing_duplicate_failed_and_skipped_cases_block():
  """Per-market outcomes cannot be replaced with an aggregate pass count."""
  good = passing('binance')
  for checks in (good.checks[:-1], [*good.checks, good.checks[0]]):
    bad = good.model_copy(update={'checks': checks})
    with pytest.raises(ValueError):
      evidence.verify_payload(bad.model_dump(mode='json'), root=repo_root())
  for values in (
    {'passed': 0},
    {'passed': 2},
    {'failed': 1},
    {'skipped': 1},
    {'exclusion': 'unsupported'},
    {'network': 'testnet'},
  ):
    bad = good.model_copy(deep=True)
    index = next(i for i, row in enumerate(bad.checks) if row.exclusion is None)
    bad.checks[index] = bad.checks[index].model_copy(update=values)
    with pytest.raises(ValueError):
      evidence.verify_payload(bad.model_dump(mode='json'), root=repo_root())


def test_exclusions_are_specific_and_never_passes():
  """Retention, spot-only methods and known unsupported streams are explicit."""
  hl = passing('hyperliquid')
  exclusions = [row for row in hl.checks if row.exclusion == 'retention_single_page']
  assert len(exclusions) == 2
  exclusions[0].passed = 1
  with pytest.raises(ValueError):
    evidence.verify_payload(hl.model_dump(mode='json'), root=repo_root())
  mexc = evidence.inventory(repo_root(), 'mexc')
  assert sum(case.exclusion == 'unsupported_perp_stream' for case in mexc.values()) == 1
  assert any(
    case.test == 'test_mexc_history_sources' and not case.exclusion
    for case in mexc.values()
  )


def test_deribit_split_and_legacy_reports():
  """The approved network split survives without allowing old narrow evidence."""
  report = passing('deribit')
  report.private_account_venue = 'deribit_testnet'
  for row in report.checks:
    if row.id.startswith('report.'):
      row.network = 'testnet'
  evidence.verify_payload(report.model_dump(mode='json'), root=repo_root())
  legacy = report.model_dump(mode='json')
  legacy['version'] = 2
  with pytest.raises(ValueError):
    evidence.verify_payload(legacy, root=repo_root())
  report.checks[0].network = 'testnet'
  with pytest.raises(ValueError):
    evidence.verify_payload(report.model_dump(mode='json'), root=repo_root())
  with pytest.raises(ValueError):
    evidence.group_inventory(repo_root(), 'binance', 'report_testnet')


@pytest.mark.parametrize(
  'venue', ['binance', 'bitget', 'kraken', 'hyperliquid', 'mexc', 'ethereum']
)
def test_real_pytest_collection_matches_inventory_without_network(
  venue: str,
  tmp_path: Path,
  monkeypatch: pytest.MonkeyPatch,
):
  """Collect real suites without running fixtures or needing any credentials."""
  accounts = tmp_path / 'accounts.toml'
  accounts.write_text(
    f'[accounts.local]\nvenue = "{venue}"\n'
    + ('uta = true\n' if venue == 'bitget' else '')
  )
  monkeypatch.setenv('SDK_DEV_ACCOUNTS_CONFIG', str(accounts))
  monkeypatch.setenv('SDK_DEV_ACCOUNT_ID', 'local')
  monkeypatch.setenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', '1')
  cases = evidence.inventory(repo_root(), venue)
  recorder = evidence.Recorder(cases, 'local')
  args = sorted({f'{case.path}::{case.test}' for case in cases.values()})
  args += [
    '--accounts-config',
    str(accounts),
    '--sdk-venue',
    'local',
    '--collect-only',
    '-p',
    'no:cacheprovider',
    '-o',
    'addopts=',
  ]
  output = io.StringIO()
  with redirect_stdout(output), redirect_stderr(output):
    code = pytest.main(args, plugins=[recorder])
  assert code == pytest.ExitCode.OK, output.getvalue()
  assert len(recorder.nodes) == sum(case.exclusion is None for case in cases.values())


def test_recorded_failures_do_not_export_account_details(tmp_path: Path):
  """Teardown and skipped fixtures block, while private diagnostics are discarded."""
  case = evidence.Case(surface='earn', path=tmp_path / 'suite.py', test='test_read')
  recorder = evidence.Recorder({case.id: case}, 'SECRET-ACCOUNT')
  node = 'suite.py::test_read[SECRET-ACCOUNT]'
  recorder.nodes[node] = case.id
  phases: list[tuple[Literal['call', 'teardown'], Literal['passed', 'failed']]] = [
    ('call', 'passed'),
    ('teardown', 'failed'),
  ]
  for when, outcome in phases:
    report = pytest.TestReport(
      nodeid=node,
      location=('suite.py', 0, 'test_read'),
      keywords={},
      outcome=outcome,
      when=when,
      longrepr='SECRET-BALANCE',
    )
    recorder.pytest_runtest_logreport(report)
  row = recorder.checks[case.id]
  assert row.passed == 1 and row.failed == 1
  assert 'SECRET' not in row.model_dump_json()


def test_release_demands_both_scopes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
  """Even passing consistency cannot satisfy the independent read-suite requirement."""
  from typer.testing import CliRunner

  check = Mock(side_effect=ValueError('missing read evidence'))
  monkeypatch.setattr(results, 'verify_one', check)
  result = CliRunner().invoke(
    results.app,
    ['release', 'binance', '--reports', str(tmp_path), '--catalogue', str(tmp_path)],
  )
  assert result.exit_code == 1
  assert check.call_args.args[1] == tmp_path / 'binance/surfaces'


def test_scope_substitution_is_rejected_before_test_validation(
  tmp_path: Path,
  monkeypatch: pytest.MonkeyPatch,
):
  """A valid report of the other scope cannot satisfy a required report path."""
  from sdk_dev import evidence as fingerprints

  monkeypatch.setattr(
    fingerprints, 'verify_report', Mock(return_value={'venue': 'binance'})
  )
  with pytest.raises(ValueError, match='expected surfaces'):
    results.verify_one(
      repo_root(), tmp_path, tmp_path, venue='binance', scope='surfaces'
    )
  monkeypatch.setattr(
    fingerprints,
    'verify_report',
    Mock(
      return_value={
        'venue': 'binance',
        'scope': 'surfaces',
      }
    ),
  )
  with pytest.raises(ValueError, match='expected consistency'):
    results.verify_one(
      repo_root(), tmp_path, tmp_path, venue='binance', scope='consistency'
    )


def test_recording_worker_does_not_export_crashes(monkeypatch: pytest.MonkeyPatch):
  """A crashed worker cannot leak its output or produce complete evidence."""
  from types import SimpleNamespace

  monkeypatch.setattr(
    evidence.subprocess,
    'run',
    Mock(
      return_value=SimpleNamespace(
        returncode=1,
        stdout='PRIVATE',
        stderr='PRIVATE',
      )
    ),
  )
  payload = evidence.collect('binance', 'private-account', Path('accounts.toml'))
  assert 'PRIVATE' not in str(payload)
  with pytest.raises(ValueError):
    evidence.verify_payload(payload, root=repo_root())
