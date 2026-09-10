"""Read-only, venue-local market consistency checks with exhaustive offline coverage."""

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from decimal import Decimal, InvalidOperation
from pathlib import Path
from time import monotonic

from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import Literal, TypeVar
from tribulnation.catalogue import Catalogue
from tribulnation.sdk.impl.market import MarketSDK
from tribulnation.sdk.market import Exchange, Market, PerpExchange

from .integration.market.support import CASES
from .repo import repo_root
from .support import load_impl_files

VERSION = 3
REQUEST_TIMEOUT = 120
BRACKET_SECONDS = 15
TOLERANCE = Decimal('0.005')
RETRIES = 3
T = TypeVar('T')
Kind = Literal['spot', 'perp']
Status = Literal['pass', 'fail', 'unavailable', 'excluded', 'deferred']

# Kraken Futures and Bitget UTA coin are explicitly deferred products.
# Keep its Catalogue rows visible as exclusions; never infer scope from discovery
# failures or automatically exclude other unrecognized exchange IDs.
CATALOGUE_EXCLUSIONS = frozenset(
  {('kraken', 'perp', 'perp'), ('bitget', 'perp', 'coin')}
)


class StrictModel(BaseModel):
  """Reject coercions and undeclared fields in saved evidence."""

  model_config = ConfigDict(extra='forbid', strict=True)


class Discovery(StrictModel):
  """Public exchange identity and its complete discovered market inventory."""

  exchange: str
  kind: Kind
  markets: list[str]


class QuoteObservation(StrictModel):
  """One public quote bracket, retaining enough information to recompute its result."""

  attempt: int = Field(ge=1, le=RETRIES)
  elapsed_seconds: float = Field(ge=0, allow_inf_nan=False)
  ticker_ids_match: bool
  bid: str | None = None
  ask: str | None = None
  before_bid: str | None = None
  before_ask: str | None = None
  after_bid: str | None = None
  after_ask: str | None = None


class Check(StrictModel):
  """A sanitized outcome: no exception text or account API payloads."""

  id: str
  status: Status
  code: Literal[
    'ok',
    'mismatch',
    'request_failed',
    'unavailable',
    'empty_book',
    'unsupported',
    'dependency_failed',
    'coverage_deferred',
    'delisted',
  ]
  quotes: list[QuoteObservation] = Field(default_factory=list[QuoteObservation])


class Payload(StrictModel):
  """One mainnet venue's discovery and deterministic check inventory."""

  version: Literal[3] = VERSION
  venue: str
  account_id: str
  discovery: list[Discovery]
  checks: list[Check]


def check_id(*parts: str) -> str:
  """Encode opaque IDs without ambiguities from colons or empty exchange IDs."""
  return json.dumps(parts, ensure_ascii=True, separators=(',', ':'))


def methods(root: Path, venue: str) -> set[str]:
  """Resolve supported read methods only from the committed implementation policy."""
  entry = load_impl_files(root / 'packages' / 'impl').get(venue)
  support = entry.support.get('market') if entry is not None else None
  if support is None or support.support == 'none' or venue.endswith('_testnet'):
    raise ValueError('Venue has no mainnet market consistency scope')
  return (
    {'rules', 'depth', 'tickers', 'perp_stats'}
    if support.support == 'full'
    else set(support.methods or [])
  )


def catalogue_rows(catalogue: Catalogue, venue: str):
  """Yield every active in-scope instrument without normalizing its opaque ID."""
  for kind, table in (
    ('spot', catalogue.spot_instruments),
    ('perp', catalogue.perpetual_instruments),
  ):
    for market_id, row in sorted(table.get(venue, {}).items()):
      if not row.get('delisted', False):
        yield kind, market_id, row


def samples(venue: str, item: Discovery) -> list[str]:
  """Select deterministic coverage plus all established reference markets."""
  selected = set(sorted(item.markets)[:3])
  for case in CASES.get(venue, []):
    exchange, market = case.market_id.split(':', 1)
    if exchange == item.exchange:
      selected.add(market)
  return sorted(selected)


def valid_market_id(venue: str, exchange: str, market: str) -> bool:
  """Check native ID conventions without asserting that an instrument is listed.

  Other venues retain opaque IDs, including Hyperliquid's significant colons.
  These rules distinguish known API namespaces, not asset identity or coverage.
  """
  if not market or market != market.strip() or any(c.isspace() for c in market):
    return False
  if market.startswith(f'{venue}:') or (exchange and market.startswith(f'{exchange}:')):
    # HIP-3 prefixes are part of the native symbol, not SDK qualification.
    if venue != 'hyperliquid':
      return False
  if venue == 'bitget':
    if exchange == 'coin':
      return market.endswith('USD_CM') and market.removesuffix('_CM').isalnum()
    return market.isalnum() and (
      exchange == 'spot'
      or exchange == 'usdt'
      and market.endswith('USDT')
      or exchange == 'usdc'
      and market.endswith('PERP')
      or exchange == 'coin-classic'
      and market.endswith('USD')
    )
  if venue == 'coinbase' and exchange == 'intx':
    return market.endswith('-PERP-INTX')
  if venue == 'mexc' and exchange == 'perp':
    return bool(re.fullmatch(r'[^_:]+_[^_:]+', market))
  if venue == 'dydx':
    return market.endswith('-USD')
  return True


def coverage_missing(report: Payload, exchange: str | None, market: str) -> bool:
  """Defer only absence from a successfully identified exchange's market list."""
  return any(
    item.exchange == exchange and market not in item.markets
    for item in report.discovery
  )


def catalogue_excluded(venue: str, kind: str, exchange: str | None) -> bool:
  """Only previously agreed product deferrals are out of qualification scope."""
  return (venue, kind, exchange) in CATALOGUE_EXCLUSIONS


def catalogue_delisted(
  catalogue: Catalogue, venue: str, item: Discovery, market: str
) -> bool:
  """Use reviewed, fingerprinted lifecycle data, never infer delisting from a book."""
  table = (
    catalogue.spot_instruments
    if item.kind == 'spot'
    else catalogue.perpetual_instruments
  )
  row = table.get(venue, {}).get(market)
  return (
    row is not None
    and row.get('exchange') == item.exchange
    and row.get('delisted', False)
  )


def inventory(payload: Payload, catalogue: Catalogue) -> dict[str, str | None]:
  """Recompute required IDs and method applicability independently of reported checks."""
  expected: dict[str, str | None] = {
    check_id('setup'): None,
    check_id('discovery'): None,
  }
  for item in payload.discovery:
    for name in ('exchange_identity', 'market_identity'):
      expected[check_id(name, item.exchange)] = None
    for method in ('tickers', 'perp_stats') if item.kind == 'perp' else ('tickers',):
      for selection in ('bulk', 'selected', 'empty'):
        expected[check_id(method, item.exchange, selection)] = method
    for market in samples(payload.venue, item):
      expected[check_id('ticker_depth', item.exchange, market)] = (
        'delisted'
        if catalogue_delisted(catalogue, payload.venue, item, market)
        else 'depth+tickers'
      )
  for kind, market, row in catalogue_rows(catalogue, payload.venue):
    excluded = catalogue_excluded(payload.venue, kind, row.get('exchange'))
    expected[check_id('catalogue_identity', kind, market)] = (
      'out_of_scope' if excluded else None
    )
    expected[check_id('catalogue_coverage', kind, market)] = (
      'out_of_scope' if excluded else None
    )
  return expected


def enabled(method: str | None, supported: set[str]) -> bool:
  """Multi-method comparisons require each underlying method to be declared."""
  return method != 'out_of_scope' and (
    method is None or set(method.split('+')) <= supported
  )


def verify_payload(
  payload: dict[str, object], *, catalogue: Catalogue, root: Path
) -> None:
  """Reject nonpassing, duplicate, vacuous or incomplete results against current scope."""
  report = Payload.model_validate(payload)
  supported = methods(root, report.venue)
  if (
    not report.account_id
    or not report.discovery
    or not any(item.markets for item in report.discovery)
  ):
    raise ValueError('Consistency evidence is empty')
  if len({item.exchange for item in report.discovery}) != len(report.discovery):
    raise ValueError('Duplicate discovered exchange IDs')
  for item in report.discovery:
    if len(set(item.markets)) != len(item.markets) or any(
      not valid_market_id(report.venue, item.exchange, market)
      for market in item.markets
    ):
      raise ValueError('Invalid discovered market inventory')
  expected = inventory(report, catalogue)
  actual = {check.id: check for check in report.checks}
  if len(actual) != len(report.checks) or set(actual) != set(expected):
    raise ValueError('Consistency check inventory is incomplete or duplicated')
  deferred = {
    check_id('catalogue_coverage', kind, market)
    for kind, market, row in catalogue_rows(catalogue, report.venue)
    if not catalogue_excluded(report.venue, kind, row.get('exchange'))
    and coverage_missing(report, row.get('exchange'), market)
  }
  for id, method in expected.items():
    check = actual[id]
    if method == 'delisted':
      if check.status != 'excluded' or check.code != 'delisted' or check.quotes:
        raise ValueError('Delisted quote checks must remain explicit exclusions')
      continue
    if id in deferred:
      if check.status != 'deferred' or check.code != 'coverage_deferred':
        raise ValueError(
          'Missing Catalogue markets must remain explicit coverage findings'
        )
      continue
    if enabled(method, supported):
      if (
        method == 'depth+tickers'
        and check.status == 'unavailable'
        and check.code == 'empty_book'
        and empty_book_observations(check.quotes)
      ):
        continue
      if check.status != 'pass' or check.code != 'ok':
        raise ValueError('Required consistency check did not pass')
      if method == 'depth+tickers':
        if (
          not check.quotes
          or len(check.quotes) > RETRIES
          or [row.attempt for row in check.quotes]
          != list(range(1, len(check.quotes) + 1))
          or bracket_result(check.quotes[-1]) is not True
        ):
          raise ValueError('Passing quote comparison lacks valid bracket observations')
    elif check.status != 'excluded' or check.code != 'unsupported':
      raise ValueError('Unsupported checks must be explicit exclusions')
  for kind, market, row in catalogue_rows(catalogue, report.venue):
    if catalogue_excluded(report.venue, kind, row.get('exchange')):
      continue
    item = next(
      (item for item in report.discovery if item.exchange == row.get('exchange')), None
    )
    if (
      item is None
      or item.kind != kind
      or not valid_market_id(report.venue, item.exchange, market)
    ):
      raise ValueError('Catalogue identity contradicts discovery')


async def request(awaitable: Awaitable[T]) -> T:
  """Bound each read without exposing upstream exception payloads."""
  return await asyncio.wait_for(awaitable, timeout=REQUEST_TIMEOUT)


def empty_book_observations(rows: list[QuoteObservation]) -> bool:
  """Recognize repeated, timely, consistently empty snapshots, never price coverage."""
  return len(rows) == RETRIES and all(
    row.attempt == attempt
    and row.ticker_ids_match
    and row.elapsed_seconds <= BRACKET_SECONDS
    and all(
      value is None
      for value in (
        row.bid,
        row.ask,
        row.before_bid,
        row.before_ask,
        row.after_bid,
        row.after_ask,
      )
    )
    for attempt, row in enumerate(rows, start=1)
  )


def bracket_result(row: QuoteObservation) -> bool | None:
  """Compare present sides and matching absence without requiring market liquidity."""
  if not row.ticker_ids_match:
    return False
  if row.elapsed_seconds > BRACKET_SECONDS:
    return None
  observed = False
  for current, before, after in (
    (row.bid, row.before_bid, row.after_bid),
    (row.ask, row.before_ask, row.after_ask),
  ):
    if current is None and before is None and after is None:
      continue
    if current is None or before is None or after is None:
      return False
    try:
      value, lower, upper = (Decimal(price) for price in (current, before, after))
    except InvalidOperation:
      return False
    if any(not price.is_finite() or price <= 0 for price in (value, lower, upper)):
      return False
    if (
      not min(lower, upper) * (1 - TOLERANCE)
      <= value
      <= max(lower, upper) * (1 + TOLERANCE)
    ):
      return False
    observed = True
  # A wholly empty bracket is recorded as unavailable, never as price evidence.
  return True if observed else None


async def quote_match(
  exchange: Exchange,
  market: Market,
  market_id: str,
  observations: list[QuoteObservation],
) -> bool | None:
  """Compare up to three fresh depth brackets, retaining sanitized public prices."""
  failures = 0
  for attempt in range(1, RETRIES + 1):
    started = monotonic()
    row = QuoteObservation(attempt=attempt, elapsed_seconds=0.0, ticker_ids_match=False)
    observations.append(row)
    try:
      before = await request(market.depth(levels=1))
      row.before_bid = str(before.bids[0].price) if before.bids else None
      row.before_ask = str(before.asks[0].price) if before.asks else None
      selected = await request(exchange.tickers(markets=[market_id]))
      row.ticker_ids_match = set(selected) == {market_id}
      ticker = selected.get(market_id)
      row.bid = (
        str(ticker.bid) if ticker is not None and ticker.bid is not None else None
      )
      row.ask = (
        str(ticker.ask) if ticker is not None and ticker.ask is not None else None
      )
      after = await request(market.depth(levels=1))
      row.after_bid = str(after.bids[0].price) if after.bids else None
      row.after_ask = str(after.asks[0].price) if after.asks else None
    finally:
      row.elapsed_seconds = monotonic() - started
    result = bracket_result(row)
    if result is True:
      return True
    failures += result is False
  return False if failures == RETRIES else None


async def collect(
  sdk: MarketSDK, account_id: str, venue: str, catalogue: Catalogue
) -> dict[str, object]:
  """Collect local public read-only checks; failures remain sanitized diagnostic rows."""
  report = Payload(venue=venue, account_id=account_id, discovery=[], checks=[])
  supported = methods(repo_root(), venue)
  exchanges: dict[str, Exchange] = {}
  markets: dict[tuple[str, str], Market] = {}

  def add(
    id: str,
    result: bool | None,
    code: Literal['mismatch', 'request_failed', 'dependency_failed'] = 'mismatch',
    quotes: list[QuoteObservation] | None = None,
  ):
    """Store only a fixed code and status, never exception messages or account data."""
    report.checks.append(
      Check(
        id=id,
        status='pass' if result else 'unavailable' if result is None else 'fail',
        code=(
          'ok'
          if result
          else 'empty_book'
          if result is None and empty_book_observations(quotes or [])
          else 'unavailable'
          if result is None
          else code
        ),
        quotes=quotes or [],
      )
    )

  async def run(
    id: str,
    fn: Callable[[], Awaitable[bool | None]],
    method: str | None = None,
    quotes: list[QuoteObservation] | None = None,
  ):
    """Keep unsupported exclusions distinct from unexpected NotImplementedError."""
    if not enabled(method, supported):
      report.checks.append(Check(id=id, status='excluded', code='unsupported'))
      return
    try:
      add(id, await fn(), quotes=quotes)
    except Exception:
      add(id, False, 'request_failed', quotes=quotes)

  try:
    account = sdk.all_accounts[account_id]
    if account.venue != venue or venue.endswith('_testnet'):
      raise ValueError('Account is not the requested mainnet venue')
    owner = await request(sdk.venue(account_id))
    if owner.venue_id != venue:
      raise ValueError('Instantiated venue identity does not match')
    add(check_id('setup'), True)
    descriptions = await request(owner.exchanges())
    unique = len({item['id'] for item in descriptions}) == len(descriptions)
    add(check_id('discovery'), bool(descriptions) and unique)
    for description in descriptions:
      exchange_id = description['id']
      discovered = Discovery(exchange=exchange_id, kind=description['type'], markets=[])
      report.discovery.append(discovered)
      try:
        exchange = await request(owner.exchange(exchange_id))
        exchanges[exchange_id] = exchange
        kind = 'perp' if isinstance(exchange, PerpExchange) else 'spot'
        add(
          check_id('exchange_identity', exchange_id),
          exchange.exchange_id == exchange_id
          and exchange.venue_id == venue
          and kind == discovered.kind,
        )
        discovered.markets = list(await request(exchange.markets()))
        valid = bool(discovered.markets) and len(set(discovered.markets)) == len(
          discovered.markets
        )
        for market_id in discovered.markets:
          valid &= valid_market_id(venue, exchange_id, market_id)
          market = await request(exchange.market(market_id))
          markets[exchange_id, market_id] = market
          valid &= (market.venue_id, market.exchange_id, market.market_id) == (
            venue,
            exchange_id,
            market_id,
          )
        add(check_id('market_identity', exchange_id), valid)
      except Exception:
        # Missing downstream rows are filled explicitly from the expected inventory.
        continue
  except Exception:
    if not any(check.id == check_id('setup') for check in report.checks):
      add(check_id('setup'), False, 'request_failed')

  for item in report.discovery:
    exchange = exchanges.get(item.exchange)
    if exchange is None:
      continue
    selected = samples(venue, item)
    for method in ('tickers', 'perp_stats') if item.kind == 'perp' else ('tickers',):
      for selection in ('bulk', 'selected', 'empty'):

        async def check_keys(
          exchange: Exchange = exchange,
          method: str = method,
          selection: str = selection,
          item: Discovery = item,
          selected: list[str] = selected,
        ) -> bool:
          """Read exact selection semantics, including the explicitly empty request."""
          requested = (
            None if selection == 'bulk' else selected if selection == 'selected' else []
          )
          if method == 'perp_stats':
            if not isinstance(exchange, PerpExchange):
              return False
            result = await request(exchange.perp_stats(markets=requested))
          else:
            result = await request(exchange.tickers(markets=requested))
          return (
            bool(result) and set(result) <= set(item.markets)
            if requested is None
            else set(result) == set(requested) and set(result) <= set(item.markets)
          )

        await run(check_id(method, item.exchange, selection), check_keys, method)
    for market_id in selected:
      observations: list[QuoteObservation] = []
      if catalogue_delisted(catalogue, venue, item, market_id):
        report.checks.append(
          Check(
            id=check_id('ticker_depth', item.exchange, market_id),
            status='excluded',
            code='delisted',
          )
        )
        continue

      async def check_quotes(
        exchange: Exchange = exchange,
        exchange_id: str = item.exchange,
        market_id: str = market_id,
      ) -> bool | None:
        """A missing reference market fails instead of disappearing from coverage."""
        market = markets.get((exchange_id, market_id))
        return (
          False
          if market is None
          else await quote_match(exchange, market, market_id, observations)
        )

      await run(
        check_id('ticker_depth', item.exchange, market_id),
        check_quotes,
        'depth+tickers',
        quotes=observations,
      )

  for kind, market_id, row in catalogue_rows(catalogue, venue):
    exchange_id = row.get('exchange')
    if catalogue_excluded(venue, kind, exchange_id):
      for name in ('catalogue_identity', 'catalogue_coverage'):
        report.checks.append(
          Check(
            id=check_id(name, kind, market_id),
            status='excluded',
            code='unsupported',
          )
        )
      continue
    item = next(
      (item for item in report.discovery if item.exchange == exchange_id), None
    )
    identity = (
      item is not None
      and item.kind == kind
      and valid_market_id(venue, item.exchange, market_id)
    )
    add(check_id('catalogue_identity', kind, market_id), identity)
    if identity and coverage_missing(report, exchange_id, market_id):
      report.checks.append(
        Check(
          id=check_id('catalogue_coverage', kind, market_id),
          status='deferred',
          code='coverage_deferred',
        )
      )
    else:
      add(check_id('catalogue_coverage', kind, market_id), identity)
  actual = {check.id for check in report.checks}
  for id, method in inventory(report, catalogue).items():
    if id not in actual:
      if enabled(method, supported):
        add(id, False, 'dependency_failed')
      else:
        report.checks.append(Check(id=id, status='excluded', code='unsupported'))
  report.checks.sort(key=lambda check: check.id)
  return report.model_dump(mode='json')
