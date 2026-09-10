"""Unit tests for the Kraken market parsers, over rows recorded from the live venue."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from tribulnation.sdk.market import Book
from tribulnation.kraken.market.impl.depth import book_depth, fold_books, parse_book
from tribulnation.kraken.market.impl.mixin import join_pairs
from tribulnation.kraken.market.impl.orders import parse_order
from tribulnation.kraken.market.impl.rules import parse_rules
from tribulnation.kraken.market.impl.trades import parse_fill, parse_trade
from tribulnation.kraken.market.spot_exchange import parse_ticker

from typed_kraken.spot.account.open_orders import OpenOrder
from typed_kraken.spot.account.trades_history import HistoricalTrade
from typed_kraken.spot.market_data.asset_pairs import AssetPair
from typed_kraken.spot.market_data.ticker import AssetTicker
from typed_kraken.streams.market_data.book import BookMessage
from typed_kraken.streams.private.executions import ExecutionTradeEvent

TIME = datetime(2026, 8, 27, 14, 6, 15, 177869, tzinfo=timezone.utc)

XBTUSD: AssetPair = {
  'altname': 'XBTUSD',
  'wsname': 'XBT/USD',
  'base': 'XXBT',
  'quote': 'ZUSD',
  'pair_decimals': 1,
  'lot_decimals': 8,
  'fees': [(0.0, 0.4), (10000.0, 0.35)],
  'fees_maker': [(0.0, 0.25), (10000.0, 0.2)],
  'ordermin': Decimal('0.00005'),
  'costmin': Decimal('0.5'),
  'tick_size': Decimal('0.1'),
  'status': 'online',
}
"""`AssetPairs` row for `XXBTZUSD`, as recorded by the PoC on 2026-09-07."""


def test_rules_read_the_base_fee_tier_as_a_fraction():
  """Kraken quotes each tier in percent; the SDK wants a fraction of 1."""
  rules = parse_rules(XBTUSD)
  assert rules.fee_asset == 'ZUSD'
  assert rules.fees is not None
  assert rules.fees.maker_buy == rules.fees.maker_sell == Decimal('0.0025')
  assert rules.fees.taker_buy == rules.fees.taker_sell == Decimal('0.004')
  assert rules.tick_size == Decimal('0.1')
  assert rules.step_size == Decimal('1E-8')
  assert rules.fixed_min_qty == Decimal('0.00005')
  assert rules.min_value == Decimal('0.5')
  assert rules.api is True


def test_rules_flat_schedule_and_unknown_fees():
  """Flat schedules use `fees`; an absent schedule is unknown, never free."""
  flat = parse_rules({**XBTUSD, 'fees_maker': []})
  assert flat.fees is not None
  assert flat.fees.maker_buy == flat.fees.taker_sell == Decimal('0.004')
  empty = parse_rules({**XBTUSD, 'fees': [], 'fees_maker': []})
  assert empty.fees is None


def test_rules_tick_size_falls_back_to_pair_decimals():
  """Older rows carry no `tick_size`; the price precision then sets it."""
  info = {k: v for k, v in XBTUSD.items() if k != 'tick_size'}
  assert parse_rules(info).tick_size == Decimal('0.1')  # type: ignore[arg-type]


def test_pairs_join_on_altname_to_the_ws_symbol():
  """The `assetVersion=1` key is the WebSocket v2 symbol; the default key is what
  `Ticker` and `Depth` answer under. Both carry the same altname."""
  display: AssetPair = {'altname': 'XBTUSD', 'base': 'BTC', 'quote': 'USD'}
  pairs = join_pairs({'XXBTZUSD': XBTUSD}, {'BTC/USD': display})
  assert pairs['XBTUSD'] == {'key': 'XXBTZUSD', 'symbol': 'BTC/USD', 'info': XBTUSD}


def test_ticker_reads_kraken_wire_shortcuts():
  """`a`/`b` are `[price, whole lot volume, lot volume]`, `c` is the last trade and `v`
  is `[today, last 24 hours]`."""
  row: AssetTicker = {
    'a': ('78375.00000', '2', '2.000'),
    'b': ('78374.90000', '2', '2.000'),
    'c': ('78374.90000', '0.01767249'),
    'v': ('768.77773678', '1506.74207485'),
  }
  ticker = parse_ticker(row)
  assert ticker.last == Decimal('78374.90000')
  assert ticker.bid == Decimal('78374.90000') and ticker.bid_qty == Decimal('2.000')
  assert ticker.ask == Decimal('78375.00000') and ticker.ask_qty == Decimal('2.000')
  assert ticker.base_volume_24h == Decimal('1506.74207485')


def test_depth_drops_the_level_timestamp():
  """REST levels are `[price, volume, timestamp]` triples."""
  book = parse_book(
    {
      'asks': [(Decimal('78375.0'), Decimal('0.992'), 1788870725)],
      'bids': [(Decimal('78374.9'), Decimal('2.0'), 1788870719)],
    }
  )
  assert book.asks == [Book.Entry(price=Decimal('78375.0'), qty=Decimal('0.992'))]
  assert book.bids == [Book.Entry(price=Decimal('78374.9'), qty=Decimal('2.0'))]


@pytest.mark.parametrize(
  ('levels', 'depth'),
  [(None, 10), (1, 10), (10, 10), (11, 25), (100, 100), (101, 500), (5000, 1000)],
)
def test_book_depth_is_the_smallest_fixed_depth_holding_levels(
  levels: int | None, depth: int
):
  """The channel serves five depths; the SDK asks for any number of levels."""
  assert book_depth(levels) == depth


async def test_book_stream_folds_snapshot_then_updates():
  """The channel sends one snapshot and then only changed levels, zero meaning removed
  -- and a yielded book must not be mutated by a later push."""

  async def pushes():
    snapshot: BookMessage = {
      'channel': 'book',
      'type': 'snapshot',
      'data': [
        {
          'symbol': 'BTC/USD',
          'bids': [
            {'price': 79700.2, 'qty': 0.00992935},
            {'price': 79698.4, 'qty': 0.000347},
          ],
          'asks': [{'price': 79700.3, 'qty': 1.04058879}],
          'checksum': 0,
          'timestamp': TIME,
        }
      ],
    }
    update: BookMessage = {
      'channel': 'book',
      'type': 'update',
      'data': [
        {
          'symbol': 'BTC/USD',
          'bids': [{'price': 79698.4, 'qty': 0.0}],
          'asks': [{'price': 79701.2, 'qty': 0.12639852}],
          'checksum': 0,
          'timestamp': TIME,
        }
      ],
    }
    yield snapshot
    yield update

  books = [book async for book in fold_books(pushes())]
  assert [e.price for e in books[0].bids] == [Decimal('79700.2'), Decimal('79698.4')]
  assert [e.price for e in books[1].bids] == [Decimal('79700.2')]
  assert [e.price for e in books[1].asks] == [Decimal('79700.3'), Decimal('79701.2')]
  assert len(books[0].bids) == 2, 'the first yielded book was mutated by the update'


def test_historical_trade_is_signed_and_fee_is_in_quote():
  """`TradesHistory` reports `vol` unsigned with a `type`, and `fee` in the quote
  asset without naming it. Recorded from the account's one XBTUSDC fill."""
  row: HistoricalTrade = {
    'ordertxid': 'ODLOMH-T4FBZ-A7DZ4O',
    'pair': 'XBTUSDC',
    'time': TIME,
    'type': 'buy',
    'ordertype': 'market',
    'price': Decimal('79746.95000'),
    'cost': Decimal('4.78482'),
    'fee': Decimal('0.03828'),
    'vol': Decimal('0.00006000'),
    'trade_id': 7311667,
    'maker': False,
  }
  trade = parse_trade('TKH2SE-M7IF5-CFI7LT', row, quote='USDC')
  assert trade.id == '7311667'
  assert trade.qty == Decimal('0.00006000') and trade.time == TIME
  assert trade.fee is not None and trade.fee.asset == 'USDC'
  assert trade.fee.amount == Decimal('0.03828')
  sell = parse_trade('T', {**row, 'type': 'sell', 'fee': Decimal(0)}, quote='USDC')
  assert sell.qty == Decimal('-0.00006000') and sell.fee is None


def test_streamed_fill_transcribes_floats_through_their_repr():
  """The `executions` channel sends numbers, kept as `float` by the client."""
  event: ExecutionTradeEvent = {  # type: ignore[typeddict-item]
    'exec_type': 'trade',
    'exec_id': 'E1',
    'order_id': 'O1',
    'timestamp': TIME,
    'symbol': 'BTC/USD',
    'side': 'sell',
    'trade_id': 7311667,
    'last_price': 79746.95,
    'last_qty': 0.00006,
    'cost': 4.78482,
    'cum_qty': 0.00006,
    'liquidity_ind': 'm',
    'fees': [{'asset': 'USD', 'qty': 0.03828}],
  }
  trade = parse_fill(event)
  assert trade.price == Decimal('79746.95') and trade.qty == Decimal('-0.00006')
  assert trade.maker is True
  assert trade.fee == trade.Fee(amount=Decimal('0.03828'), asset='USD')


def test_open_order_is_signed_and_pending_counts_as_active():
  """A `pending` order awaits book entry: not resting, not finished either."""
  order: OpenOrder = {
    'status': 'pending',
    'descr': {'pair': 'XBTUSD', 'type': 'sell', 'price': Decimal('90000.0')},
    'vol': Decimal('0.001'),
    'vol_exec': Decimal('0.0002'),
  }
  state = parse_order('OABC', order)
  assert state.id == 'OABC' and state.active is True
  assert state.qty == Decimal('-0.001') and state.filled_qty == Decimal('-0.0002')
  assert state.price == Decimal('90000.0')
  assert parse_order('O', {**order, 'status': 'closed'}).active is False
