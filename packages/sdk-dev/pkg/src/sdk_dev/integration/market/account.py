"""Read-only account-method checks on the reference markets (ADR 0042).

Every check validates the shape and internal consistency of what the account reads
return, never their contents: an account without orders, fills or balances passes.
Failures use fixed messages, so balances, identifiers and raw errors never reach the
output or the recorded evidence.
"""

from collections.abc import Awaitable, Callable, Collection, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import asyncio

import pytest
from typing_extensions import TypeVar, cast

from tribulnation.sdk import AuthError, Context, MarketSDK, NetworkError, RateLimited
from tribulnation.sdk.core import PaginatedResponse
from tribulnation.sdk.market import (
  Collateral,
  Fees,
  FundingPayment,
  OrderState,
  PerpCollateral,
  PerpMarket,
  PerpPosition,
  Position,
  Rules,
  Trade,
)
from sdk_dev.repo import IMPL_DIR, repo_root
from sdk_dev.support import (
  AccountMode,
  ImplFile,
  MarketQualification,
  load_impl_files,
  mode_rank,
)
from ..accounts import account_mode, package_of, selected_accounts
from ..runtime import loop_of
from ..support import describe_exception
from .conftest import market_sdk
from .support import cases_of

ACCOUNT_READS = (
  'fees',
  'open_orders',
  'query_order',
  'trades_history',
  'funding_payments',
  'position',
  'perp_position',
  'collateral',
  'perp_collateral',
  'leverage',
  'available_notional',
)
"""Account-scoped Market reads, one case each per reference market."""

PERP_ONLY = frozenset(
  {'funding_payments', 'perp_position', 'perp_collateral', 'leverage'}
)
"""Reads the SDK defines on perpetual markets only."""

STATIC_EXCLUSIONS = {'query_order': 'order_lifecycle'}
"""Reads a read-only suite cannot exercise: an order ID to query needs an order
placed and cancelled, which is trading."""

HISTORY = timedelta(days=30)
"""Window of trade and funding history read."""

HISTORY_PAGES = 2
"""Pages of history read at most, so an active account stays bounded."""

TIMEOUT = 60
"""Seconds allowed per read, history pages included."""


class AccountCheckError(Exception):
  """A contract violation, described by a fixed message without account values."""


def require(condition: bool, message: str):
  """Raise `AccountCheckError(message)` unless `condition` holds."""
  if not condition:
    raise AccountCheckError(message)


def finite(value: object) -> bool:
  """Whether `value` is a finite `Decimal`."""
  return isinstance(value, Decimal) and value.is_finite()


def required_mode(qualification: MarketQualification, method: str) -> AccountMode:
  """The weakest account mode the venue serves `method` with."""
  if method in qualification.address_methods:
    return 'address'
  if method in qualification.token_methods:
    return 'token'
  return 'private'


def account_exclusion(
  impl: ImplFile,
  *,
  venue: str,
  exchange_id: str,
  method: str,
  mode: AccountMode,
  bitget_uta: bool | None,
  apply_waivers: bool = True,
) -> str | None:
  """The policy exclusion of one account read on one market, or `None` if required.

  Reconstructed from committed declarations and the recorded account mode only, so the
  offline verifier reaches the same answer as the live run. A `waived:<reason>` code
  still runs the read: only the waiver's expected error becomes a visible skip.

  Raises:
    ValueError: Account methods are declared without a `[qualification.market]` table.
  """
  if method in STATIC_EXCLUSIONS:
    return STATIC_EXCLUSIONS[method]
  if exchange_id == 'spot' and method in PERP_ONLY:
    return 'perp_only'
  support = impl.support.get('market')
  qualification = impl.qualification.market
  declared = (
    support is not None
    and support.support != 'none'
    and (support.support == 'full' or method in (support.methods or ()))
  )
  if not declared or (
    qualification is not None
    and method in qualification.unsupported.get(exchange_id, ())
  ):
    return 'unsupported'
  if qualification is None:
    raise ValueError('Declared account methods need a [qualification.market] table')
  if mode_rank(mode) < mode_rank(required_mode(qualification, method)):
    return 'credential_mode'
  if (
    venue == 'bitget'
    and bitget_uta is False
    and exchange_id != 'spot'
    and method in ('collateral', 'perp_collateral')
  ):
    return 'bitget_classic'
  if apply_waivers:
    for waiver in qualification.waived:
      if waiver.exchange == exchange_id and waiver.method == method:
        return f'{WAIVED}{waiver.reason}'
  return None


WAIVED = 'waived:'
"""Prefix of waiver exclusion codes, followed by the waiver's reason."""

WAIVED_ERRORS: dict[str, type[Exception]] = {
  'credential_scope': AuthError,
  'account_setting': NotImplementedError,
}
"""The only failure each waiver reason turns into a skip; anything else still fails."""


def check_waivers(impl: ImplFile, exchanges: Collection[str]):
  """Reject waivers naming an unknown exchange or a read that is not otherwise required.

  Checked against the reference markets' exchanges and the declarations alone, in the
  strongest mode, so a stale waiver fails instead of silently matching nothing.

  Raises:
    ValueError: A waiver is duplicated or does not name a required account read.
  """
  qualification = impl.qualification.market
  if qualification is None:
    return
  seen: set[tuple[str, str]] = set()
  for waiver in qualification.waived:
    key = (waiver.exchange, waiver.method)
    if key in seen:
      raise ValueError('Duplicate account-read waiver')
    seen.add(key)
    if waiver.exchange not in exchanges or waiver.method not in ACCOUNT_READS:
      raise ValueError('Waiver names an unknown exchange or account read')
    code = account_exclusion(
      impl,
      venue='',
      exchange_id=waiver.exchange,
      method=waiver.method,
      mode='private',
      bitget_uta=None,
      apply_waivers=False,
    )
    if code is not None:
      raise ValueError('Waiver names an account read that is already excluded')


@dataclass(frozen=True, kw_only=True)
class AccountPlan:
  """Which reads one account runs on one reference market."""

  exclusions: dict[str, str | None]
  """Policy exclusion per read; `None` for a required read."""
  below_minimum: bool
  """Whether the account's mode is weaker than the venue's qualification minimum."""


def plan_of(sdk: MarketSDK, id: str) -> AccountPlan:
  """Apply the exclusion policy to a configured account and reference market."""
  account_id, exchange_id, _ = id.split(':', 2)
  account = sdk.accounts[account_id]
  venue = package_of(account.venue)
  impl = load_impl_files(repo_root() / IMPL_DIR)[venue]
  mode = account_mode(account)
  uta = getattr(account, 'uta', None)
  exclusions = {
    method: account_exclusion(
      impl,
      venue=venue,
      exchange_id=exchange_id,
      method=method,
      mode=mode,
      bitget_uta=uta if isinstance(uta, bool) else None,
    )
    for method in ACCOUNT_READS
  }
  qualification = impl.qualification.market
  below = qualification is not None and mode_rank(mode) < mode_rank(
    qualification.min_mode
  )
  return AccountPlan(exclusions=exclusions, below_minimum=below)


@dataclass
class AccountResults:
  """Independent read outcomes for one account and market, with the history window."""

  spot: bool
  start: datetime
  end: datetime
  values: dict[str, object] = field(default_factory=dict[str, object])
  failures: dict[str, str] = field(default_factory=dict[str, str])
  errors: dict[str, type[Exception]] = field(default_factory=dict[str, type[Exception]])
  """Exception class per failed read, matched against waivers; never exported."""

  async def attempt(self, name: str, call: Callable[[], Awaitable[object]]):
    """Bound each read, retaining a sanitized failure without hiding later reads."""
    try:
      with Context().retried(NetworkError, RateLimited, max_retries=2).use():
        self.values[name] = await asyncio.wait_for(call(), TIMEOUT)
    except Exception as exception:
      self.failures[name] = describe_exception(exception)
      self.errors[name] = type(exception)


T = TypeVar('T')


async def first_pages(read: Callable[[], PaginatedResponse[T]]) -> list[T]:
  """Read at most `HISTORY_PAGES` pages, closing the walk early when there are more."""
  items: list[T] = []
  iterator = aiter(read())
  try:
    for _ in range(HISTORY_PAGES):
      try:
        page = await anext(iterator)
      except StopAsyncIteration:
        break
      items.extend(page)
  finally:
    close = getattr(iterator, 'aclose', None)
    if close is not None:
      await close()
  return items


async def collect_account(
  sdk: MarketSDK, id: str, methods: Sequence[str]
) -> AccountResults:
  """Acquire one managed venue and call only the selected read-only account methods."""
  account_id, exchange_id, symbol = id.split(':', 2)
  end = datetime.now(timezone.utc)
  result = AccountResults(spot=exchange_id == 'spot', start=end - HISTORY, end=end)
  try:
    async with sdk:
      venue = await sdk.venue(account_id)
      exchange = await venue.exchange(exchange_id)
      market = await exchange.market(symbol)
      calls: dict[str, Callable[[], Awaitable[object]]] = {
        'rules': market.rules,
        'fees': market.fees,
        'open_orders': market.open_orders,
        'trades_history': lambda: first_pages(
          lambda: market.trades_history(result.start, result.end)
        ),
        'position': market.position,
        'collateral': market.collateral,
        'available_notional': market.available_notional,
      }
      if isinstance(market, PerpMarket):
        calls.update(
          {
            'funding_payments': lambda: first_pages(
              lambda: market.funding_payments(result.start, result.end)
            ),
            'perp_position': market.perp_position,
            'perp_collateral': market.perp_collateral,
            'leverage': market.leverage,
          }
        )
      wanted = list(methods)
      if 'trades_history' in wanted:
        wanted.append('rules')
      if 'perp_position' in wanted and 'position' not in wanted:
        wanted.append('position')
      for name in wanted:
        if name in calls:
          await result.attempt(name, calls[name])
        else:
          result.failures[name] = 'Perpetual read on a non-perpetual market'
  except Exception as exception:
    failure = describe_exception(exception)
    for name in methods:
      result.failures.setdefault(name, failure)
  return result


def check_fees(value: object):
  """Four finite rates below 100% in magnitude, with non-negative taker rates."""
  require(isinstance(value, Fees), 'fees: not a Fees value')
  fees = cast(Fees, value)
  rates = (fees.maker_buy, fees.maker_sell, fees.taker_buy, fees.taker_sell)
  require(all(finite(rate) for rate in rates), 'fees: non-finite rate')
  require(fees.taker_buy >= 0 and fees.taker_sell >= 0, 'fees: negative taker rate')
  require(all(abs(rate) < 1 for rate in rates), 'fees: rate of 100% or more')


def check_open_orders(value: object):
  """Open orders with IDs, valid prices and fills within their signed quantity."""
  require(
    isinstance(value, Sequence) and not isinstance(value, str),
    'open_orders: not a sequence',
  )
  for order in cast(Sequence[object], value):
    require(isinstance(order, OrderState), 'open_orders: item is not an OrderState')
    order = cast(OrderState, order)
    require(isinstance(order.id, str) and bool(order.id), 'open_orders: empty order ID')
    require(finite(order.price) and order.price >= 0, 'open_orders: invalid price')
    require(finite(order.qty) and order.qty != 0, 'open_orders: invalid quantity')
    require(finite(order.filled_qty), 'open_orders: non-finite filled quantity')
    require(
      order.filled_qty == 0 or (order.filled_qty > 0) == (order.qty > 0),
      'open_orders: filled quantity has the opposite sign',
    )
    require(
      abs(order.filled_qty) <= abs(order.qty),
      'open_orders: filled quantity exceeds the order quantity',
    )


def in_window(time: object, *, start: datetime, end: datetime) -> bool:
  """Whether `time` is a timezone-aware datetime within the inclusive window."""
  return (
    isinstance(time, datetime) and time.utcoffset() is not None and start <= time <= end
  )


def check_trades(
  value: object, *, start: datetime, end: datetime, fee_asset: str | None
):
  """Fills inside the window, with valid prices, sides and fees.

  A rules `fee_asset` names the asset every fill pays in; `None` defers it to each
  fill (ADR 0028).
  """
  require(isinstance(value, list), 'trades_history: pages were not read')
  for trade in cast(list[object], value):
    require(isinstance(trade, Trade), 'trades_history: item is not a Trade')
    trade = cast(Trade, trade)
    require(
      in_window(trade.time, start=start, end=end),
      'trades_history: naive or out-of-window time',
    )
    require(finite(trade.price) and trade.price > 0, 'trades_history: invalid price')
    require(finite(trade.qty) and trade.qty != 0, 'trades_history: invalid quantity')
    require(isinstance(trade.maker, bool), 'trades_history: maker is not a bool')
    if trade.fee is not None:
      require(finite(trade.fee.amount), 'trades_history: non-finite fee')
      require(
        isinstance(trade.fee.asset, str) and bool(trade.fee.asset),
        'trades_history: empty fee asset',
      )
      require(
        fee_asset is None or trade.fee.asset == fee_asset,
        'trades_history: fee asset differs from rules().fee_asset',
      )


def check_funding_payments(value: object, *, start: datetime, end: datetime):
  """Funding cash flows inside the window, with finite amounts."""
  require(isinstance(value, list), 'funding_payments: pages were not read')
  for payment in cast(list[object], value):
    require(
      isinstance(payment, FundingPayment), 'funding_payments: item is not a payment'
    )
    payment = cast(FundingPayment, payment)
    require(finite(payment.amount), 'funding_payments: non-finite amount')
    require(
      in_window(payment.time, start=start, end=end),
      'funding_payments: naive or out-of-window time',
    )


def check_position(value: object, *, spot: bool):
  """A finite size, never negative on spot, where it is a balance."""
  require(isinstance(value, Position), 'position: not a Position')
  size = cast(Position, value).size
  require(finite(size), 'position: non-finite size')
  require(not spot or size >= 0, 'position: negative spot balance')


def check_perp_position(value: object, position: object):
  """A valid entry price for any open size, agreeing with `position()`."""
  require(isinstance(value, PerpPosition), 'perp_position: not a PerpPosition')
  perp = cast(PerpPosition, value)
  require(finite(perp.size), 'perp_position: non-finite size')
  require(
    finite(perp.entry_price) and perp.entry_price >= 0,
    'perp_position: invalid entry price',
  )
  require(
    perp.size == 0 or perp.entry_price > 0,
    'perp_position: open position without an entry price',
  )
  require(isinstance(position, Position), 'perp_position: position() was not read')
  require(
    cast(Position, position).size == perp.size,
    'perp_position: size differs from position()',
  )


def check_collateral(value: object, *, spot: bool):
  """Finite equity and free collateral, free never above equity."""
  require(isinstance(value, Collateral), 'collateral: not a Collateral')
  collateral = cast(Collateral, value)
  require(
    finite(collateral.equity) and finite(collateral.free_collateral),
    'collateral: non-finite value',
  )
  require(
    collateral.free_collateral <= collateral.equity,
    'collateral: free collateral exceeds equity',
  )
  require(
    not spot or collateral.free_collateral >= 0, 'collateral: negative spot balance'
  )


def check_perp_collateral(value: object):
  """Collateral plus non-negative margins, maintenance within initial, and a mode."""
  require(isinstance(value, PerpCollateral), 'perp_collateral: not a PerpCollateral')
  collateral = cast(PerpCollateral, value)
  try:
    check_collateral(collateral, spot=False)
  except AccountCheckError as error:
    raise AccountCheckError(f'perp_{error}') from None
  margins = (collateral.initial_margin, collateral.maintenance_margin)
  require(
    all(finite(margin) and margin >= 0 for margin in margins),
    'perp_collateral: invalid margin',
  )
  require(
    collateral.maintenance_margin <= collateral.initial_margin,
    'perp_collateral: maintenance margin exceeds initial margin',
  )
  require(
    finite(collateral.leverage) and collateral.leverage >= 0,
    'perp_collateral: invalid leverage',
  )
  require(
    collateral.margin_mode in ('cross', 'isolated'), 'perp_collateral: unknown mode'
  )


def check_leverage(value: object):
  """A finite, positive leverage."""
  require(finite(value) and cast(Decimal, value) > 0, 'leverage: not positive')


def check_available_notional(value: object):
  """A finite, non-negative opening capacity; venue caps may lower it (ADR 0041)."""
  require(finite(value) and cast(Decimal, value) >= 0, 'available_notional: negative')


def check(method: str, result: AccountResults):
  """Validate one collected read against its contract."""
  value = result.values[method]
  if method == 'fees':
    check_fees(value)
  elif method == 'open_orders':
    check_open_orders(value)
  elif method == 'trades_history':
    rules = result.values.get('rules')
    require(isinstance(rules, Rules), 'trades_history: rules() was not read')
    check_trades(
      value,
      start=result.start,
      end=result.end,
      fee_asset=cast(Rules, rules).fee_asset,
    )
  elif method == 'funding_payments':
    check_funding_payments(value, start=result.start, end=result.end)
  elif method == 'position':
    check_position(value, spot=result.spot)
  elif method == 'perp_position':
    check_perp_position(value, result.values.get('position'))
  elif method == 'collateral':
    check_collateral(value, spot=result.spot)
  elif method == 'perp_collateral':
    check_perp_collateral(value)
  elif method == 'leverage':
    check_leverage(value)
  elif method == 'available_notional':
    check_available_notional(value)
  else:
    raise AccountCheckError(f'{method}: no check defined')


def pytest_generate_tests(metafunc: pytest.Metafunc):
  """Cover every selected account's reference markets."""
  if 'account_market' not in metafunc.fixturenames:
    return
  sdk = market_sdk(metafunc.config)
  ids = [
    f'{account}:{case.market_id}'
    for account in selected_accounts(metafunc.config, sdk.accounts, surface='market')
    for case in cases_of(sdk.accounts[account].venue)
  ]
  metafunc.parametrize('account_market', ids, ids=ids, scope='module')


@pytest.fixture(scope='module')
def account_plan(account_market: str, pytestconfig: pytest.Config) -> AccountPlan:
  """The exclusion policy for one account and reference market."""
  return plan_of(market_sdk(pytestconfig), account_market)


@pytest.fixture(scope='module')
def account_result(
  account_market: str, account_plan: AccountPlan, pytestconfig: pytest.Config
) -> AccountResults:
  """Collect every required read once per account and reference market."""
  methods = [m for m, code in account_plan.exclusions.items() if runs(code)]
  sdk = market_sdk(pytestconfig)
  return loop_of(pytestconfig).run_until_complete(
    collect_account(sdk, account_market, methods)
  )


def runs(exclusion: str | None) -> bool:
  """Whether a case runs: required reads and waived reads, which may still pass."""
  return exclusion is None or exclusion.startswith(WAIVED)


@pytest.mark.parametrize('method', ACCOUNT_READS)
def test_account_read(
  account_market: str,
  method: str,
  account_plan: AccountPlan,
  request: pytest.FixtureRequest,
):
  """Validate one account read; declared reads that raise are failures.

  A waived read still runs and passes when it works; only its waiver's expected
  error becomes a skip, so a stale waiver shows up as a pass in the evidence.
  """
  exclusion = account_plan.exclusions[method]
  if not runs(exclusion):
    pytest.skip(f'Excluded by policy: {exclusion}')
  if account_plan.below_minimum:
    pytest.skip("Account credentials are below the venue's qualification mode")
  result = cast(AccountResults, request.getfixturevalue('account_result'))
  if method in result.failures:
    if exclusion is not None and issubclass(
      result.errors.get(method, Exception),
      WAIVED_ERRORS[exclusion.removeprefix(WAIVED)],
    ):
      pytest.skip(f'Waived ({exclusion}): {result.failures[method]}')
    pytest.fail(f'{method}: {result.failures[method]}', pytrace=False)
  try:
    check(method, result)
  except AccountCheckError as error:
    pytest.fail(str(error), pytrace=False)
  except Exception as error:
    pytest.fail(f'{method}: malformed value ({type(error).__name__})', pytrace=False)
