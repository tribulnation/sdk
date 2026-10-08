"""All supported read suites must pass; omitted cases and forged skips fail closed."""

import asyncio
from contextlib import redirect_stderr, redirect_stdout
import io
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from typing_extensions import Literal

from sdk_dev import read_evidence as evidence
from sdk_dev.cli import results
from sdk_dev.integration.market.account import WAIVED, check_waivers, runs
from sdk_dev.repo import repo_root
from sdk_dev.support import AccountMode, ImplFile, Waiver, load_impl_files


def waived(exclusion: str | None) -> bool:
  """Whether an exclusion code is a waiver, whose read still runs."""
  return exclusion is not None and exclusion.startswith(WAIVED)


def minimum(venue: str) -> AccountMode:
  """The venue's qualification minimum, or `public` without account reads."""
  impl = load_impl_files(repo_root() / 'packages/impl')[venue]
  market = impl.qualification.market
  return market.min_mode if market is not None else 'public'


def uta_of(venue: str) -> bool | None:
  """Bitget qualifies its tracked Classic account; other venues have no mode flag."""
  return False if venue == 'bitget' else None


def cases_of(venue: str, mode: AccountMode | None = None) -> dict[str, evidence.Case]:
  """The inventory for a venue's account at `mode`, by default its minimum."""
  return evidence.inventory(
    repo_root(), venue, mode=mode or minimum(venue), bitget_uta=uta_of(venue)
  )


def passing(venue: str, mode: AccountMode | None = None) -> evidence.Payload:
  """Synthetic results are used only to exercise the offline verifier."""
  mode = mode or minimum(venue)
  return evidence.Payload(
    venue=venue,
    account_venue=venue,
    account_mode=mode,
    bitget_uta=uta_of(venue),
    completed=True,
    checks=[
      evidence.Outcome(
        id=id,
        passed=int(case.exclusion is None),
        skipped=int(waived(case.exclusion)),
        exclusion=case.exclusion,
      )
      for id, case in cases_of(venue, mode).items()
    ],
  )


@pytest.mark.parametrize('venue', results.required_venues(repo_root(), 'sdk'))
def test_all_implementations_have_complete_read_inventories(venue: str):
  """Every declared implementation has a nonempty independently checked inventory."""
  report = passing(venue)
  evidence.verify_payload(report.model_dump(mode='json'), root=repo_root())


def test_market_packages_require_account_surfaces_too():
  """Market success does not replace Wallet/Earn/Report qualification."""
  cases = cases_of('binance')
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
  assert len(exclusions) == 3
  exclusions[0].passed = 1
  with pytest.raises(ValueError):
    evidence.verify_payload(hl.model_dump(mode='json'), root=repo_root())
  mexc = cases_of('mexc')
  assert sum(case.exclusion == 'unsupported_perp_stream' for case in mexc.values()) == 1
  kraken = cases_of('kraken')
  assert (
    sum(case.exclusion == 'unsupported_perp_stream' for case in kraken.values()) == 1
  )


SUSPENDED = 'wallet.test_withdrawal_methods_not_empty[null, null]'


def test_withdrawal_suspension_is_narrow_and_dated(monkeypatch: pytest.MonkeyPatch):
  """Only Bitget withdrawal non-emptiness is excluded, never passed, and only until its end."""
  monkeypatch.setattr(evidence, 'today', lambda: date(2026, 10, 9))
  bitget = cases_of('bitget')
  excluded = [
    id for id, c in bitget.items() if c.exclusion == 'venue_withdrawals_suspended'
  ]
  assert excluded == [SUSPENDED]
  assert (
    bitget['wallet.test_withdrawal_methods_can_be_fetched[null, null]'].exclusion
    is None
  )
  for venue in results.required_venues(repo_root(), 'sdk'):
    if venue != 'bitget':
      cases = cases_of(venue).values()
      assert all(c.exclusion != 'venue_withdrawals_suspended' for c in cases)
  report = passing('bitget')
  evidence.verify_payload(report.model_dump(mode='json'), root=repo_root())
  forged = report.model_copy(deep=True)
  row = next(r for r in forged.checks if r.id == SUSPENDED)
  row.passed = 1
  with pytest.raises(ValueError):
    evidence.verify_payload(forged.model_dump(mode='json'), root=repo_root())
  monkeypatch.setattr(evidence, 'today', lambda: date(2026, 10, 10))
  assert cases_of('bitget')[SUSPENDED].exclusion is None
  with pytest.raises(ValueError):
    evidence.verify_payload(report.model_dump(mode='json'), root=repo_root())


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
    evidence.group_inventory(repo_root(), 'binance', 'report_testnet', mode='private')


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
    + ('uta = false\n' if venue == 'bitget' else '')
  )
  monkeypatch.setenv('SDK_DEV_ACCOUNTS_CONFIG', str(accounts))
  monkeypatch.setenv('SDK_DEV_ACCOUNT_ID', 'local')
  monkeypatch.setenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', '1')
  cases = cases_of(venue)
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
  assert len(recorder.nodes) == sum(runs(case.exclusion) for case in cases.values())


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
  monkeypatch.setattr(results, 'affected_venues', lambda root, package, venues: venues)
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


def test_public_address_reports_do_not_require_signing_secrets(
  monkeypatch: pytest.MonkeyPatch,
):
  """Read-only Report qualification needs an address, not trading authority."""
  from sdk_dev.integration.accounts import require_report_credentials
  from tribulnation.sdk.impl.accounts import Dydx, Hyperliquid, Binance

  monkeypatch.delenv('UNSET_REPORT_ADDRESS', raising=False)
  for account in (
    Dydx(address='dydx1test', public=True),
    Hyperliquid(address='0xtest', public=True),
  ):
    require_report_credentials(account)
  with pytest.raises(pytest.skip.Exception):
    require_report_credentials(
      Hyperliquid(address='$UNSET_REPORT_ADDRESS', public=True)
    )
  with pytest.raises(pytest.skip.Exception):
    require_report_credentials(Binance(public=True))


def test_report_runner_forwards_archive_configuration(tmp_path: Path):
  """Report provider configuration still reaches snapshot construction."""
  from sdk_dev.integration.report.conftest import load_sdk

  path = tmp_path / 'accounts.toml'
  path.write_text(
    '[accounts.dydx]\nvenue = "dydx"\npublic = true\naddress = "dydx1test"\n'
    '[report.dydx]\narchive_node = "polkachu"\n'
  )
  sdk = load_sdk(Mock(getoption=Mock(return_value=str(path))))
  assert sdk.config == {'dydx': {'archive_node': 'polkachu'}}


def test_report_runner_rejects_unknown_archive_provider(tmp_path: Path):
  """A typo must not silently select the default non-archive node."""
  from sdk_dev.integration.report.conftest import load_sdk
  import pydantic

  path = tmp_path / 'accounts.toml'
  path.write_text('[accounts]\n[report.dydx]\narchive_node = "typo"\n')
  with pytest.raises(pydantic.ValidationError):
    load_sdk(Mock(getoption=Mock(return_value=str(path))))


@pytest.mark.parametrize('venue', results.required_venues(repo_root(), 'sdk'))
def test_report_inventory_requires_only_snapshots(venue: str):
  """Report history is outside SDK live qualification under ADR 0016."""
  cases = cases_of(venue)
  report_tests = {case.test for case in cases.values() if case.surface == 'report'}
  assert report_tests <= {
    'test_snapshot_can_be_fetched',
    'test_snapshot_time_is_tz_aware',
    'test_snapshot_balances_are_finite_decimals',
  }


def test_report_snapshot_fixture_never_reads_history():
  """A snapshot check must not launch an archive-backed history sweep."""
  from sdk_dev.integration.report.conftest import read_report
  from tribulnation.sdk.reporting import Snapshot, SnapshotRecord

  snapshot = SnapshotRecord(
    snapshot=Snapshot(subaccounts=[]),
    provenance={'source': 'api', 'service': 'fixture', 'id': 'fixture'},
  )
  report = MagicMock()
  report.snapshot = AsyncMock(return_value=snapshot)
  report.history.side_effect = AssertionError('History must not be requested')
  sdk = Mock(venue=Mock(return_value=report))

  result = asyncio.run(read_report(sdk, 'fixture'))

  assert result.snapshot is snapshot
  assert result.snapshot_failure is None
  report.snapshot.assert_awaited_once_with()
  report.history.assert_not_called()
  report.__aexit__.assert_awaited_once()


def test_previous_history_qualification_version_is_rejected():
  """The changed qualification boundary requires newly recorded evidence."""
  legacy = passing('dydx').model_dump(mode='json')
  legacy['version'] = 3
  with pytest.raises(ValueError):
    evidence.verify_payload(legacy, root=repo_root())


def account_cases(venue: str, mode: AccountMode | None = None) -> dict[str, str | None]:
  """Account-read exclusions keyed by `<market> <method>`."""
  return {
    f'{case.market} {case.method}': case.exclusion
    for case in cases_of(venue, mode).values()
    if case.test == 'test_account_read'
  }


def test_account_inventory_follows_support_modes_and_exchanges():
  """Exclusions come from impl.toml support, the recorded mode and the market kind."""
  hl = account_cases('hyperliquid')
  assert hl[':BTC fees'] is None and hl['xyz:xyz:SILVER leverage'] is None
  assert hl['spot:UBTC/USDC:142 fees'] is None
  assert hl['spot:UBTC/USDC:142 perp_position'] == 'perp_only'
  assert all(
    code == 'order_lifecycle' for key, code in hl.items() if 'query_order' in key
  )
  binance = account_cases('binance')
  assert binance['spot:BTCUSDT fees'] is None
  assert binance['usdm:BTCUSDT fees'] == 'waived:credential_scope'
  assert binance['usdm:BTCUSDT open_orders'] == 'unsupported'
  assert binance['usdm:BTCUSDT leverage'] == 'unsupported'
  lighter = account_cases('lighter', 'address')
  assert lighter['perp:1 position'] is None
  assert lighter['perp:1 fees'] == 'credential_mode'
  assert lighter['perp:1 funding_payments'] == 'credential_mode'
  assert account_cases('lighter')['perp:1 fees'] is None
  bitget = account_cases('bitget')
  assert bitget['usdt:BTCUSDT perp_collateral'] == 'bitget_classic'
  assert bitget['usdt:BTCUSDT collateral'] == 'bitget_classic'
  assert bitget['spot:BTCUSDT collateral'] is None
  assert bitget['usdc:BTCPERP fees'] == 'unsupported'
  uta = evidence.inventory(repo_root(), 'bitget', mode='private', bitget_uta=True)
  assert all(case.exclusion != 'bitget_classic' for case in uta.values())
  for venue in ('deribit', 'kucoin'):
    codes = set(account_cases(venue).values())
    assert codes == {'unsupported', 'order_lifecycle', 'perp_only'}


def test_qualification_tables_name_real_account_reads():
  """Every listed method is an account read the venue declares, on a real exchange."""
  from sdk_dev.integration.market.account import ACCOUNT_READS
  from sdk_dev.integration.market.support import CASES

  for venue, impl in load_impl_files(repo_root() / 'packages/impl').items():
    market = impl.qualification.market
    support = impl.support.get('market')
    if market is None:
      if support is not None and support.support != 'none':
        assert all(code is not None for code in account_cases(venue).values())
      continue
    assert support is not None
    declared = (
      set(ACCOUNT_READS) if support.support == 'full' else set(support.methods or ())
    )
    assert set(market.address_methods) | set(market.token_methods) <= declared
    assert not set(market.address_methods) & set(market.token_methods)
    exchanges = {case.market_id.split(':', 1)[0] for case in CASES[venue]}
    for exchange, methods in market.unsupported.items():
      assert exchange in exchanges and set(methods) <= declared


@pytest.mark.parametrize('venue', ['binance', 'hyperliquid', 'lighter'])
def test_account_mode_below_minimum_is_rejected(venue: str):
  """A weaker account cannot narrow its own required inventory."""
  weaker: AccountMode = 'address' if minimum(venue) != 'address' else 'public'
  report = passing(venue, weaker)
  with pytest.raises(ValueError, match='below'):
    evidence.verify_payload(report.model_dump(mode='json'), root=repo_root())
  stronger = passing(venue, 'private')
  evidence.verify_payload(stronger.model_dump(mode='json'), root=repo_root())


def test_account_exclusions_cannot_be_invented_dropped_or_skipped():
  """Account rows follow the reconstructed policy exactly."""
  good = passing('binance')
  required = next(
    i
    for i, row in enumerate(good.checks)
    if 'test_account_read' in row.id and row.exclusion is None
  )
  excluded = next(
    i
    for i, row in enumerate(good.checks)
    if 'test_account_read' in row.id and row.exclusion == 'unsupported'
  )
  updates: list[tuple[int, dict[str, object]]] = [
    (required, {'passed': 0, 'exclusion': 'credential_mode'}),
    (required, {'passed': 0, 'skipped': 1}),
    (required, {'passed': 0, 'failed': 1}),
    (excluded, {'exclusion': None, 'passed': 1}),
    (excluded, {'exclusion': 'perp_only'}),
  ]
  for index, values in updates:
    bad = good.model_copy(deep=True)
    bad.checks[index] = bad.checks[index].model_copy(update=values)
    with pytest.raises(ValueError):
      evidence.verify_payload(bad.model_dump(mode='json'), root=repo_root())
  missing = good.model_copy(deep=True)
  del missing.checks[required]
  with pytest.raises(ValueError):
    evidence.verify_payload(missing.model_dump(mode='json'), root=repo_root())


def test_version_four_reports_are_rejected_not_relabelled():
  """Reports without a recorded account mode cannot qualify (ADR 0034)."""
  legacy = passing('binance').model_dump(mode='json')
  legacy['version'] = 4
  with pytest.raises(ValueError):
    evidence.verify_payload(legacy, root=repo_root())
  del legacy['account_mode']
  with pytest.raises(ValueError):
    evidence.verify_payload(legacy, root=repo_root())


def test_declared_waivers_are_visible_non_blocking_codes():
  """Binance USD-M and MEXC spot fees are waived with their reason, nothing else."""
  assert account_cases('binance')['usdm:BTCUSDT fees'] == 'waived:credential_scope'
  assert account_cases('binance')['spot:BTCUSDT fees'] is None
  assert account_cases('mexc')['spot:BTCUSDT fees'] == 'waived:account_setting'
  for venue in results.required_venues(repo_root(), 'sdk'):
    codes = {code for code in account_cases(venue).values() if waived(code)}
    expected = {
      'binance': {'waived:credential_scope'},
      'mexc': {'waived:account_setting'},
    }.get(venue, set())
    assert codes == expected


@pytest.mark.parametrize(
  'values, valid',
  [
    ({'passed': 0, 'skipped': 1}, True),
    ({'passed': 1, 'skipped': 0}, True),
    ({'passed': 0, 'skipped': 0}, False),
    ({'passed': 0, 'skipped': 0, 'failed': 1}, False),
    ({'passed': 1, 'skipped': 1}, False),
    ({'passed': 0, 'skipped': 1, 'exclusion': 'unsupported'}, False),
    ({'passed': 0, 'skipped': 1, 'exclusion': 'waived:account_setting'}, False),
  ],
)
def test_waived_reads_skip_or_pass_but_never_fail(
  values: dict[str, object], valid: bool
):
  """A waived read may skip or (if its waiver went stale) pass; failures still block."""
  report = passing('binance')
  index = next(
    i
    for i, row in enumerate(report.checks)
    if row.exclusion == 'waived:credential_scope'
  )
  report.checks[index] = report.checks[index].model_copy(update=values)
  payload = report.model_dump(mode='json')
  if valid:
    evidence.verify_payload(payload, root=repo_root())
  else:
    with pytest.raises(ValueError):
      evidence.verify_payload(payload, root=repo_root())


def with_waiver(venue: str, **fields: str) -> ImplFile:
  """The venue's declarations with one added waiver."""
  impl = load_impl_files(repo_root() / 'packages/impl')[venue]
  market = impl.qualification.market
  assert market is not None
  waiver = Waiver.model_validate({'reason': 'account_setting', 'note': 'x', **fields})
  market = market.model_copy(update={'waived': [*market.waived, waiver]})
  qualification = impl.qualification.model_copy(update={'market': market})
  return impl.model_copy(update={'qualification': qualification})


@pytest.mark.parametrize(
  'fields',
  [
    {'exchange': 'coin', 'method': 'fees'},
    {'exchange': 'spot', 'method': 'place_order'},
    {'exchange': 'spot', 'method': 'leverage'},
    {'exchange': 'spot', 'method': 'query_order'},
    {'exchange': 'perp', 'method': 'open_orders'},
    {'exchange': 'spot', 'method': 'fees'},
  ],
)
def test_waivers_must_name_a_required_read(fields: dict[str, str]):
  """Unknown exchanges or methods, excluded reads and duplicates are rejected."""
  with pytest.raises(ValueError):
    check_waivers(with_waiver('mexc', **fields), {'spot', 'perp'})
  check_waivers(
    with_waiver('mexc', exchange='spot', method='position'), {'spot', 'perp'}
  )


def test_waiver_reasons_and_notes_are_closed():
  """Only the closed reason set is accepted, and every waiver explains itself."""
  import pydantic

  for raw in (
    {'exchange': 'spot', 'method': 'fees', 'reason': 'flaky', 'note': 'x'},
    {'exchange': 'spot', 'method': 'fees', 'reason': 'account_setting', 'note': ''},
  ):
    with pytest.raises(pydantic.ValidationError):
      Waiver.model_validate(raw)


def test_summary_lists_every_waiver():
  """Release notes see each waived read and whether it skipped or passed."""
  from sdk_dev.evidence import waiver_summary

  checks = passing('binance').model_dump(mode='json')['checks']
  summary = waiver_summary(checks)
  assert 'usdm:BTCUSDT' in summary and 'waived:credential_scope, skipped' in summary
  assert waiver_summary(passing('bybit').model_dump(mode='json')['checks']) == ''
