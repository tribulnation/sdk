"""Non-market release evidence preserves real suite failures without private data."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from typing_extensions import Literal

from sdk_dev import surface_evidence as evidence
from sdk_dev.cli import results
from sdk_dev.repo import repo_root


def passing(venue: str) -> dict[str, object]:
  """Build complete synthetic outcomes for offline-policy mutation tests."""
  return evidence.Payload(
    venue=venue,
    account_venue=venue,
    completed=True,
    checks=[
      evidence.Outcome(id=id, passed=1) for id in evidence.inventory(repo_root(), venue)
    ],
  ).model_dump(mode='json')


@pytest.mark.parametrize(
  'venue,count', [('ethereum', 6), ('kucoin', 12), ('deribit', 12)]
)
def test_nonmarket_packages_have_real_required_read_suites(venue: str, count: int):
  """Every supported surface contributes checks, with no placeholder market report."""
  payload = passing(venue)
  assert len(evidence.Payload.model_validate(payload).checks) == count
  evidence.verify_payload(payload, root=repo_root())


def test_failed_skipped_duplicate_missing_and_wrong_network_reports_block():
  """A skipped fixture, a teardown failure or an incomplete inventory cannot attest."""
  good = evidence.Payload.model_validate(passing('ethereum'))
  cases = [
    good.model_copy(update={'completed': False}),
    good.model_copy(update={'account_venue': 'arbitrum'}),
    good.model_copy(update={'checks': good.checks[:-1]}),
    good.model_copy(update={'checks': [*good.checks, good.checks[0]]}),
  ]
  for values in ({'passed': 0}, {'failed': 1}, {'skipped': 1}, {'passed': 2}):
    cases.append(
      good.model_copy(
        update={'checks': [good.checks[0].model_copy(update=values), *good.checks[1:]]}
      )
    )
  for case in cases:
    with pytest.raises(ValueError):
      evidence.verify_payload(case.model_dump(mode='json'), root=repo_root())


def test_deribit_split_keeps_public_metadata_mainnet_and_private_report_testnet():
  """Only the approved private checks may carry testnet evidence."""
  report = evidence.Payload.model_validate(passing('deribit'))
  report.private_account_venue = 'deribit_testnet'
  for check in report.checks:
    if check.id.startswith('report.'):
      check.network = 'testnet'
  evidence.verify_payload(report.model_dump(mode='json'), root=repo_root())
  for check in report.checks:
    original = check.network
    check.network = 'testnet' if original == 'mainnet' else 'mainnet'
    with pytest.raises(ValueError, match='network'):
      evidence.verify_payload(report.model_dump(mode='json'), root=repo_root())
    check.network = original
  for venue in ('deribit', 'kucoin_testnet', None):
    report.private_account_venue = venue
    with pytest.raises(ValueError):
      evidence.verify_payload(report.model_dump(mode='json'), root=repo_root())


def test_other_venues_and_old_surface_schema_cannot_use_the_deribit_exception():
  """The exception neither weakens other venue checks nor reuses old unlabeled runs."""
  report = evidence.Payload.model_validate(passing('kucoin'))
  report.private_account_venue = 'deribit_testnet'
  with pytest.raises(ValueError):
    evidence.verify_payload(report.model_dump(mode='json'), root=repo_root())
  for group in ('public_mainnet', 'report_testnet'):
    with pytest.raises(ValueError):
      evidence.group_inventory(repo_root(), 'kucoin', group)
  legacy = passing('deribit')
  legacy['version'] = 1
  with pytest.raises(ValueError):
    evidence.verify_payload(legacy, root=repo_root())


def test_deribit_groups_partition_every_required_check():
  """A split retains exactly the required public and private tests, without skips."""
  public = evidence.group_inventory(repo_root(), 'deribit', 'public_mainnet')
  private = evidence.group_inventory(repo_root(), 'deribit', 'report_testnet')
  assert len(public) == len(private) == 6
  assert not set(public) & set(private)
  assert set(public) | set(private) == set(evidence.inventory(repo_root(), 'deribit'))
  assert all(not id.startswith('report.') for id in public)
  assert all(id.startswith('report.') for id in private)


def test_split_collector_preserves_a_failed_private_run(
  monkeypatch: pytest.MonkeyPatch,
):
  """Public success cannot conceal a private worker crash or wrong environment."""
  public = evidence.Payload.model_validate(passing('deribit'))
  public.checks = [row for row in public.checks if not row.id.startswith('report.')]
  private = evidence.Payload.model_validate(passing('deribit'))
  private.account_venue = 'deribit_testnet'
  private.checks = [row for row in private.checks if row.id.startswith('report.')]
  for row in private.checks:
    row.network = 'testnet'
  for completed in (True, False):
    private.completed = completed
    monkeypatch.setattr(
      evidence,
      'collect',
      Mock(
        side_effect=[
          public.model_dump(mode='json'),
          private.model_dump(mode='json'),
        ]
      ),
    )
    result = evidence.collect_deribit('public', 'private', Path('accounts.toml'))
    if completed:
      evidence.verify_payload(result, root=repo_root())
    else:
      with pytest.raises(ValueError):
        evidence.verify_payload(result, root=repo_root())


def test_recorder_discards_private_errors_and_tracks_teardown():
  """Only fixed test identity and outcome counts escape the pytest process."""
  path = Path('/tmp/suite.py')
  recorder = evidence.Recorder({'report.test_snapshot': path})
  phases: list[
    tuple[Literal['setup', 'call', 'teardown'], Literal['passed', 'failed', 'skipped']]
  ] = [
    ('setup', 'passed'),
    ('call', 'passed'),
    ('teardown', 'failed'),
  ]
  for when, outcome in phases:
    report = pytest.TestReport(
      nodeid=f'{path}::test_snapshot[PRIVATE-ACCOUNT]',
      location=(str(path), 0, 'test_snapshot'),
      keywords={},
      outcome=outcome,
      longrepr='PRIVATE-BALANCE-AND-KEY',
      when=when,
    )
    recorder.pytest_runtest_logreport(report)
  check = recorder.checks['report.test_snapshot']
  assert check.passed == 1 and check.failed == 1
  assert 'PRIVATE' not in str(check.model_dump())


def test_subprocess_failures_never_export_output(monkeypatch: pytest.MonkeyPatch):
  """Raw configuration errors are discarded, not stored in a failed report."""
  monkeypatch.setattr(
    evidence.subprocess,
    'run',
    Mock(return_value=SimpleNamespace(returncode=1, stdout='SECRET', stderr='SECRET')),
  )
  result = evidence.collect('ethereum', 'local', Path('sdk.test.toml'))
  assert 'SECRET' not in str(result)
  with pytest.raises(ValueError):
    evidence.verify_payload(result, root=repo_root())


def test_worker_runs_real_pytest_and_sanitizes_failures(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
  """Exercise pytest's real callbacks, including parameterized node names."""
  suite = tmp_path / 'test_live.py'
  suite.write_text(
    'import pytest\n@pytest.mark.parametrize("account", ["PRIVATE-ID"])\ndef test_read(account):\n  assert False, "PRIVATE-BALANCE"\n'
  )
  (tmp_path / 'conftest.py').write_text(
    'def pytest_addoption(parser):\n  parser.addoption("--accounts-config")\n  parser.addoption("--sdk-venue")\n'
  )

  def inventory(root: Path, venue: str) -> dict[str, Path]:
    """Use a temporary real pytest suite without any exchange credentials."""
    return {'report.test_read': suite}

  def configured(accounts: Path) -> SimpleNamespace:
    """Supply only the selected account identity to the worker."""
    return SimpleNamespace(
      all_accounts={'local': SimpleNamespace(venue='ethereum')},
      accounts={'local': object()},
    )

  monkeypatch.setattr(evidence, 'inventory', inventory)
  monkeypatch.setattr(results, 'configured_sdk', configured)
  monkeypatch.setenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', '1')
  result = evidence.run_worker('ethereum', 'local', tmp_path / 'accounts.toml')
  report = evidence.Payload.model_validate(result)
  assert not report.completed and report.checks[0].failed == 1
  assert 'PRIVATE' not in str(result)
