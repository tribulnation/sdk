"""Deterministic local consistency coverage and offline evidence rejection."""

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from typing_extensions import cast
from tribulnation.catalogue import Catalogue
from tribulnation.sdk.impl.market import MarketSDK
from tribulnation.sdk.market import Book, PerpExchange, PerpStats, Ticker

from sdk_dev import consistency
from sdk_dev.consistency import Payload, check_id, collect, verify_payload


@pytest.fixture
def catalogue() -> Catalogue:
  """One active instrument with exact translation identities."""
  return Catalogue(
    assets={
      'bitcoin': {'id': 'bitcoin', 'display_name': 'Bitcoin', 'symbol': 'BTC'},
      'dollar': {'id': 'dollar', 'display_name': 'Dollar', 'symbol': 'USD'},
    },
    platforms={},
    platforms_order=[],
    network_translations={},
    asset_translations={'fixture': {'BTC': 'bitcoin', 'USD': 'dollar'}},
    spot_instruments={
      'fixture': {'BTC/USD': {'exchange': '', 'base': 'bitcoin', 'quote': 'dollar'}}
    },
    perpetual_instruments={},
    debt_instruments={},
    pools={},
    spam={},
  )


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
  """An explicit venue policy excludes only undeclared methods."""
  directory = tmp_path / 'packages' / 'impl' / 'fixture'
  directory.mkdir(parents=True)
  (directory / 'impl.toml').write_text(
    '[support.market]\nsupport="partial"\nauth=false\n'
    'methods=["rules","tickers","depth"]\n'
  )
  monkeypatch.setattr(consistency, 'repo_root', lambda: tmp_path)
  return tmp_path


@pytest.fixture
def sdk() -> MarketSDK:
  """A duck-typed public read harness; no credentials or trading methods exist."""
  market = SimpleNamespace(
    venue_id='fixture',
    exchange_id='',
    market_id='BTC/USD',
    rules=AsyncMock(return_value=SimpleNamespace(base='BTC', quote='USD')),
    depth=AsyncMock(
      return_value=Book(
        bids=[Book.Entry(Decimal(99), Decimal(1))],
        asks=[Book.Entry(Decimal(101), Decimal(1))],
      )
    ),
  )

  async def tickers(markets: list[str] | None = None) -> dict[str, Ticker]:
    """Honor exact selections and keep last unrelated to top-of-book comparisons."""
    keys = ['BTC/USD'] if markets is None else markets
    return {
      key: Ticker(bid=Decimal(99), ask=Decimal(101), last=Decimal(1000)) for key in keys
    }

  exchange = SimpleNamespace(
    exchange_id='',
    venue_id='fixture',
    markets=AsyncMock(return_value=['BTC/USD']),
    market=AsyncMock(return_value=market),
    tickers=AsyncMock(side_effect=tickers),
  )
  owner = SimpleNamespace(
    venue_id='fixture',
    exchange=AsyncMock(return_value=exchange),
    exchanges=AsyncMock(return_value=[{'id': '', 'type': 'spot', 'name': 'Fixture'}]),
  )
  return cast(
    MarketSDK,
    SimpleNamespace(
      all_accounts={'local': SimpleNamespace(venue='fixture')},
      venue=AsyncMock(return_value=owner),
    ),
  )


async def payload(sdk: MarketSDK, catalogue: Catalogue) -> dict[str, object]:
  """Exercise the production collector, not a handcrafted passing report."""
  return await collect(sdk, 'local', 'fixture', catalogue)


async def test_complete_local_run_verifies(
  root: Path, sdk: MarketSDK, catalogue: Catalogue
):
  """Empty exchange IDs and a far-away last price are both legitimate."""
  result = await payload(sdk, catalogue)
  verify_payload(result, catalogue=catalogue, root=root)
  report = Payload.model_validate(result)
  assert len(report.checks) == 10
  assert {check.status for check in report.checks} == {'pass'}


@pytest.mark.parametrize('field', ['unknown', 'version'])
async def test_schema_rejects_extra_or_coerced_fields(
  field: str, root: Path, sdk: MarketSDK, catalogue: Catalogue
):
  """The saved JSON contract accepts neither unknown fields nor string versions."""
  result = await payload(sdk, catalogue)
  result[field] = '1'
  with pytest.raises(ValueError):
    verify_payload(result, catalogue=catalogue, root=root)


async def test_missing_duplicate_and_vacuous_results_fail(
  root: Path, sdk: MarketSDK, catalogue: Catalogue
):
  """A report cannot remove failed checks or present an empty discovery as passing."""
  good = Payload.model_validate(await payload(sdk, catalogue))
  for report in (
    good.model_copy(update={'checks': good.checks[:-1]}),
    good.model_copy(update={'checks': [*good.checks, good.checks[0]]}),
    good.model_copy(update={'discovery': []}),
  ):
    with pytest.raises(ValueError):
      verify_payload(report.model_dump(mode='json'), catalogue=catalogue, root=root)


async def test_catalogue_growth_requires_new_checks(
  root: Path, sdk: MarketSDK, catalogue: Catalogue
):
  """Expected coverage is reconstructed from the actual supplied Catalogue."""
  result = await payload(sdk, catalogue)
  catalogue.spot_instruments['fixture']['NEW/USD'] = {
    'exchange': '',
    'base': 'bitcoin',
    'quote': 'dollar',
  }
  with pytest.raises(ValueError, match='inventory'):
    verify_payload(result, catalogue=catalogue, root=root)


async def test_missing_exchange_does_not_default_to_empty(
  root: Path, sdk: MarketSDK, catalogue: Catalogue
):
  """An explicitly empty exchange ID is valid; an omitted field is not."""
  catalogue.spot_instruments['fixture']['BTC/USD'].pop('exchange')
  result = await payload(sdk, catalogue)
  with pytest.raises(ValueError, match='did not pass'):
    verify_payload(result, catalogue=catalogue, root=root)


async def test_catalogue_prefix_is_not_stripped(
  root: Path, sdk: MarketSDK, catalogue: Catalogue
):
  """An opaque colon-containing ID is never silently matched to a different key."""
  row = catalogue.spot_instruments['fixture'].pop('BTC/USD')
  catalogue.spot_instruments['fixture']['spot:BTC/USD'] = row
  result = await payload(sdk, catalogue)
  verify_payload(result, catalogue=catalogue, root=root)
  report = Payload.model_validate(result)
  check = next(
    check
    for check in report.checks
    if check.id == check_id('catalogue_coverage', 'spot', 'spot:BTC/USD')
  )
  assert check.status == 'deferred'


async def test_absent_catalogue_market_is_visible_but_not_a_release_gate(
  root: Path, sdk: MarketSDK, catalogue: Catalogue
):
  """Exact coverage is deferred; identity and coverage remain separate."""
  catalogue.spot_instruments['fixture']['MISSING/USD'] = {
    'exchange': '',
    'base': 'bitcoin',
    'quote': 'dollar',
  }
  result = await payload(sdk, catalogue)
  verify_payload(result, catalogue=catalogue, root=root)
  report = Payload.model_validate(result)
  deferred = next(check for check in report.checks if check.status == 'deferred')
  assert deferred.id == check_id('catalogue_coverage', 'spot', 'MISSING/USD')
  deferred.status = 'pass'
  deferred.code = 'ok'
  with pytest.raises(ValueError, match='coverage findings'):
    verify_payload(report.model_dump(mode='json'), catalogue=catalogue, root=root)


@pytest.mark.parametrize(
  'venue,exchange,good,bad',
  [
    ('bitget', 'coin-classic', 'BTCUSD', 'BTCUSD_CM'),
    ('bitget', 'coin', 'BTCUSD_CM', 'BTCUSD'),
    ('bitget', 'usdt', '龙虾USDT', '龙虾USDT_UMCBL'),
    ('bitget', 'usdc', 'BTCPERP', 'BTCUSDT'),
    ('coinbase', 'intx', 'BTC-PERP-INTX', 'BTC-PERP'),
    ('mexc', 'perp', 'BTC_USDT', 'BTCUSDT'),
    ('dydx', 'perp', 'BTC-USD', 'BTC-USDC'),
  ],
)
def test_native_id_conventions_do_not_assert_market_existence(
  venue: str, exchange: str, good: str, bad: str
):
  """Known product namespace mismatches remain blocking independently of listings."""
  assert consistency.valid_market_id(venue, exchange, good)
  assert not consistency.valid_market_id(venue, exchange, bad)


async def test_asset_translation_checks_are_retired(
  root: Path, sdk: MarketSDK, catalogue: Catalogue
):
  """Identity evidence does not claim to verify Catalogue asset semantics."""
  catalogue.asset_translations['fixture']['BTC'] = 'dollar'
  result = await payload(sdk, catalogue)
  verify_payload(result, catalogue=catalogue, root=root)
  market = await (await (await sdk.venue('local')).exchange('')).market('BTC/USD')
  cast(AsyncMock, market.rules).assert_not_called()
  assert not any(
    'catalogue_rules' in check.id for check in Payload.model_validate(result).checks
  )


async def test_legacy_asset_evidence_is_rejected(
  root: Path, sdk: MarketSDK, catalogue: Catalogue
):
  """Old schemas and invented asset observations cannot masquerade as new evidence."""
  result = await payload(sdk, catalogue)
  result['version'] = 1
  with pytest.raises(ValueError):
    verify_payload(result, catalogue=catalogue, root=root)
  report = Payload.model_validate(await payload(sdk, catalogue))
  raw = report.model_dump(mode='json')
  raw['checks'][0]['assets'] = {}
  with pytest.raises(ValueError):
    verify_payload(raw, catalogue=catalogue, root=root)


async def test_delisted_and_sdk_only_markets_are_not_coverage_errors(
  root: Path, sdk: MarketSDK, catalogue: Catalogue
):
  """Catalogue expansion is a later concern; delisted rows are out of scope."""
  catalogue.spot_instruments['fixture']['DELISTED'] = {
    'delisted': True,
    'base': 'bitcoin',
    'quote': 'dollar',
  }
  catalogue.spot_instruments['fixture'].pop('BTC/USD')
  verify_payload(await payload(sdk, catalogue), catalogue=catalogue, root=root)


async def test_product_exclusions_are_explicit_not_inferred_from_missing_discovery(
  root: Path, sdk: MarketSDK, catalogue: Catalogue, monkeypatch: pytest.MonkeyPatch
):
  """Only the declared deferred product is excluded; other unknown exchanges fail."""
  assert consistency.catalogue_excluded('kraken', 'perp', 'perp')
  assert not consistency.catalogue_excluded('kraken', 'spot', 'perp')
  assert consistency.catalogue_excluded('bitget', 'perp', 'coin')
  assert not consistency.catalogue_excluded('bitget', 'perp', 'coin-classic')
  assert not consistency.catalogue_excluded('bitget', 'spot', 'coin')
  monkeypatch.setattr(
    consistency, 'CATALOGUE_EXCLUSIONS', frozenset({('fixture', 'perp', 'future')})
  )
  catalogue.perpetual_instruments['fixture'] = {
    'BTC/USD': {
      'exchange': 'future',
      'base': 'bitcoin',
      'quote': 'dollar',
      'settlement': 'dollar',
    },
  }
  result = await payload(sdk, catalogue)
  verify_payload(result, catalogue=catalogue, root=root)
  assert (
    sum(check.status == 'excluded' for check in Payload.model_validate(result).checks)
    == 2
  )
  catalogue.perpetual_instruments['fixture']['BTC/USD']['exchange'] = 'typo'
  with pytest.raises(ValueError):
    verify_payload(await payload(sdk, catalogue), catalogue=catalogue, root=root)


async def test_empty_selection_must_not_fetch_every_market(
  root: Path, sdk: MarketSDK, catalogue: Catalogue
):
  """An empty selection differs from None even when the venue has only one market."""
  exchange = await (await sdk.venue('local')).exchange('')
  cast(AsyncMock, exchange.tickers).side_effect = None
  cast(AsyncMock, exchange.tickers).return_value = {
    'BTC/USD': Ticker(bid=Decimal(99), ask=Decimal(101))
  }
  with pytest.raises(ValueError):
    verify_payload(await payload(sdk, catalogue), catalogue=catalogue, root=root)


async def test_depth_mismatch_retries_and_missing_quotes_block(
  root: Path, sdk: MarketSDK, catalogue: Catalogue
):
  """Persistent price or missing-side mismatches fail after three fresh attempts."""
  exchange = await (await sdk.venue('local')).exchange('')
  market = await exchange.market('BTC/USD')
  depth = cast(AsyncMock, market.depth)
  depth.return_value = Book(
    bids=[Book.Entry(Decimal(50), Decimal(1))],
    asks=[Book.Entry(Decimal(51), Decimal(1))],
  )
  result = Payload.model_validate(await payload(sdk, catalogue))
  quote = next(
    check
    for check in result.checks
    if check.id == check_id('ticker_depth', '', 'BTC/USD')
  )
  assert quote.status == 'fail'
  assert depth.await_count == 6
  depth.return_value = Book()
  result = Payload.model_validate(await payload(sdk, catalogue))
  quote = next(
    check
    for check in result.checks
    if check.id == check_id('ticker_depth', '', 'BTC/USD')
  )
  assert quote.status == 'fail'
  with pytest.raises(ValueError):
    verify_payload(result.model_dump(mode='json'), catalogue=catalogue, root=root)


async def test_unexpected_unsupported_is_failure_not_exclusion(
  root: Path, sdk: MarketSDK, catalogue: Catalogue
):
  """Only impl.toml policy, never a thrown exception, determines exclusions."""
  exchange = await (await sdk.venue('local')).exchange('')
  market = await exchange.market('BTC/USD')
  cast(AsyncMock, market.depth).side_effect = NotImplementedError(
    'sensitive upstream payload'
  )
  result = await payload(sdk, catalogue)
  assert 'sensitive' not in str(result)
  with pytest.raises(ValueError):
    verify_payload(result, catalogue=catalogue, root=root)


async def test_empty_book_diagnostics_do_not_invent_price_coverage(
  root: Path, sdk: MarketSDK, catalogue: Catalogue
):
  """An empty exchange can be consistent without claiming any price evidence."""
  exchange = await (await sdk.venue('local')).exchange('')
  market = await exchange.market('BTC/USD')
  cast(AsyncMock, market.depth).return_value = Book()

  async def empty_tickers(markets: list[str] | None = None) -> dict[str, Ticker]:
    """Return exact requested IDs with no invented quotes."""
    return {key: Ticker() for key in (['BTC/USD'] if markets is None else markets)}

  cast(AsyncMock, exchange.tickers).side_effect = empty_tickers
  report = Payload.model_validate(await payload(sdk, catalogue))
  quote = next(check for check in report.checks if check.quotes)
  assert quote.status == 'unavailable'
  assert quote.code == 'empty_book'
  assert consistency.empty_book_observations(quote.quotes)
  verify_payload(report.model_dump(mode='json'), catalogue=catalogue, root=root)


async def test_empty_sample_requires_complete_matching_observations(
  root: Path, sdk: MarketSDK, catalogue: Catalogue
):
  """Empty-book exceptions require complete, timely, matching observations."""
  report = Payload.model_validate(await payload(sdk, catalogue))
  report.discovery[0].markets.append('EMPTY/USD')
  empty = consistency.Check(
    id=check_id('ticker_depth', '', 'EMPTY/USD'),
    status='unavailable',
    code='empty_book',
    quotes=[
      consistency.QuoteObservation(
        attempt=attempt, elapsed_seconds=1.0, ticker_ids_match=True
      )
      for attempt in range(1, consistency.RETRIES + 1)
    ],
  )
  report.checks.append(empty)
  verify_payload(report.model_dump(mode='json'), catalogue=catalogue, root=root)
  for field, value in (
    ('ticker_ids_match', False),
    ('elapsed_seconds', 16.0),
    ('before_bid', '99'),
    ('ask', '101'),
    ('attempt', 2),
  ):
    original = empty.quotes[0]
    empty.quotes[0] = original.model_copy(update={field: value})
    with pytest.raises(ValueError):
      verify_payload(report.model_dump(mode='json'), catalogue=catalogue, root=root)
    empty.quotes[0] = original
  empty.quotes.pop()
  with pytest.raises(ValueError):
    verify_payload(report.model_dump(mode='json'), catalogue=catalogue, root=root)


async def test_setup_failures_are_sanitized_diagnostics(
  root: Path, sdk: MarketSDK, catalogue: Catalogue
):
  """A credential or setup failure does not leak an exception into saved evidence."""
  cast(AsyncMock, sdk.venue).side_effect = RuntimeError('secret-key=DO-NOT-LOG')
  result = await payload(sdk, catalogue)
  assert 'DO-NOT-LOG' not in str(result)
  with pytest.raises(ValueError):
    verify_payload(result, catalogue=catalogue, root=root)


async def test_quote_observations_are_verified(
  root: Path, sdk: MarketSDK, catalogue: Catalogue
):
  """A saved pass label cannot override contradictory public observations."""
  report = Payload.model_validate(await payload(sdk, catalogue))
  quote = next(check for check in report.checks if check.quotes)
  assert quote.quotes[0].bid == '99'
  assert quote.quotes[0].before_ask == '101'
  quote.quotes[0].bid = '500'
  with pytest.raises(ValueError, match='bracket'):
    verify_payload(report.model_dump(mode='json'), catalogue=catalogue, root=root)


async def test_slow_brackets_are_unavailable(
  root: Path, sdk: MarketSDK, catalogue: Catalogue, monkeypatch: pytest.MonkeyPatch
):
  """A price coincidence after a slow request does not pass the fixed time budget."""
  ticks = iter([0.0, 16.0, 20.0, 36.0, 40.0, 56.0])
  monkeypatch.setattr(consistency, 'monotonic', lambda: next(ticks))
  report = Payload.model_validate(await payload(sdk, catalogue))
  quote = next(check for check in report.checks if check.quotes)
  assert quote.status == 'unavailable'
  assert [row.elapsed_seconds for row in quote.quotes] == [16.0] * 3
  with pytest.raises(ValueError):
    verify_payload(report.model_dump(mode='json'), catalogue=catalogue, root=root)


@pytest.mark.parametrize('side', ['bid', 'ask'])
async def test_one_sided_books_compare_only_the_existing_side(
  side: str, root: Path, sdk: MarketSDK, catalogue: Catalogue
):
  """A sole one-sided sample qualifies without fabricating its absent side."""
  exchange = await (await sdk.venue('local')).exchange('')
  market = await exchange.market('BTC/USD')
  cast(AsyncMock, market.depth).return_value = Book(
    bids=[Book.Entry(Decimal(99), Decimal(1))] if side == 'bid' else [],
    asks=[Book.Entry(Decimal(101), Decimal(1))] if side == 'ask' else [],
  )

  async def tickers(markets: list[str] | None = None) -> dict[str, Ticker]:
    """Return precisely the observed side and exact selection IDs."""
    return {
      key: Ticker(
        bid=Decimal(99) if side == 'bid' else None,
        ask=Decimal(101) if side == 'ask' else None,
      )
      for key in (['BTC/USD'] if markets is None else markets)
    }

  cast(AsyncMock, exchange.tickers).side_effect = tickers
  report = Payload.model_validate(await payload(sdk, catalogue))
  verify_payload(report.model_dump(mode='json'), catalogue=catalogue, root=root)
  quote = next(check for check in report.checks if check.quotes)
  assert quote.status == 'pass'
  setattr(quote.quotes[-1], side, '500')
  with pytest.raises(ValueError, match='bracket'):
    verify_payload(report.model_dump(mode='json'), catalogue=catalogue, root=root)


@pytest.mark.parametrize('value', ['0', '-1', 'NaN', 'Infinity', 'not-a-price'])
def test_invalid_existing_side_never_counts_as_empty(value: str):
  """Malformed prices fail even when the opposite side is consistently missing."""
  row = consistency.QuoteObservation(
    attempt=1,
    elapsed_seconds=1.0,
    ticker_ids_match=True,
    bid=value,
    before_bid='99',
    after_bid='99',
  )
  assert consistency.bracket_result(row) is False


async def test_delisted_quote_exclusions_keep_identity_and_verify_lifecycle(
  root: Path, sdk: MarketSDK, catalogue: Catalogue
):
  """Only an explicit exact Catalogue lifecycle flag permits a quote exclusion."""
  catalogue.spot_instruments['fixture']['BTC/USD']['delisted'] = True
  report = Payload.model_validate(await payload(sdk, catalogue))
  quote = next(check for check in report.checks if 'ticker_depth' in check.id)
  assert (quote.status, quote.code, quote.quotes) == ('excluded', 'delisted', [])
  assert (
    next(check for check in report.checks if 'market_identity' in check.id).status
    == 'pass'
  )
  exchange = await (await sdk.venue('local')).exchange('')
  market = await exchange.market('BTC/USD')
  cast(AsyncMock, market.depth).assert_not_awaited()
  verify_payload(report.model_dump(mode='json'), catalogue=catalogue, root=root)
  quote.code = 'unsupported'
  with pytest.raises(ValueError, match='Delisted'):
    verify_payload(report.model_dump(mode='json'), catalogue=catalogue, root=root)
  quote.code = 'delisted'
  catalogue.spot_instruments['fixture']['BTC/USD']['exchange'] = 'different'
  with pytest.raises(ValueError):
    verify_payload(report.model_dump(mode='json'), catalogue=catalogue, root=root)


async def test_two_sided_policy_reports_require_fresh_qualification(
  root: Path, sdk: MarketSDK, catalogue: Catalogue
):
  """Payload version 2 cannot be relabeled as the new liquidity-independent policy."""
  result = await payload(sdk, catalogue)
  result['version'] = 2
  with pytest.raises(ValueError):
    verify_payload(result, catalogue=catalogue, root=root)


async def test_policy_exclusions_are_explicit_and_rechecked(
  root: Path, sdk: MarketSDK, catalogue: Catalogue
):
  """A later policy change invalidates evidence that excluded the newly required read."""
  path = root / 'packages' / 'impl' / 'fixture' / 'impl.toml'
  path.write_text(
    '[support.market]\nsupport="partial"\nauth=false\nmethods=["rules"]\n'
  )
  result = await payload(sdk, catalogue)
  report = Payload.model_validate(result)
  excluded = next(check for check in report.checks if check.status == 'excluded')
  assert excluded.id in {
    check_id('tickers', '', selection) for selection in ('bulk', 'selected', 'empty')
  } | {check_id('ticker_depth', '', 'BTC/USD')}
  verify_payload(result, catalogue=catalogue, root=root)
  path.write_text('[support.market]\nsupport="full"\nauth=false\n')
  with pytest.raises(ValueError):
    verify_payload(result, catalogue=catalogue, root=root)


async def test_wrong_account_venue_is_not_mainnet_evidence(
  root: Path, sdk: MarketSDK, catalogue: Catalogue
):
  """An account alias may be arbitrary, but its configured venue must match exactly."""
  cast(SimpleNamespace, sdk.all_accounts['local']).venue = 'fixture_testnet'
  with pytest.raises(ValueError):
    verify_payload(await payload(sdk, catalogue), catalogue=catalogue, root=root)


async def test_perp_stats_checks_exact_requested_ids(
  root: Path, sdk: MarketSDK, catalogue: Catalogue
):
  """Perpetual bulk, selected and empty stats are independently required checks."""
  owner = await sdk.venue('local')
  spot = await owner.exchange('')
  perp = Mock(spec=PerpExchange)
  perp.venue_id = 'fixture'
  perp.exchange_id = ''
  perp.market = spot.market
  perp.markets = spot.markets
  perp.tickers = spot.tickers

  async def stats(markets: list[str] | None = None) -> dict[str, PerpStats]:
    """Return a deterministic public stats row for each exact requested key."""
    return {
      key: PerpStats(index=Decimal(100))
      for key in (['BTC/USD'] if markets is None else markets)
    }

  perp.perp_stats = AsyncMock(side_effect=stats)
  cast(AsyncMock, owner.exchange).return_value = perp
  cast(AsyncMock, owner.exchanges).return_value = [
    {'id': '', 'type': 'perp', 'name': 'Perp'}
  ]
  catalogue.spot_instruments = {}
  path = root / 'packages' / 'impl' / 'fixture' / 'impl.toml'
  path.write_text('[support.market]\nsupport="full"\nauth=false\n')
  result = await payload(sdk, catalogue)
  verify_payload(result, catalogue=catalogue, root=root)
  report = Payload.model_validate(result)
  assert {check.id for check in report.checks if 'perp_stats' in check.id} == {
    check_id('perp_stats', '', selection) for selection in ('bulk', 'selected', 'empty')
  }
  perp.perp_stats.side_effect = None
  perp.perp_stats.return_value = {'UNRELATED': PerpStats(index=Decimal(100))}
  with pytest.raises(ValueError):
    verify_payload(await payload(sdk, catalogue), catalogue=catalogue, root=root)
