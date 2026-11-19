"""Venue rows as SDK values: fills, candles, books, tickers, funding, collateral, limits
and snapshots."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from typing_extensions import Any, cast

import pytest
from typed_evedex import Evedex
from typed_evedex.exchange.account.available_balance import AvailableBalance
from typed_evedex.schemas import Instrument, Position, User
from typed_evedex.streams.order_book import OrderBookUpdate

from tribulnation.evedex.core import Shared
from tribulnation.evedex.market import account
from tribulnation.evedex.market.books import frame_book
from tribulnation.evedex.market.exchanges import EvedexPerpExchange
from tribulnation.evedex.market.markets import (
  EvedexPerpMarket,
  account_fees,
  next_funding,
  next_settlement,
)
from tribulnation.evedex.report import Report
from tribulnation.sdk.market import ExchangeTrade

from .conftest import BUY_ID, SELL_ID, T0, Fake, instrument, order, position

H = datetime(2026, 11, 19, 8, tzinfo=timezone.utc)


def fill(**overrides: Any) -> dict[str, Any]:
  """An account fill: no side, no fee."""
  row: dict[str, Any] = {
    'id': 'b8afcb14',
    'order': SELL_ID,
    'instrument': 'XRPUSD',
    'fillQuantity': Decimal('6'),
    'fillPrice': Decimal('0.9873'),
    'fillRole': 'TAKER',
    'matchId': '1',
    'createdAt': T0,
  }
  return row | overrides


async def test_fills_take_their_side_and_fee_from_the_orders(fake: Fake):
  """Sides come from one `orders.list` per page, fees from `orders.fills` per order;
  the order id is also the client order id; fills outside the window are dropped."""
  fake.orders = [order(), order(id=BUY_ID, side='BUY')]
  fake.fill_pages = [
    [
      fill(),
      fill(id='44992c0a', order=BUY_ID, fillRole='MAKER'),
      fill(id='late', createdAt=T0 + timedelta(days=1)),
    ]
  ]
  fake.order_fills = {
    SELL_ID: [
      {'id': 'b8afcb14', 'fee': [{'coin': 'usdt', 'quantity': Decimal('0.0027')}]}
    ],
    BUY_ID: [{'id': '44992c0a', 'fee': []}],
  }
  m = EvedexPerpMarket(shared=fake.shared(), name='XRPUSD')
  trades = await m.trades_history(T0 - timedelta(hours=1), T0 + timedelta(hours=1))
  sell, buy = trades
  assert sell.qty == Decimal('-6') and not sell.maker
  assert sell.client_order_id == sell.order_id == SELL_ID
  assert sell.fee is not None and sell.fee.amount == Decimal('0.0027')
  assert sell.fee.asset == 'usdt'
  assert buy.qty == Decimal('6') and buy.maker and buy.fee is None
  assert sum(name == 'orders.list' for name, _ in fake.calls) == 1
  [(_, (instrument_, after, _))] = [c for c in fake.calls if c[0] == 'fills']
  assert instrument_ == 'XRPUSD' and after < T0 - timedelta(hours=1)


async def test_exchange_fills_name_their_market(fake: Fake):
  """Exchange-wide fills are `ExchangeTrade`s keyed by instrument."""
  fake.fill_pages = [[fill()]]
  exchange = EvedexPerpExchange(shared=fake.shared())
  [trade] = await exchange.trades_history(None, T0, T0)
  assert isinstance(trade, ExchangeTrade) and trade.market_id == 'XRPUSD'


async def test_candle_rows_are_open_close_high_low(fake: Fake):
  """`[openTime, open, close, high, low, volumeUsd, volume]`, half-open on `end`."""
  fake.candle_pages = [
    [
      (
        H,
        Decimal('1'),
        Decimal('2'),
        Decimal('3'),
        Decimal('0.5'),
        Decimal('60'),
        Decimal('30'),
      ),
      (H + timedelta(hours=1), *[Decimal(1)] * 6),
    ]
  ]
  m = EvedexPerpMarket(shared=fake.shared(), name='XRPUSD')
  [c] = await m.candles('1h', H, H + timedelta(hours=1))
  assert (c.open, c.close, c.high, c.low) == (1, 2, 3, Decimal('0.5'))
  assert c.volume == 30 and c.quote_volume == 60
  assert await m.candles('1h', H, H) == []


def test_stream_books_are_whole_books():
  """Every publication is the book, stamped with its time."""
  level = {'price': Decimal('0.99'), 'quantity': Decimal('5')}
  frame = cast(
    OrderBookUpdate,
    {'instrument': 'XRPUSD', 'orderBook': {'t': T0, 'bids': [level], 'asks': []}},
  )
  book = frame_book(frame)
  assert book.time == T0 and book.bids[0].price == Decimal('0.99') and not book.asks


async def test_tickers_join_the_top_of_book(fake: Fake):
  """Last and volumes from the instrument, bid and ask from `marketLevel=1`; hidden
  instruments are not listed."""
  fake.instruments = [instrument(), instrument(name='LDOUSD', visibility='none')]
  exchange = EvedexPerpExchange(shared=fake.shared(keyed=False))
  assert await exchange.markets() == ['XRPUSD']
  tickers = await exchange.tickers()
  assert list(tickers) == ['XRPUSD']
  t = tickers['XRPUSD']
  assert (t.bid, t.ask, t.last) == (
    Decimal('0.9885'),
    Decimal('0.9887'),
    Decimal('0.9887'),
  )
  assert t.base_volume_24h == Decimal('13992156')
  assert ('order_book', ('XRPUSD', '1')) in fake.calls


def test_funding_is_the_next_hourly_share():
  """The rate computed every 8 hours, an eighth of it at the next whole hour."""
  row = cast(Instrument, instrument())
  funding = next_funding(
    row, now=datetime(2026, 11, 19, 13, 59, 59, tzinfo=timezone.utc)
  )
  assert funding.rate == Decimal('-0.00013691') / 8
  assert funding.time == datetime(2026, 11, 19, 14, tzinfo=timezone.utc)
  assert funding.interval == timedelta(hours=1)
  assert next_settlement(H) == H + timedelta(hours=1)


async def test_index_and_perp_stats(fake: Fake):
  """Index is `avgLastPrice * lotSize`; open interest in base units."""
  fake.instruments = [instrument(lotSize=Decimal(1000), name='1000PEPEUSD')]
  exchange = EvedexPerpExchange(shared=fake.shared(keyed=False))
  stats = (await exchange.perp_stats())['1000PEPEUSD']
  assert stats.index == Decimal('989.11278') and stats.open_interest == Decimal(
    '30331317.1'
  )
  assert stats.funding_interval == timedelta(hours=1)


def test_personal_fees_override_the_account_rates():
  """`personalTradingFees` wins field by field over `tradingFees`."""
  rates = {'maker': Decimal('0.00015'), 'taker': Decimal('0.00045')}
  plain = account_fees(cast(User, {'tradingFees': rates, 'personalTradingFees': None}))
  assert plain.maker_buy == Decimal('0.00015') and plain.taker_sell == Decimal(
    '0.00045'
  )
  personal = account_fees(
    cast(User, {'tradingFees': rates, 'personalTradingFees': {'makerFee': Decimal(0)}})
  )
  assert personal.maker_sell == 0 and personal.taker_buy == Decimal('0.00045')


def test_cross_bucket():
  """Equity is the balance plus unrealized PnL; free collateral the venue's."""
  summary = cast(
    AvailableBalance,
    {
      'funding': {'balance': Decimal('8')},
      'position': [{'volume': Decimal('6'), 'initialMargin': Decimal('3')}],
      'availableBalance': Decimal('4.9'),
    },
  )
  rows = [
    cast(
      Position,
      position(
        quantity=Decimal('6'),
        unRealizedPnL=Decimal('-0.1'),
        maintenanceMargin=Decimal('0.05'),
      ),
    )
  ]
  bucket = account.bucket(summary, rows)
  assert bucket.equity == Decimal('7.9') and bucket.free_collateral == Decimal('4.9')
  assert bucket.initial_margin == 3 and bucket.maintenance_margin == Decimal('0.05')
  assert bucket.leverage == Decimal(6) / Decimal('7.9')
  assert bucket.margin_mode == 'cross'


async def test_positions_are_signed(fake: Fake):
  """`quantity` is unsigned beside `side`; a zero record is flat."""
  m = EvedexPerpMarket(shared=fake.shared(), name='XRPUSD')
  assert (await m.perp_position()).size == 0
  fake.positions = [position(side='SELL', quantity=Decimal('6'))]
  p = await m.perp_position()
  assert p.size == Decimal('-6') and p.entry_price == Decimal('0.9877')
  assert p.liquidation_price is None


def test_position_limit_is_the_leverage_tier():
  """The tier at the account's leverage less the position, at the mark; no tier, no
  limit; account overrides raise."""
  row = cast(Instrument, instrument(markPrice=Decimal(1)))
  user = cast(User, {'riskFactorOverride': {}})
  limit = account.remaining_position_limit(row, user=user, size=Decimal(10), leverage=2)
  assert limit.long == Decimal(7398000 - 10) and limit.short == Decimal(7398000)
  free = account.remaining_position_limit(row, user=user, size=Decimal(0), leverage=7)
  assert free.long is None and free.short is None
  with pytest.raises(NotImplementedError):
    account.remaining_position_limit(
      row,
      user=cast(User, {'riskFactorOverride': {'leverageLimit': {}}}),
      size=Decimal(0),
      leverage=1,
    )


async def test_snapshot_holds_trading_and_wallet():
  """The trading balance and positions, and the wallet; zero balances left out."""

  async def funding() -> Any:
    return [{'coin': 'usdt', 'quantity': Decimal('7.99')}]

  async def balance() -> Any:
    return [
      {'currency': 'usdt', 'balance': Decimal('1.87')},
      {'currency': 'eth', 'balance': 0},
    ]

  async def positions() -> Any:
    return {
      'list': [
        position(side='SELL', quantity=Decimal('6')),
        position(instrument='BTCUSD'),
      ]
    }

  client = SimpleNamespace(
    credentials=SimpleNamespace(account=None),
    exchange=SimpleNamespace(
      account=SimpleNamespace(funding=funding, balance=balance),
      positions=SimpleNamespace(list=positions),
    ),
  )
  report = Report(shared=Shared(client=cast(Evedex, client)))
  trading, wallet = (await report.snapshot()).snapshot.subaccounts
  assert trading.subaccount == 'trading' and trading.balances == {
    'usdt': Decimal('7.99')
  }
  assert list(trading.positions) == ['XRPUSD']
  assert trading.positions['XRPUSD'].size == Decimal('-6')
  assert wallet.subaccount == 'wallet' and wallet.balances == {'usdt': Decimal('1.87')}


def test_report_needs_a_key():
  """A report without either key is refused before building a client."""
  with pytest.raises(ValueError):
    Report.new()
