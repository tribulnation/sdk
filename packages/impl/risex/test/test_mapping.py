"""Venue rows as SDK values: fills, funding signs, books, positions, collateral,
candle chunks and snapshots."""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from typing_extensions import Any, cast

import pytest
from pydantic import TypeAdapter
from typed_risex import RISEx
from typed_risex.account.funding_payments import FundingPayment as FundingRow
from typed_risex.account.trade_history import AccountTrade
from typed_risex.portfolio.details import PortfolioDetails
from typed_risex.streams.orderbook import OrderbookSnapshot, OrderbookUpdate

from tribulnation.risex.core import Shared
from tribulnation.risex.market import account, history
from tribulnation.risex.market.books import frame_book
from tribulnation.risex.market.common import funding_received, parse_trade
from tribulnation.risex.market.markets import RisexPerpMarket
from tribulnation.risex.report import Report
from tribulnation.sdk.market import POSITION_LIMIT_TTL, RemainingPositionLimit

T0 = datetime(2026, 11, 17, 10, tzinfo=timezone.utc)


def fill(**overrides: Any) -> AccountTrade:
  """A taker sell fill of an order placed without a client id."""
  row: dict[str, Any] = {
    'id': 'a-b',
    'market_id': 1,
    'order_id': '0xb',
    'side': 'SELL',
    'price': Decimal('64345.9'),
    'size': Decimal('0.0001'),
    'fee': Decimal('0.001286918'),
    'liquidity_indicator': 'TAKER',
    'time': T0,
    'client_order_id': '',
  }
  return cast(AccountTrade, row | overrides)


def test_trades_are_signed_and_keep_client_ids():
  """Sells are negative, the fee is USDC, and `''` client ids are `None`."""
  sell = parse_trade(fill())
  assert sell.qty == Decimal('-0.0001') and not sell.maker
  assert sell.fee is not None and sell.fee.asset == 'USDC'
  assert sell.client_order_id is None
  buy = parse_trade(
    fill(side='BUY', liquidity_indicator='MAKER', client_order_id='777')
  )
  assert buy.qty == Decimal('0.0001') and buy.maker and buy.client_order_id == '777'


def test_funding_is_received_positive():
  """The venue's `funding_payment` is positive when paid: a long paying at a positive
  rate is negative to the SDK, a long receiving at a negative rate positive."""
  paid = cast(FundingRow, {'funding_payment': Decimal('19.468611333931637682')})
  received = cast(FundingRow, {'funding_payment': Decimal('-0.004879833131885902')})
  assert funding_received(paid) == Decimal('-19.468611333931637682')
  assert funding_received(received) == Decimal('0.004879833131885902')


def test_book_updates_are_absolute_sizes():
  """A snapshot is the book; an update's levels replace their size, `0` deletes."""

  def level(p: str, q: str) -> dict[str, Any]:
    """One aggregated level."""
    return {'price': Decimal(p), 'quantity': Decimal(q), 'order_count': 1}

  snapshot = cast(
    OrderbookSnapshot,
    {
      'type': 'snapshot',
      'worker_timestamp': T0,
      'data': {
        'bids': [level('100', '1')],
        'asks': [level('101', '2'), level('102', '3')],
      },
    },
  )
  update = cast(
    OrderbookUpdate,
    {
      'type': 'update',
      'worker_timestamp': T0 + timedelta(seconds=1),
      'data': {'bids': [level('100', '5')], 'asks': [level('101', '0')]},
    },
  )
  book = frame_book(snapshot)
  book.update(frame_book(update))
  assert [(e.price, e.qty) for e in book.bids] == [(Decimal(100), Decimal(5))]
  assert [(e.price, e.qty) for e in book.asks] == [(Decimal(102), Decimal(3))]


def details(*, isolated: bool = False) -> PortfolioDetails:
  """A portfolio with one cross (or isolated) BTC long."""
  summary = {
    'cross_margin_balance': Decimal('1009.98'),
    'free_collateral': Decimal('1008.70'),
    'total_initial_margin': Decimal('1.27'),
    'total_maintenance_margin': Decimal('0.085'),
    'account_leverage': Decimal('0.0063'),
    'usdc_balance': Decimal('1009.97'),
  }
  position: dict[str, Any] = {
    'market_id': 1,
    'size': Decimal('0.0001'),
    'margin_mode': 1 if isolated else 0,
  }
  return cast(PortfolioDetails, {'summary': summary, 'positions': [position]})


def test_cross_bucket():
  """The summary is the cross bucket; an isolated position raises."""
  bucket = account.bucket(details())
  assert bucket.equity == Decimal('1009.98') and bucket.free_collateral == Decimal(
    '1008.70'
  )
  assert bucket.margin_mode == 'cross'
  with pytest.raises(NotImplementedError):
    account.bucket(details(isolated=True))


def positions(**overrides: Any) -> list[dict[str, Any]]:
  """`account.positions` rows: a 1e18-scaled BTC short."""
  row: dict[str, Any] = {
    'market_id': 1,
    'size': -100000000000000,
    'avg_entry_price': 63767800000000000000000,
    'margin_mode': 0,
  }
  return [row | overrides]


class Pages:
  """One page of rows, as a `_paged` walk."""

  def __init__(self, rows: list[Any]):
    self.rows = rows

  def via(self, call: Any) -> Any:
    """Iterate without middleware."""
    rows = self.rows

    async def pages():
      yield rows

    return pages()


def walk(rows: list[Any]) -> Any:
  """A `_paged` method answering `rows` whatever its arguments."""

  def paged(*args: Any, **kwargs: Any) -> Pages:
    return Pages(rows)

  return paged


def fake_shared(**namespaces: Any) -> Shared:
  """A `Shared` over a fake client of the given namespaces."""
  client = SimpleNamespace(credentials=None, **namespaces)
  return Shared(client=cast(RISEx, client), address='0xabc')


async def test_positions_are_unscaled_and_signed():
  """`account.positions`' integers are divided by 1e18; a short is negative; another
  market is flat."""
  shared = fake_shared(account=SimpleNamespace(positions_paged=walk(positions())))
  short = await account.perp_position(shared, 1, ttl=None)
  assert short.size == Decimal('-0.0001') and short.entry_price == Decimal('63767.8')
  flat = await account.perp_position(shared, 2, ttl=None)
  assert flat.size == 0


async def test_snapshot():
  """The settled USDC balance and positions by market id, labelled by address."""

  async def portfolio_details(address: str) -> Any:
    return details()

  shared = fake_shared(
    account=SimpleNamespace(positions_paged=walk(positions())),
    portfolio=SimpleNamespace(details=portfolio_details),
  )
  record = await Report(shared=shared).snapshot()
  [sub] = record.snapshot.subaccounts
  assert sub.subaccount == '0xabc'
  assert sub.balances == {'USDC': Decimal('1009.97')}
  assert sub.positions['1'].size == Decimal('-0.0001')
  isolated = fake_shared(
    account=SimpleNamespace(positions_paged=walk(positions(margin_mode=1))),
    portfolio=SimpleNamespace(details=portfolio_details),
  )
  with pytest.raises(NotImplementedError):
    await Report(shared=isolated).snapshot()


async def test_candles_are_chunked_under_the_range_cap():
  """A window wider than `CANDLES_CHUNK` intervals is split; rows outside each chunk's
  half-open range are dropped."""
  calls: list[tuple[datetime, datetime, int]] = []

  async def candles(
    *, market_id: int, interval: int, from_: datetime, to: datetime
  ) -> Any:
    calls.append((from_, to, interval))
    row: dict[str, Any] = {
      'time': from_,
      'open': 1,
      'high': 1,
      'low': 1,
      'close': 1,
      'volume': 1,
    }
    late: dict[str, Any] = row | {'time': to}
    return {'data': [row, late]}

  shared = fake_shared(markets=SimpleNamespace(candles=candles))
  start = T0
  end = start + timedelta(minutes=history.CANDLES_CHUNK + 5)
  pages = [p async for p in history.candles(shared, 1, '1m', start, end)]
  assert [len(p) for p in pages] == [1, 1]
  assert calls[0] == (
    start,
    start + timedelta(minutes=history.CANDLES_CHUNK),
    60 * 10**9,
  )
  assert calls[1][1] == end


async def test_funding_payments_filter_and_sign():
  """Rows outside the inclusive window are dropped; exchange-wide rows carry the
  market id."""
  rows: list[dict[str, Any]] = [
    {'market_id': 1, 'funding_payment': Decimal('2'), 'block_time': T0},
    {
      'market_id': 2,
      'funding_payment': Decimal('-1'),
      'block_time': T0 - timedelta(days=9),
    },
  ]
  shared = fake_shared(account=SimpleNamespace(funding_payments_paged=walk(rows)))
  pages = [
    p async for p in history.funding_payments(shared, None, T0 - timedelta(days=1), T0)
  ]
  [[payment]] = pages
  assert payment.amount == Decimal('-2')
  assert getattr(payment, 'market_id') == '1'
  with pytest.raises(ValueError):
    [p async for p in history.funding_payments(shared, 1, datetime(2026, 1, 1), T0)]


async def test_unsettled_funding_rows_validate_and_count():
  """An unsettled accrual sends `''` rates (typed-risex 0.1.1 accepts them): it still
  validates and is funding all the same, its amount the negated `funding_payment`."""
  wire: dict[str, object] = {
    'market_id': 1,
    'funding_payment': '19.468611333931637682',
    'position_size': '0.5',
    'block_number': 0,
    'block_time': str(int(T0.timestamp() * 10**9)),
    'tx_hash': '',
    'side': 'long',
    'funding_rate': '0.0000336',
    'is_settled': False,
    'funding_rate_8h': '',
    'trade_side': '',
    'entry_type': 'funding',
  }
  row = TypeAdapter(FundingRow).validate_python(wire)
  assert row['funding_rate_8h'] == ''
  shared = fake_shared(account=SimpleNamespace(funding_payments_paged=walk([row])))
  [[payment]] = [
    p async for p in history.funding_payments(shared, 1, T0 - timedelta(hours=1), T0)
  ]
  assert payment.amount == Decimal('-19.468611333931637682')


def market_row(*, max_size: str = '100000000', open_interest: str = '247.6') -> Any:
  """Mainnet BTC's row (2026-11-17), at a round mark of 60000."""
  return {
    'market_id': 1,
    'mark_price': Decimal('60000'),
    'max_position_size': Decimal(max_size),
    'open_interest': Decimal(open_interest),
    'config': {'open_interest_limit': Decimal('750')},
  }


@pytest.mark.parametrize(
  'max_size,open_interest,size,expected',
  [
    # The open-interest room, 502.4 BTC, binds both ways.
    ('100000000', '247.6', '0', (Decimal('30144000'), Decimal('30144000'))),
    # A 2 BTC cap less the 0.5 held long; the short side keeps the whole cap.
    ('2', '247.6', '0.5', (Decimal('90000'), Decimal('120000'))),
    ('2', '247.6', '-0.5', (Decimal('120000'), Decimal('90000'))),
    # At the open-interest limit nothing grows.
    ('100000000', '750', '0.5', (Decimal(0), Decimal(0))),
  ],
)
def test_remaining_position_limit(
  max_size: str, open_interest: str, size: str, expected: tuple[Decimal, Decimal]
):
  """Base-unit caps as notional at the mark: the account's cap less what each
  direction holds, bounded by the market's open-interest room."""
  limit = account.remaining_position_limit(
    market_row(max_size=max_size, open_interest=open_interest), size=Decimal(size)
  )
  assert (limit.long, limit.short) == expected


async def test_markets_share_the_live_rows_and_positions(
  monkeypatch: pytest.MonkeyPatch,
):
  """Every market's limit comes from one all-market live read and one positions read,
  shared for the default `ttl`; past it, both are read again."""
  now = [1000.0]
  monkeypatch.setattr(asyncio.get_running_loop(), 'time', lambda: now[0])
  live: list[Any] = []
  paged: list[Any] = []

  async def markets_all(force_refresh: bool | None = None, **kwargs: Any) -> Any:
    """BTC's live row with a 1 BTC cap, and 21 more markets; never filtered."""
    live.append((force_refresh, kwargs))
    rows: list[Any] = [
      {**market_row(max_size='1'), 'market_id': i} for i in range(1, 23)
    ]
    return {'markets': rows}

  def positions_paged(*args: Any, **kwargs: Any) -> Pages:
    paged.append(args)
    return Pages(positions())

  shared = fake_shared(
    account=SimpleNamespace(positions_paged=positions_paged),
    markets=SimpleNamespace(all=markets_all),
  )
  perps = [RisexPerpMarket(shared=shared, index_id=i) for i in range(1, 23)]
  limits = await asyncio.gather(*(m.remaining_position_limit() for m in perps))
  assert limits[0] == RemainingPositionLimit(
    long=Decimal(60000), short=Decimal('59994')
  )
  assert limits[1] == RemainingPositionLimit(long=Decimal(60000), short=Decimal(60000))
  assert live == [(True, {})] and len(paged) == 1
  now[0] += POSITION_LIMIT_TTL.total_seconds()
  await asyncio.gather(*(m.remaining_position_limit() for m in perps))
  assert len(live) == 2 and len(paged) == 2
