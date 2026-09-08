"""Live conformance tests for the Bitget market implementation.

The shared `suite.py` covers `candles`; this module covers the rest of the surface. One
event loop per account runs every method once (`Results`), and each test reads its
outcome back, so a single account's run is one connection and one catalogue fetch
rather than one per test. Accounts: the credential-free `bitget` default, plus every
`accounts.Bitget` entry in the accounts config -- `sdk.test.toml` carries one Classic
and one UTA account, which is what exercises both dispatch branches.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import asyncio

import pytest

from typing_extensions import Any, Awaitable, Callable, Sequence, cast

from tribulnation.sdk import AuthError, Context, MarketSDK, NetworkError, RateLimited
from tribulnation.sdk.impl.accounts import Bitget
from tribulnation.sdk.core import PaginatedResponse
from tribulnation.sdk.market import Book, Candle, PerpCollateral, Rules, Ticker
from ..support import describe_exception
from .conftest import SDK

VENUE = 'bitget'
SYMBOL = 'BTCUSDT'
OTHER = 'ETHUSDT'

SPOT_CANDLES_PAGE = 999
"""Candles per page the spot implementation yields."""

CANDLES_END = (datetime.now(timezone.utc) - timedelta(days=1)).replace(
  minute=0, second=0, microsecond=0
)
"""Open time of the last hourly spot candle asked for: a closed candle, a day ago, so the
counts are exact and the window stays inside the recent endpoint's two-month horizon."""

STREAM_TIMEOUT = 20
"""Seconds to wait for a stream to deliver its first item, or to confirm a subscription."""


def market_sdk(config: pytest.Config) -> MarketSDK:
  """The session's `MarketSDK`, shared with the candle suite through its stash key."""
  sdk = config.stash.get(SDK, None)
  if sdk is None:
    sdk = MarketSDK.load(cast(str, config.getoption('accounts_config')))
    config.stash[SDK] = sdk
  return sdk


def pytest_generate_tests(metafunc: pytest.Metafunc):
  """Parameterize this module over every configured Bitget account, the
  credential-free default included, so the public surface is exercised without keys."""
  if 'market_account' not in metafunc.fixturenames:
    return
  sdk = market_sdk(metafunc.config)
  ids = [id for id, account in sdk.all_accounts.items() if account.venue == VENUE]
  metafunc.parametrize('market_account', ids, ids=ids, scope='module')


@dataclass(frozen=True)
class Failure:
  """One method's failure: the exception, and a description safe to print."""

  error: Exception
  message: str


@dataclass
class Results:
  """Every method's outcome for one account, collected in one event loop.

  Each method is attempted on its own, so one failure never hides the others, and the
  tests read the outcomes back with `check` (a value) or `expect` (a raise).
  """

  values: dict[str, Any] = field(default_factory=dict[str, Any])

  async def attempt(self, name: str, call: Callable[[], Awaitable[Any]]):
    """Run one method under the shared retry policy and record its outcome."""
    try:
      with Context().retried(NetworkError, RateLimited, max_retries=3).use():
        self.values[name] = await call()
    except Exception as exception:
      self.values[name] = Failure(exception, describe_exception(exception))

  async def first(self, name: str, open: Callable[[], Any]):
    """Record the first item a stream context delivers, within `STREAM_TIMEOUT`."""

    async def take():
      async with open() as stream:
        async for item in stream:
          return item
        raise AssertionError('stream ended before delivering anything')

    await self.attempt(name, lambda: asyncio.wait_for(take(), STREAM_TIMEOUT))

  async def subscribes(self, name: str, open: Callable[[], Any]):
    """Record that a stream context can be entered and left, within `STREAM_TIMEOUT`.

    A fill stream on an account that isn't trading delivers nothing, so the proof is
    the subscription itself: login, subscribe ack and clean unsubscribe.
    """

    async def enter():
      async with open():
        await asyncio.sleep(1)
      return True

    await self.attempt(name, lambda: asyncio.wait_for(enter(), STREAM_TIMEOUT))

  def check(self, name: str) -> Any:
    """The recorded value, failing the test on a recorded failure."""
    if name not in self.values:
      pytest.skip(f'{name} was not collected for this account')
    value = self.values[name]
    if isinstance(value, Failure):
      pytest.fail(f'{name}: {value.message}', pytrace=False)
    return value

  def expect(self, name: str, error: type[Exception]):
    """Assert the method raised `error`, the declared outcome for this account."""
    if name not in self.values:
      pytest.skip(f'{name} was not collected for this account')
    value = self.values[name]
    if not isinstance(value, Failure):
      pytest.fail(f'{name}: expected {error.__name__}, got a value', pytrace=False)
    if not isinstance(value.error, error):
      pytest.fail(
        f'{name}: expected {error.__name__}, got {value.message}', pytrace=False
      )


HOUR = timedelta(hours=1)


async def pages(paging: PaginatedResponse[Candle]) -> list[Sequence[Candle]]:
  """Every page of a candle walk, as yielded."""
  return [page async for page in paging]


async def collect(sdk: MarketSDK, account_id: str, public: bool, results: Results):
  """Run every method against one account."""
  venue = await sdk.venue(account_id)
  end = datetime.now(timezone.utc)
  start = end - timedelta(days=30)
  async with venue:
    spot = await venue.exchange('spot')
    perp = await venue.perp_exchange('perp')
    await results.attempt('exchanges', venue.exchanges)
    spot_market = await spot.market(SYMBOL)
    perp_market = await perp.market(SYMBOL)
    # Public: spot.
    await results.attempt('spot.markets', spot.markets)
    await results.attempt('spot.depth', spot_market.depth)
    await results.attempt('spot.depth.levels', lambda: spot_market.depth(levels=5))
    await results.attempt('spot.tickers', spot.tickers)
    await results.attempt('spot.tickers.some', lambda: spot.tickers([SYMBOL, OTHER]))
    await results.attempt('spot.rules', spot_market.rules)
    await results.attempt(
      'spot.candles',
      lambda: pages(spot_market.candles('1h', CANDLES_END - 71 * HOUR, CANDLES_END)),
    )
    await results.attempt(
      'spot.candles.straddle',
      lambda: pages(
        spot_market.candles(
          '1h', CANDLES_END - (SPOT_CANDLES_PAGE + 49) * HOUR, CANDLES_END
        )
      ),
    )
    await results.first('spot.depth_stream', spot_market.depth_stream)
    # Public: perp.
    await results.attempt('perp.markets', perp.markets)
    await results.attempt('perp.depth', perp_market.depth)
    await results.attempt('perp.depth.levels', lambda: perp_market.depth(levels=7))
    await results.attempt('perp.tickers', perp.tickers)
    await results.attempt('perp.tickers.some', lambda: perp.tickers([SYMBOL, OTHER]))
    await results.attempt('perp.rules', perp_market.rules)
    await results.first('perp.depth_stream', lambda: perp_market.depth_stream(levels=3))
    await results.attempt('perp.index', perp_market.index)
    await results.attempt('perp.next_funding', perp_market.next_funding)
    await results.attempt(
      'perp.funding_rates', lambda: perp_market.funding_rates(start, end)
    )
    await results.attempt('perp.perp_stats', perp.perp_stats)
    await results.attempt('perp.perp_stats.some', lambda: perp.perp_stats([SYMBOL]))
    # Trading is deliberately unimplemented.
    await results.attempt(
      'spot.place_order',
      lambda: spot_market.place_order(
        {'qty': Decimal('0.0001'), 'price': Decimal(1), 'type': 'LIMIT'}
      ),
    )
    # Account-scoped.
    await results.attempt('spot.open_orders', spot_market.open_orders)
    if public:
      return
    await results.attempt(
      'spot.trades_history', lambda: spot_market.trades_history(start, end)
    )
    await results.attempt('spot.position', spot_market.position)
    await results.attempt('spot.collateral', spot_market.collateral)
    await results.attempt('spot.collateral.pool', spot.collateral)
    await results.attempt('spot.available_notional', spot_market.available_notional)
    await results.subscribes('spot.trades_stream', spot_market.trades_stream)
    await results.attempt('perp.open_orders', perp_market.open_orders)
    await results.attempt(
      'perp.trades_history', lambda: perp_market.trades_history(start, end)
    )
    await results.attempt('perp.perp_position', perp_market.perp_position)
    await results.attempt('perp.position', perp_market.position)
    await results.attempt('perp.perp_collateral', perp_market.perp_collateral)
    await results.attempt('perp.perp_collateral.pool', perp.perp_collateral)
    await results.attempt('perp.available_notional', perp_market.available_notional)
    await results.attempt(
      'perp.funding_payments', lambda: perp_market.funding_payments(start, end)
    )
    await results.subscribes('perp.trades_stream', perp_market.trades_stream)


@pytest.fixture(scope='module')
def bitget(market_account: str, pytestconfig: pytest.Config) -> Results:
  """Every method's outcome for one account."""
  sdk = market_sdk(pytestconfig)
  account = sdk.all_accounts[market_account]
  assert isinstance(account, Bitget)
  results = Results()
  results.values['public'] = account.public
  results.values['uta'] = account.uta
  asyncio.run(collect(sdk, market_account, account.public, results))
  return results


def is_classic(bitget: Results) -> bool:
  """Whether the account under test declared Classic mode."""
  return bitget.values['uta'] is False


def test_exchanges(bitget: Results):
  """Both exchanges are listed."""
  assert {e['id'] for e in bitget.check('exchanges')} == {'spot', 'perp'}


def test_spot_markets(bitget: Results):
  """The spot catalogue lists the reference pair."""
  markets = bitget.check('spot.markets')
  assert SYMBOL in markets and len(markets) > 100


def test_spot_depth(bitget: Results):
  """The spot book is two-sided, best-first and capped by `levels`."""
  book: Book = bitget.check('spot.depth')
  assert book.best_bid.price < book.best_ask.price
  assert book.bids[0].price > book.bids[-1].price
  assert len(bitget.check('spot.depth.levels').bids) == 5


def test_spot_tickers(bitget: Results):
  """One call covers the universe, and a subset call keeps only what was asked."""
  tickers: dict[str, Ticker] = bitget.check('spot.tickers')
  assert len(tickers) > 100
  t = tickers[SYMBOL]
  assert t.bid is not None and t.ask is not None and t.bid <= t.ask
  assert t.last is not None and t.base_volume_24h is not None
  assert set(bitget.check('spot.tickers.some')) == {SYMBOL, OTHER}


def test_spot_rules(bitget: Results):
  """Rules carry the pair's assets, sizes and the venue's default fees."""
  rules: Rules = bitget.check('spot.rules')
  assert (rules.base, rules.quote) == ('BTC', 'USDT')
  assert rules.tick_size > 0 and rules.step_size > 0
  assert rules.taker_fee >= rules.maker_fee >= 0
  assert rules.api


def check_spot_candles(result: list[Sequence[Candle]], *, count: int):
  """The spot candle contract over a recent window: exact count, ascending, aligned."""
  candles = [c for page in result for c in page]
  assert len(candles) == count, f'expected {count} candles, got {len(candles)}'
  first = CANDLES_END - (count - 1) * HOUR
  assert [c.time for c in candles] == [first + k * HOUR for k in range(count)]
  for page in result:
    assert page, 'an empty page was yielded'
  for previous, page in zip(result, result[1:]):
    assert previous[-1].time < page[0].time, 'pages overlap or are out of order'
  for candle in candles:
    assert candle.low <= candle.open <= candle.high
    assert candle.low <= candle.close <= candle.high
    assert isinstance(candle.volume, Decimal) and isinstance(
      candle.quote_volume, Decimal
    )


def test_spot_candles(bitget: Results):
  """Three days of hourly spot candles, ending a day ago, come back exact."""
  check_spot_candles(bitget.check('spot.candles'), count=72)


def test_spot_candles_straddling_two_pages(bitget: Results):
  """A window one page plus fifty candles wide yields two pages, every candle once."""
  result = bitget.check('spot.candles.straddle')
  assert len(result) >= 2, 'the window did not straddle two pages'
  check_spot_candles(result, count=SPOT_CANDLES_PAGE + 50)


def test_spot_depth_stream(bitget: Results):
  """The order book stream delivers a whole, two-sided book."""
  book: Book = bitget.check('spot.depth_stream')
  assert book.bids and book.asks and book.best_bid.price < book.best_ask.price


def test_perp_markets(bitget: Results):
  """The perpetual catalogue lists the reference contract."""
  markets = bitget.check('perp.markets')
  assert SYMBOL in markets and len(markets) > 100


def test_perp_depth(bitget: Results):
  """The futures book is two-sided and trimmed to a depth off the venue's enum."""
  book: Book = bitget.check('perp.depth')
  assert book.best_bid.price < book.best_ask.price
  assert len(book.bids) > 50
  assert len(bitget.check('perp.depth.levels').asks) == 7


def test_perp_tickers(bitget: Results):
  """One call covers the universe, and a subset call keeps only what was asked."""
  tickers: dict[str, Ticker] = bitget.check('perp.tickers')
  t = tickers[SYMBOL]
  assert t.bid is not None and t.ask is not None and t.bid <= t.ask
  assert set(bitget.check('perp.tickers.some')) == {SYMBOL, OTHER}


def test_perp_rules(bitget: Results):
  """Rules carry the contract's assets, sizes and fees."""
  rules: Rules = bitget.check('perp.rules')
  assert (rules.base, rules.quote, rules.fee_asset) == ('BTC', 'USDT', 'USDT')
  assert rules.tick_size > 0 and rules.step_size > 0 and rules.api


def test_perp_depth_stream(bitget: Results):
  """The futures order book stream delivers a whole book, trimmed to `levels`."""
  book: Book = bitget.check('perp.depth_stream')
  assert len(book.bids) == 3 and book.best_bid.price < book.best_ask.price


def test_perp_index(bitget: Results):
  """The index price is a positive figure near the book."""
  index: Decimal = bitget.check('perp.index')
  book: Book = bitget.check('perp.depth')
  assert abs(index / book.mark_price - 1) < Decimal('0.05')


def test_perp_next_funding(bitget: Results):
  """The next settlement is in the future, on a whole-hour interval."""
  funding = bitget.check('perp.next_funding')
  assert funding.time > datetime.now(timezone.utc)
  assert funding.interval.total_seconds() % 3600 == 0


def test_perp_funding_rates(bitget: Results):
  """A month of settlements, all inside the window, newest first."""
  rates = bitget.check('perp.funding_rates')
  times = [r.time for r in rates]
  assert len(times) >= 60  # every 8h or better
  assert times == sorted(times, reverse=True)
  assert times[0] - times[-1] < timedelta(days=31)


def test_perp_stats(bitget: Results):
  """Every perpetual gets index, mark, funding and open interest in one snapshot."""
  stats = bitget.check('perp.perp_stats')
  s = stats[SYMBOL]
  assert s.index > 0 and s.mark is not None and s.funding is not None
  assert s.next_funding_time is not None and s.funding_interval is not None
  assert s.open_interest is not None and s.open_interest > 0
  assert set(bitget.check('perp.perp_stats.some')) == {SYMBOL}


def test_place_order_unimplemented(bitget: Results):
  """Trading is not implemented: we do not trade on Bitget."""
  bitget.expect('spot.place_order', NotImplementedError)


def test_spot_open_orders(bitget: Results):
  """Open orders are listed; a credential-free account is refused, not answered."""
  if bitget.values['public']:
    bitget.expect('spot.open_orders', AuthError)
  else:
    assert isinstance(bitget.check('spot.open_orders'), list)


def test_spot_trades_history(bitget: Results):
  """Fills over the last month parse, every one on the reference pair's own sign."""
  for trade in bitget.check('spot.trades_history'):
    assert trade.price > 0 and trade.qty != 0


def test_spot_position(bitget: Results):
  """A spot position is a non-negative base balance."""
  assert bitget.check('spot.position').size >= 0


def test_spot_collateral(bitget: Results):
  """Market-level collateral is the quote balance; the pool exists only on UTA."""
  collateral = bitget.check('spot.collateral')
  assert collateral.equity >= collateral.free_collateral >= 0
  assert bitget.check('spot.available_notional') == collateral.free_collateral
  if is_classic(bitget):
    bitget.expect('spot.collateral.pool', NotImplementedError)
  else:
    assert bitget.check('spot.collateral.pool').equity > 0


def test_spot_trades_stream(bitget: Results):
  """The private fill channel can be subscribed and left cleanly."""
  assert bitget.check('spot.trades_stream') is True


def test_perp_open_orders(bitget: Results):
  """Open perpetual orders are listed."""
  assert isinstance(bitget.check('perp.open_orders'), list)


def test_perp_trades_history(bitget: Results):
  """Perpetual fills over the last month parse with their fees."""
  for trade in bitget.check('perp.trades_history'):
    assert trade.price > 0 and trade.qty != 0
    assert trade.fee is not None and trade.fee.asset == 'USDT'


def test_perp_position(bitget: Results):
  """The perpetual position is reported, and `position()` agrees with it."""
  position = bitget.check('perp.perp_position')
  assert bitget.check('perp.position').size == position.size


def test_perp_collateral(bitget: Results):
  """UTA reports its margin pool; Classic has no margin figures to report."""
  if is_classic(bitget):
    bitget.expect('perp.perp_collateral', NotImplementedError)
    bitget.expect('perp.perp_collateral.pool', NotImplementedError)
  else:
    collateral: PerpCollateral = bitget.check('perp.perp_collateral')
    assert collateral.equity > 0 and collateral.margin_mode in ('cross', 'isolated')
    assert bitget.check('perp.perp_collateral.pool').margin_mode == 'cross'


def test_perp_available_notional(bitget: Results):
  """Opening capacity is a non-negative figure in either mode."""
  assert bitget.check('perp.available_notional') >= 0


def test_perp_funding_payments_unsupported(bitget: Results):
  """Funding payments are not supported: no documented ledger type to filter on."""
  bitget.expect('perp.funding_payments', NotImplementedError)


def test_perp_trades_stream(bitget: Results):
  """The private fill channel can be subscribed and left cleanly."""
  assert bitget.check('perp.trades_stream') is True
