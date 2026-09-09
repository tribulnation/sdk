"""Network-free regressions for the live runner's selection, safety and contracts."""

from collections.abc import Sequence
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock
import ast
import asyncio

import pytest
from typer.testing import CliRunner
from typing_extensions import cast

from tribulnation.sdk import ApiError, Earn, Wallet
from tribulnation.sdk.impl.accounts import Account, Bybit, Kraken, Mexc
from tribulnation.sdk.market import Candle, PerpStats
from sdk_dev.cli import test as cli
from sdk_dev.cli.test import runner
from sdk_dev.integration import accounts, conftest
from sdk_dev.integration.earn.conftest import fetch_instruments
from sdk_dev.integration.market import suite, public
from sdk_dev.integration.market.support import END, HOUR, CandlesResult
from sdk_dev.integration.runtime import loop_of
from sdk_dev.integration.support import describe_exception
from sdk_dev.integration.wallet.conftest import fetch_wallet


@pytest.mark.parametrize('surface', ['earn', 'wallet', 'report', 'market'])
def test_cli_exact_selector(surface: str, monkeypatch: pytest.MonkeyPatch):
  """Every surface forwards an exact selector, not a pytest expression."""
  calls: list[list[str]] = []

  def capture(args: list[str]) -> int:
    """Record the command without starting pytest or making API calls."""
    calls.append(args)
    return 0

  monkeypatch.setattr(runner.pytest, 'main', capture)
  result = CliRunner().invoke(
    cli.test_app, [surface, 'my-account', '--accounts', 'test.toml']
  )
  assert result.exit_code == 0, result.output
  assert calls[0][calls[0].index('--sdk-venue') + 1] == 'my-account'
  assert '-k' not in calls[0]
  if surface == 'market':
    assert any(path.endswith('/market/public.py') for path in calls[0])


def test_runner_propagates_failure(monkeypatch: pytest.MonkeyPatch):
  """A failed live suite cannot be reported as a successful CLI command."""

  def fail(args: list[str]) -> int:
    """Return a failed pytest exit code without running any tests."""
    return 1

  monkeypatch.setattr(runner.pytest, 'main', fail)
  assert CliRunner().invoke(cli.test_app, ['wallet']).exit_code == 1


@pytest.mark.parametrize(
  ('selector', 'expected'),
  [('mexc', ['trading']), ('trading', ['trading']), ('kraken', ['cold'])],
)
def test_account_selection_matches_venue_not_alias_substrings(
  selector: str,
  expected: list[str],
  monkeypatch: pytest.MonkeyPatch,
  pytestconfig: pytest.Config,
):
  """Alias names need not contain the venue; unrelated clients are never constructed."""
  monkeypatch.setattr(pytestconfig.option, 'sdk_venue', selector, raising=False)
  configured: dict[str, Account] = {
    'trading': Mexc(),
    'cold': Kraken(),
    'unused': Bybit(),
  }
  assert (
    accounts.selected_accounts(pytestconfig, configured, surface='wallet') == expected
  )


def test_unknown_selector_is_an_error(
  monkeypatch: pytest.MonkeyPatch, pytestconfig: pytest.Config
):
  """A typo must not produce an apparently successful empty run."""
  monkeypatch.setattr(pytestconfig.option, 'sdk_venue', 'mex', raising=False)
  with pytest.raises(pytest.UsageError, match='Unknown venue'):
    accounts.selected_accounts(pytestconfig, {'trading': Mexc()}, surface='wallet')


def test_missing_credentials_are_deferred_to_selected_account(
  tmp_path: Path,
  monkeypatch: pytest.MonkeyPatch,
  pytestconfig: pytest.Config,
):
  """Collection succeeds with missing environment variables; the selected read skips."""
  path = tmp_path / 'accounts.toml'
  path.write_text(
    '[accounts.private]\nvenue = "mexc"\napi_key = "$SDK_TEST_MISSING_KEY"\n'
  )
  monkeypatch.delenv('SDK_TEST_MISSING_KEY', raising=False)
  monkeypatch.setattr(pytestconfig.option, 'accounts_config', str(path), raising=False)
  configured = accounts.load_accounts(pytestconfig)
  with pytest.raises(pytest.skip.Exception, match='Missing required credential'):
    accounts.require_credentials(configured['private'])


def test_shared_loop_is_reused_and_closed():
  """A session has one loop even when several independent surface fixtures run."""
  config = pytest.Config.fromdictargs({}, [])
  loop = loop_of(config)
  assert loop_of(config) is loop
  conftest.pytest_unconfigure(config)
  assert loop.is_closed()


def test_private_surfaces_skip_public_only_accounts():
  """One shared accounts file can serve public market and private-only surface suites."""
  with pytest.raises(
    pytest.skip.Exception, match='requires a configured private account'
  ):
    accounts.require_credentials(Bybit(public=True), auth=True)


@pytest.mark.parametrize('failure', [False, True])
def test_earn_closes_on_success_or_failure(failure: bool):
  """Earn reads own their client's async lifetime on both exit paths."""
  sdk = AsyncMock(spec=Earn)
  sdk.instruments.return_value = []
  if failure:
    sdk.instruments.side_effect = RuntimeError('read failed')
    with pytest.raises(RuntimeError):
      asyncio.run(fetch_instruments(cast(Earn, sdk)))
  else:
    assert asyncio.run(fetch_instruments(cast(Earn, sdk))) == []
  sdk.__aenter__.assert_awaited_once()
  sdk.__aexit__.assert_awaited_once()


def test_wallet_checks_declared_support_before_calling():
  """A declared gap skips without invoking an endpoint; the supported read still runs."""
  sdk = AsyncMock(spec=Wallet)
  sdk.withdrawal_methods.return_value = []
  result = asyncio.run(fetch_wallet(cast(Wallet, sdk), methods=['withdrawal_methods']))
  assert result.deposit_unsupported is not None
  assert result.withdrawal_failure is None
  sdk.deposit_methods.assert_not_called()
  sdk.withdrawal_methods.assert_awaited_once()
  sdk.__aexit__.assert_awaited_once()


def test_wallet_unexpected_unimplemented_is_a_failure():
  """A promised method raising NotImplementedError must not silently become a skip."""
  sdk = AsyncMock(spec=Wallet)
  sdk.deposit_methods.side_effect = NotImplementedError('broken implementation')
  sdk.withdrawal_methods.return_value = []
  result = asyncio.run(fetch_wallet(cast(Wallet, sdk)))
  assert result.deposit_failure == 'NotImplementedError'
  assert result.deposit_unsupported is None
  assert result.withdrawal_failure is None
  sdk.__aexit__.assert_awaited_once()


def candles(offsets: Sequence[int]) -> list[Candle]:
  """Build a series with controllable gaps, native order and overlapping opens."""
  return [
    Candle(
      time=END - (72 - offset) * HOUR,
      open=Decimal(1),
      high=Decimal(1),
      low=Decimal(1),
      close=Decimal(1),
    )
    for offset in offsets
  ]


def test_candle_conformance_allows_native_order_and_empty_slots():
  """No ordering or synthetic-candle guarantee is imposed by the live suite."""
  suite.check_series(
    CandlesResult(pages=[candles([71, 60]), candles([2, 0])]), count=72
  )


@pytest.mark.parametrize('offsets', [[1, 1], [-1, 2], [1, 72]])
def test_candle_conformance_rejects_duplicates_and_outside_opens(offsets: list[int]):
  """Duplicate, pre-start and exclusive-end candles are genuine contract failures."""
  with pytest.raises(AssertionError):
    suite.check_series(CandlesResult(pages=[candles(offsets)]), count=72)


def test_candle_conformance_rejects_misalignment():
  """Candle times must be grid-aligned even when the response is otherwise valid."""
  rows = candles([1])
  rows[0].time += timedelta(microseconds=1)
  with pytest.raises(AssertionError, match='Unaligned'):
    suite.check_series(CandlesResult(pages=[rows]), count=72)


def test_public_outcomes_continue_after_a_failure():
  """One broken read leaves independent public results available for diagnosis."""
  result = public.PublicResults()
  bad = AsyncMock(side_effect=RuntimeError('secret credential'))
  good = AsyncMock(return_value=Decimal(1))

  async def collect():
    """Run both fake methods on the same loop."""
    await result.attempt('depth', bad)
    await result.attempt('index', good)

  asyncio.run(collect())
  assert result.failures == {'depth': 'RuntimeError'}
  assert result.values == {'index': Decimal(1)}


def test_account_dependent_market_reads_are_explicit():
  """Fee/catalogue requirements are known before calls; other AuthErrors still fail."""
  assert public.needs_account('bybit', 'rules', public=True)
  assert not public.needs_account('bybit', 'rules', public=False)
  assert not public.needs_account('bybit', 'depth', public=True)
  assert not public.needs_account('kraken', 'rules', public=True)
  assert public.needs_account('coinbase', 'perp_stats', public=True)


def test_perp_stats_conformance_accepts_unknown_optional_fields():
  """A bulk endpoint need not invent settlement state or a mark price."""
  assert 'perp_stats' in public.READS
  result = public.PublicResults(
    values={
      'perp_stats': {
        'BTC_USDT': PerpStats(index=Decimal('100'), funding=Decimal('-0.0001'))
      },
    }
  )
  public.test_public_read(result, 'mexc:perp:BTC_USDT', 'perp_stats')


@pytest.mark.parametrize(
  'stats',
  [
    PerpStats(index=Decimal('NaN')),
    PerpStats(index=Decimal('100'), open_interest=Decimal('-1')),
    PerpStats(index=Decimal('100'), funding_interval=timedelta(0)),
  ],
)
def test_perp_stats_conformance_rejects_invalid_values(stats: PerpStats):
  """Genuine contract violations fail even when the SDK call itself succeeded."""
  result = public.PublicResults(values={'perp_stats': {'BTC_USDT': stats}})
  with pytest.raises(AssertionError):
    public.test_public_read(result, 'mexc:perp:BTC_USDT', 'perp_stats')


@pytest.mark.parametrize(
  'error',
  [
    RuntimeError('secret credential'),
    ApiError({'code': 700007, 'msg': 'secret credential'}),
  ],
)
def test_error_summary_never_echoes_payloads(error: Exception):
  """Signed URLs, headers and account records cannot leak through pytest summaries."""
  assert 'secret credential' not in describe_exception(error)


def test_live_suites_have_no_mutating_order_calls():
  """Even tests expecting an unimplemented error must never submit a live order."""
  root = Path(public.__file__).parents[1]
  forbidden = {
    'place_order',
    'place_orders',
    'cancel_order',
    'cancel_orders',
    'cancel_open_orders',
  }
  for path in root.rglob('*.py'):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
      assert not (isinstance(node, ast.Attribute) and node.attr in forbidden), path.name
