"""Market mappings from rows the venue sent: rules and fees, tickers and stats, funding,
books, positions, collateral and leverage."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from typing_extensions import Any, AsyncIterator
from typed_core.util import Stream

from tribulnation.grvt.core import Shared
from tribulnation.grvt.market import books
from tribulnation.grvt.market.exchanges import GrvtPerpExchange
from tribulnation.grvt.market.markets import GrvtPerpMarket
from tribulnation.sdk.core import MissingData
from tribulnation.sdk.market import Book, Fees, NextFunding, PerpPosition

BTC = 'BTC_USDT_Perp'
ETH = 'ETH_USDT_Perp'
NEXT = datetime(2026, 10, 22, 16, tzinfo=timezone.utc)


def market(shared: Shared, name: str = BTC) -> GrvtPerpMarket:
  """A market object over `shared`."""
  return GrvtPerpMarket(shared=shared, instrument=name)


def ticker(**changes: object) -> dict[str, Any]:
  """BTC's mainnet ticker (2026-10-22), with `changes`."""
  row: dict[str, Any] = {
    'instrument': BTC,
    'mark_price': Decimal('81899.8'),
    'index_price': Decimal('81942.5'),
    'last_price': Decimal('81895.2'),
    'best_bid_price': Decimal('81894.7'),
    'best_bid_size': Decimal('1.227'),
    'best_ask_price': Decimal('81894.8'),
    'best_ask_size': Decimal('3.663'),
    'buy_volume_24h_b': Decimal('1000.5'),
    'sell_volume_24h_b': Decimal('958.33'),
    'buy_volume_24h_q': Decimal('80000000.9'),
    'sell_volume_24h_q': Decimal('83802233.035'),
    'open_interest': Decimal('2517.5'),
    'funding_rate': Decimal('0.01'),
    'next_funding_time': NEXT,
  }
  return {**row, **changes}


async def test_rules_use_the_instrument_and_published_tier_one(shared: Shared):
  """`min_size` is the step and the minimum; fees are tier 1 of the published schedule,
  charged in the quote; `api` follows `status`."""
  rules = await market(shared).rules()
  assert (rules.tick_size, rules.step_size, rules.fixed_min_qty, rules.min_value) == (
    Decimal('0.1'),
    Decimal('0.001'),
    Decimal('0.001'),
    Decimal('100.0'),
  )
  assert rules.fee_asset == 'USDT' and rules.api
  assert rules.fees == Fees.symmetric(
    maker=Decimal('-0.000001'), taker=Decimal('0.00045')
  )


async def test_delisted_markets_stay_listed_without_api(
  make_fake: Any, make_shared: Any, make_instrument: Any
):
  """Discovery lists delisted perpetuals; their rules say they do not trade."""
  shared = make_shared(
    make_fake(),
    make_instrument(BTC),
    make_instrument('OLD_USDT_Perp', status='DELISTED'),
  )
  exchange = GrvtPerpExchange(shared=shared)
  assert await exchange.markets() == [BTC, 'OLD_USDT_Perp']
  assert not (await exchange.rules('OLD_USDT_Perp')).api
  with pytest.raises(ValueError):
    await exchange.market('NOPE_USDT_Perp')


async def test_fees_scale_the_tier_from_millionths(shared: Shared, fake: Any):
  """`ClientTier` rates are millionths of notional: tier 1 is -1 and 450."""

  async def summary() -> dict[str, Any]:
    """Tier 1."""
    return {
      'result': {},
      'tier': {'tier': 1, 'futures_maker_fee': -1, 'futures_taker_fee': 450},
    }

  fake.trading.funding_account_summary = summary
  fees = await market(shared).fees()
  assert fees == Fees.symmetric(maker=Decimal('-0.000001'), taker=Decimal('0.00045'))


async def test_tickers_map_empty_sides_to_none(shared: Shared, fake: Any):
  """A `0` price is an empty side; volumes add taker buys and sells; unknown names are
  left out, and an empty selection makes no request."""
  sent: list[tuple[str, str]] = []

  async def one(instrument: str, *, transport: str = 'http') -> dict[str, Any]:
    """BTC as quoted; ETH delisted with an empty book."""
    sent.append((instrument, transport))
    if instrument == ETH:
      return ticker(
        instrument=ETH, best_bid_price=Decimal(0), best_ask_price=Decimal(0)
      )
    return ticker()

  fake.market.ticker = one
  exchange = GrvtPerpExchange(shared=shared)
  tickers = await exchange.tickers([BTC, ETH, 'NOPE_USDT_Perp'])
  btc, eth = tickers[BTC], tickers[ETH]
  assert (btc.bid, btc.ask, btc.bid_qty, btc.ask_qty) == (
    Decimal('81894.7'),
    Decimal('81894.8'),
    Decimal('1.227'),
    Decimal('3.663'),
  )
  assert btc.base_volume_24h == Decimal('1958.83')
  assert btc.quote_volume_24h == Decimal('163802233.935')
  assert (eth.bid, eth.ask, eth.bid_qty, eth.ask_qty) == (None, None, None, None)
  assert set(sent) == {(BTC, 'ws'), (ETH, 'ws')}
  sent.clear()
  assert await exchange.tickers([]) == {}
  assert sent == []


async def test_next_funding_converts_percent_and_reads_the_interval(
  make_fake: Any, make_shared: Any, make_instrument: Any
):
  """The ticker rate is in percentage points; the interval is the instrument's."""
  fake = make_fake()
  shared = make_shared(fake, make_instrument('XAU_USDT_Perp', funding_interval_hours=4))

  async def one(instrument: str, *, transport: str = 'http') -> dict[str, Any]:
    """XAU's indicative rate."""
    return ticker(instrument=instrument, funding_rate=Decimal('0.0017'))

  fake.market.ticker = one
  funding = await market(shared, 'XAU_USDT_Perp').next_funding()
  assert funding == NextFunding(
    rate=Decimal('0.000017'), time=NEXT, interval=timedelta(hours=4)
  )
  assert funding.premium is None


async def test_next_funding_without_a_rate_is_missing_data(shared: Shared, fake: Any):
  """A ticker without its rate raises rather than inventing one."""

  async def one(instrument: str, *, transport: str = 'http') -> dict[str, Any]:
    """No funding rate."""
    row = ticker()
    del row['funding_rate']
    return row

  fake.market.ticker = one
  with pytest.raises(MissingData) as caught:
    await market(shared).next_funding()
  assert (caught.value.market_id, caught.value.field) == (BTC, 'rate')


async def test_perp_stats_leave_out_an_unpriced_market_only_in_bulk(
  shared: Shared, fake: Any
):
  """Reading every market omits one without an index (ADR 0030); naming it raises."""

  async def one(instrument: str, *, transport: str = 'http') -> dict[str, Any]:
    """ETH has no index price."""
    if instrument == ETH:
      row = ticker(instrument=ETH)
      del row['index_price']
      return row
    return ticker()

  fake.market.ticker = one
  exchange = GrvtPerpExchange(shared=shared)
  stats = await exchange.perp_stats()
  assert list(stats) == [BTC]
  btc = stats[BTC]
  assert (btc.index, btc.mark, btc.funding, btc.open_interest) == (
    Decimal('81942.5'),
    Decimal('81899.8'),
    Decimal('0.0001'),
    Decimal('2517.5'),
  )
  assert (btc.next_funding_time, btc.funding_interval) == (NEXT, timedelta(hours=8))
  with pytest.raises(MissingData):
    await exchange.perp_stats([ETH])


async def test_index_is_the_mini_ticker_index(shared: Shared, fake: Any):
  """The mini ticker's `index_price`; without one, `MissingData`."""

  async def mini(instrument: str) -> dict[str, Any]:
    """BTC's mini ticker."""
    return {'index_price': Decimal('81942.507239541')}

  fake.market.mini_ticker = mini
  assert await market(shared).index() == Decimal('81942.507239541')

  async def empty(instrument: str) -> dict[str, Any]:
    """No index."""
    return {}

  fake.market.mini_ticker = empty
  with pytest.raises(MissingData):
    await market(shared).index()


@pytest.mark.parametrize(
  'levels,depth', [(None, 500), (1, 10), (10, 10), (11, 50), (100, 100), (600, 500)]
)
def test_depth_asks_the_smallest_covering_venue_depth(levels: int | None, depth: int):
  """10, 50, 100 or 500 levels per side; the largest when nothing covers."""
  assert books.venue_depth(levels) == depth


def levels(*rows: tuple[str, str]) -> list[dict[str, Any]]:
  """Book levels from `(price, size)` pairs."""
  return [{'price': Decimal(p), 'size': Decimal(s), 'num_orders': 1} for p, s in rows]


def frame(bids: list[dict[str, Any]], asks: list[dict[str, Any]], second: int) -> Any:
  """One `v1.book.d` frame."""
  return {
    'event_time': datetime(2026, 10, 22, 9, 0, second, tzinfo=timezone.utc),
    'instrument': BTC,
    'bids': bids,
    'asks': asks,
  }


async def test_depth_stream_applies_deltas_after_the_snapshot(
  shared: Shared, fake: Any
):
  """Books start once every snapshot frame arrived; a zero size deletes a level."""
  frames = [
    frame(levels(('100', '1'), ('99', '2')), levels(('101', '1')), 0),
    frame([], levels(('102', '3')), 0),
    frame(levels(('100', '0')), levels(('101', '4')), 1),
  ]
  unsubscribed: list[bool] = []

  async def pushed() -> AsyncIterator[Any]:
    """The snapshot (two frames), then one delta."""
    for f in frames:
      yield f

  async def unsubscribe():
    """Record the unsubscription."""
    unsubscribed.append(True)

  async def orderbook_delta(instrument: str, *, rate: int) -> Stream[Any, Any, Any]:
    """Two snapshot frames, at the fastest rate."""
    assert (instrument, rate) == (BTC, 50)
    reply = {'num_snapshots': [2]}
    return Stream(reply=reply, stream=pushed(), unsubscribe=unsubscribe)

  fake.market_streams.orderbook_delta = orderbook_delta
  seen: list[Book] = []
  async with market(shared).depth_stream(queue_size=10, overflow='fail') as stream:
    async for book in stream:
      seen.append(book)
      if len(seen) == 2:
        break
  first, second = seen
  assert [(e.price, e.qty) for e in first.bids] == [(100, 1), (99, 2)]
  assert [(e.price, e.qty) for e in first.asks] == [(101, 1), (102, 3)]
  assert [(e.price, e.qty) for e in second.bids] == [(99, 2)]
  assert [(e.price, e.qty) for e in second.asks] == [(101, 4), (102, 3)]
  assert second.time == datetime(2026, 10, 22, 9, 0, 1, tzinfo=timezone.utc)
  assert unsubscribed == [True]


def position(name: str, size: str, margin_type: str = 'CROSS') -> dict[str, Any]:
  """A position row of `account_summary` and `positions`."""
  return {
    'instrument': name,
    'size': Decimal(size),
    'notional': Decimal(size) * 81835,
    'entry_price': Decimal('81835.0'),
    'unrealized_pnl': Decimal(0),
    'margin_type': margin_type,
  }


def summary(*positions: dict[str, Any]) -> dict[str, Any]:
  """Testnet's flat sub-account summary (2026-10-22), with `positions` listed: in
  multi-asset mode `margin_balance` is equity at the 99.8% collateral value ratio."""
  return {
    'total_equity': Decimal('20018.031815'),
    'total_cross_equity': Decimal('20018.031815'),
    'margin_balance': Decimal('19977.995751'),
    'initial_margin': Decimal('0.0'),
    'maintenance_margin': Decimal('0.0'),
    'positions': list(positions),
  }


def mixed_summary() -> dict[str, Any]:
  """Testnet's sub-account summary while holding 0.084 ETH cross and 0.002 BTC isolated
  at 10x (2026-10-22): the account margins are the cross position's alone. Read with
  BTC's margin limits: `max_addable_amount` `19941.26479`, `max_removable_amount`
  `0.00944`."""
  return {
    'total_equity': Decimal('20017.733633'),
    'total_cross_equity': Decimal('20001.403174'),
    'margin_balance': Decimal('19961.400456'),
    'initial_margin': Decimal('20.135665'),
    'maintenance_margin': Decimal('2.013566'),
    'positions': [
      {
        'instrument': ETH,
        'size': Decimal('0.084'),
        'notional': Decimal('201.356658'),
        'unrealized_pnl': Decimal('0.043938'),
        'margin_type': 'CROSS',
      },
      {
        'instrument': BTC,
        'size': Decimal('0.002'),
        'notional': Decimal('163.210188'),
        'unrealized_pnl': Decimal('-0.177811'),
        'margin_type': 'ISOLATED',
        'isolated_balance': Decimal('16.50827'),
        'isolated_im': Decimal('16.321018'),
        'isolated_mm': Decimal('1.632101'),
      },
    ],
  }


async def mixed(fake: Any) -> list[int]:
  """Serve `mixed_summary` and the default 10x leverage; returns the leverage call log."""
  calls: list[int] = []

  async def account_summary() -> dict[str, Any]:
    """ETH cross, BTC isolated."""
    return mixed_summary()

  async def all_initial_leverage() -> dict[str, Any]:
    """Both at the default 10x."""
    calls.append(1)
    rows: list[dict[str, Any]] = [
      {'instrument': m, 'leverage': Decimal('10.0')} for m in (BTC, ETH)
    ]
    return {'results': rows}

  fake.trading.account_summary = account_summary
  fake.trading.all_initial_leverage = all_initial_leverage
  return calls


async def test_perp_position_is_signed(shared: Shared, fake: Any):
  """The position of the market, signed; flat when the venue lists none."""
  requests: list[dict[str, Any]] = []

  async def positions(**kwargs: Any) -> list[dict[str, Any]]:
    """A short BTC position."""
    requests.append(kwargs)
    return [position(BTC, '-0.002')]

  fake.trading.positions = positions
  assert await market(shared).perp_position() == PerpPosition(
    size=Decimal('-0.002'), entry_price=Decimal('81835.0')
  )
  assert requests == [{'kind': ['PERPETUAL'], 'base': ['BTC'], 'quote': ['USDT']}]
  assert await market(shared, ETH).perp_position() == PerpPosition()


async def test_cross_bucket_and_available_notional(shared: Shared, fake: Any):
  """Equity is the cross equity; free collateral is `margin_balance` less the cross
  initial margin (the venue's `max_addable_amount`, `19941.26479`, in the same read);
  leverage is cross notional over equity; available notional is free collateral times
  the account's leverage, for the isolated market too; one leverage read serves
  every market for the caller's `ttl`."""
  calls = await mixed(fake)
  eth = market(shared, ETH)
  cross = await eth.perp_collateral()
  assert cross.margin_mode == 'cross'
  assert cross.equity == Decimal('20001.403174')
  assert (cross.initial_margin, cross.maintenance_margin) == (
    Decimal('20.135665'),
    Decimal('2.013566'),
  )
  assert cross.free_collateral == Decimal('19941.264791')
  assert cross.leverage == Decimal('201.356658') / Decimal('20001.403174')
  assert await GrvtPerpExchange(shared=shared).perp_collateral() == cross
  minute = timedelta(minutes=1)
  assert await eth.available_notional(ttl=minute) == Decimal('199412.64791')
  assert await market(shared).available_notional(ttl=minute) == Decimal('199412.64791')
  assert await eth.leverage(ttl=minute) == 10 and calls == [1]
  assert await eth.leverage() == 10 and calls == [1, 1]


async def test_flat_cross_bucket(shared: Shared, fake: Any):
  """No cross position: leverage is exactly zero and free collateral is the whole
  `margin_balance`."""

  async def account_summary() -> dict[str, Any]:
    """Flat."""
    return summary()

  fake.trading.account_summary = account_summary
  bucket = await market(shared).perp_collateral()
  assert bucket.leverage == 0 and bucket.equity == Decimal('20018.031815')
  assert bucket.free_collateral == Decimal('19977.995751')


async def test_cross_free_collateral_floors_at_zero(shared: Shared, fake: Any):
  """An initial margin above `margin_balance` leaves nothing free, never less."""

  async def account_summary() -> dict[str, Any]:
    """Margin balance below the initial margin."""
    return {**summary(), 'margin_balance': Decimal(10), 'initial_margin': Decimal(12)}

  fake.trading.account_summary = account_summary
  assert (await market(shared).perp_collateral()).free_collateral == 0


async def test_isolated_position_has_its_own_bucket(shared: Shared, fake: Any):
  """An isolated position's bucket is its own balance plus unrealized PnL against its
  own margins; free is the excess over its initial margin (the venue's
  `max_removable_amount`, `0.00944`, in the same read)."""
  await mixed(fake)
  isolated = await market(shared).perp_collateral()
  assert isolated.margin_mode == 'isolated'
  assert isolated.equity == Decimal('16.330459')
  assert (isolated.initial_margin, isolated.maintenance_margin) == (
    Decimal('16.321018'),
    Decimal('1.632101'),
  )
  assert isolated.free_collateral == Decimal('0.009441')
  assert isolated.leverage == Decimal('163.210188') / Decimal('16.330459')


async def test_added_isolated_margin_is_free(shared: Shared, fake: Any):
  """Margin added above the initial margin is free; testnet's `max_removable_amount`
  after adding 5 USDT was `5.01478` in the same read."""
  row: dict[str, Any] = {
    'instrument': BTC,
    'size': Decimal('0.002'),
    'notional': Decimal('163.216122'),
    'unrealized_pnl': Decimal('-0.171877'),
    'margin_type': 'ISOLATED',
    'isolated_balance': Decimal('21.50827'),
    'isolated_im': Decimal('16.321612'),
    'isolated_mm': Decimal('1.632161'),
  }

  async def account_summary() -> dict[str, Any]:
    """BTC isolated, 5 USDT added."""
    return summary(row)

  fake.trading.account_summary = account_summary
  bucket = await market(shared).perp_collateral()
  assert bucket.free_collateral == Decimal('5.014781')


async def test_isolated_position_without_its_figures_is_missing_data(
  shared: Shared, fake: Any
):
  """An isolated row without `isolated_balance` raises rather than reading zero."""

  async def account_summary() -> dict[str, Any]:
    """BTC isolated, its figures omitted."""
    return summary(position(BTC, '0.002', 'ISOLATED'))

  fake.trading.account_summary = account_summary
  with pytest.raises(MissingData) as raised:
    await market(shared).perp_collateral()
  assert (raised.value.market_id, raised.value.field) == (BTC, 'isolated_balance')
  assert (await market(shared, ETH).perp_collateral()).margin_mode == 'cross'


async def test_account_reads_need_an_api_key(make_fake: Any, make_shared: Any):
  """A public client raises `AuthError` before any request."""
  from tribulnation.sdk import AuthError

  btc = market(make_shared(make_fake(api_key=False)))
  for read in (btc.fees, btc.perp_position, btc.perp_collateral, btc.open_orders):
    with pytest.raises(AuthError):
      await read()
  with pytest.raises(AuthError):
    await btc.query_order('1')


def test_market_ids(shared: Shared):
  """Ids are `<account>:perp:<instrument>`; the account defaults to the venue."""
  btc = market(shared)
  assert (btc.id, btc.venue_id) == (f'grvt:perp:{BTC}', 'grvt')
  testnet = Shared(client=shared.client, venue_id='grvt_testnet', account_id='t')
  assert market(testnet).id == f't:perp:{BTC}'
