"""Mapping Bitget payloads onto SDK market types, on rows recorded live (2026-09-08)."""

from typing_extensions import Any, cast
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from tribulnation.bitget.market.impl import (
  parse_book,
  parse_perp_rules,
  parse_perp_stats,
  parse_spot_rules,
  parse_spot_ticker,
  perp_depth_limit,
)
from tribulnation.bitget.market.impl.candles import parse_perp_candle, parse_spot_candle
from tribulnation.bitget.market.impl.parse import (
  parse_classic_stream_fill,
  parse_mix_fill,
  parse_mix_order,
  parse_spot_fill,
  parse_spot_order,
  parse_uta_fill,
  parse_uta_order,
  parse_uta_stream_fill,
)
from typed_bitget.classic.mix.market.contracts import MixContract
from typed_bitget.classic.mix.order.fills import MixOrderFill
from typed_bitget.classic.mix.order.open import MixOpenOrder
from typed_bitget.classic.spot.order.fills import SpotOwnFill
from typed_bitget.classic.spot.order.open import SpotOpenOrder
from typed_bitget.classic.spot.symbols import SpotSymbol
from typed_bitget.classic.spot.tickers import SpotTicker
from typed_bitget.classic_streams.fill import MixFill1, SpotFill
from typed_bitget.schemas import MixTicker
from typed_bitget.uta.market.funding_rate.current import CurrentFundingRate
from typed_bitget.uta.trade.order.fills import Fill
from typed_bitget.uta.trade.order.unfilled import UnfilledOrder
from typed_bitget.uta_streams.fill import FillUpdate

T = datetime(2026, 8, 13, 10, 19, 36, 100000, tzinfo=timezone.utc)

SPOT_SYMBOL: dict[str, Any] = {
  'symbol': 'BTCUSDT',
  'baseCoin': 'BTC',
  'quoteCoin': 'USDT',
  'minTradeAmount': Decimal('0'),
  'maxTradeAmount': Decimal('900000000000000000000'),
  'takerFeeRate': Decimal('0.002'),
  'makerFeeRate': Decimal('0.002'),
  'pricePrecision': 2,
  'quantityPrecision': 6,
  'minTradeUSDT': Decimal('1'),
  'status': 'online',
  'buyLimitPriceRatio': Decimal('0.02'),
  'sellLimitPriceRatio': Decimal('0.02'),
}
"""The BTCUSDT spot row, narrowed to the fields the mapping reads."""

CONTRACT: dict[str, Any] = {
  'symbol': 'BTCUSDT',
  'baseCoin': 'BTC',
  'quoteCoin': 'USDT',
  'buyLimitPriceRatio': Decimal('0.05'),
  'sellLimitPriceRatio': Decimal('0.05'),
  'makerFeeRate': Decimal('0.0002'),
  'takerFeeRate': Decimal('0.0006'),
  'minTradeNum': Decimal('0.0001'),
  'maxOrderQty': 1200,
  'priceEndStep': 1,
  'pricePlace': 1,
  'sizeMultiplier': Decimal('0.0001'),
  'symbolType': 'perpetual',
  'minTradeUSDT': Decimal('5'),
  'symbolStatus': 'normal',
  'maxLever': Decimal('150'),
}
"""The BTCUSDT contract row, narrowed to the fields the mapping reads."""


def test_a_spot_book_keeps_the_venue_digits():
  """Spot levels arrive as decimal strings and must survive untouched."""
  book = parse_book(
    [(Decimal('78405'), Decimal('0.0199830000000000'))],
    [(Decimal('78406'), Decimal('1'))],
  )
  assert book.bids[0].qty == Decimal('0.0199830000000000')
  assert str(book.bids[0].qty) == '0.0199830000000000'


def test_a_futures_book_converts_floats_through_their_repr():
  """Futures levels arrive as JSON numbers; `Decimal(float)` would expand the binary
  fraction (`78381.6` -> `78381.600000000005820766...`), so the repr is what's kept."""
  book = parse_book([(78381.5, 0.0205)], [(78381.6, 0.0205)])
  assert book.best_ask.price == Decimal('78381.6')
  assert str(book.best_ask.price) == '78381.6'
  assert book.best_bid.qty == Decimal('0.0205')


def test_a_book_is_sorted_best_first_whatever_the_wire_order():
  """`Book` sorts on construction, so an unordered push cannot invert the spread."""
  book = parse_book([(1, 1), (3, 1), (2, 1)], [(6, 1), (4, 1), (5, 1)])
  assert [e.price for e in book.bids] == [3, 2, 1]
  assert [e.price for e in book.asks] == [4, 5, 6]


def test_the_futures_depth_enum_rounds_up_and_caps_at_max():
  """The futures book takes a fixed enum: serve the next member up, `max` past 50."""
  assert perp_depth_limit(None) == 'max'
  assert perp_depth_limit(1) == '1'
  assert perp_depth_limit(2) == '5'
  assert perp_depth_limit(5) == '5'
  assert perp_depth_limit(7) == '15'
  assert perp_depth_limit(50) == '50'
  assert perp_depth_limit(51) == 'max'
  assert perp_depth_limit(500) == 'max'


def test_a_one_sided_spot_ticker_reports_no_size():
  """2 of 1305 symbols send `null` sizes; they must not read as zero."""
  ticker = parse_spot_ticker(
    cast(
      SpotTicker,
      {
        'symbol': 'RWMBUSDT',
        'lastPr': Decimal('1'),
        'bidPr': Decimal('0.9'),
        'askPr': Decimal('1.1'),
        'bidSz': None,
        'askSz': Decimal('5'),
        'baseVolume': Decimal('100'),
      },
    )
  )
  assert ticker.bid_qty is None and ticker.ask_qty == Decimal(5)
  assert ticker.last == Decimal(1) and ticker.base_volume_24h == Decimal(100)


def mix_ticker() -> MixTicker:
  """The BTCUSDT futures ticker, narrowed to the fields the mapping reads."""
  return cast(
    MixTicker,
    {
      'symbol': 'BTCUSDT',
      'lastPr': Decimal('78418.8'),
      'askPr': Decimal('78418.9'),
      'bidPr': Decimal('78418.8'),
      'bidSz': Decimal('1'),
      'askSz': Decimal('2'),
      'baseVolume': Decimal('50000'),
      'indexPrice': Decimal('78447.1135'),
      'fundingRate': Decimal('0.0001'),
      'holdingAmount': Decimal('35009.8822999998803'),
      'markPrice': Decimal('78418.8'),
    },
  )


def test_perp_stats_join_the_ticker_with_its_funding_schedule():
  """Index, mark, rate and open interest come off the ticker; the schedule off the
  funding listing, which is absent for a contract that listing omits."""
  funding = cast(
    CurrentFundingRate,
    {
      'symbol': 'BTCUSDT',
      'fundingRate': Decimal('0.0001'),
      'fundingRateInterval': 8,
      'nextUpdate': T,
      'minFundingRate': None,
      'maxFundingRate': None,
    },
  )
  stats = parse_perp_stats(mix_ticker(), funding)
  assert stats.index == Decimal('78447.1135') and stats.mark == Decimal('78418.8')
  assert stats.funding == Decimal('0.0001')
  assert stats.open_interest == Decimal('35009.8822999998803')
  assert stats.next_funding_time == T
  assert stats.funding_interval == timedelta(hours=8)
  bare = parse_perp_stats(mix_ticker(), None)
  assert bare.next_funding_time is None and bare.funding_interval is None


def test_spot_rules_derive_sizes_from_decimal_place_counts():
  """Bitget publishes precisions, not tick sizes; a zero `minTradeAmount` is no
  minimum rather than a minimum of zero."""
  rules = parse_spot_rules(cast(SpotSymbol, SPOT_SYMBOL))
  assert rules.tick_size == Decimal('0.01')
  assert rules.step_size == Decimal('0.000001')
  assert rules.fixed_min_qty is None
  assert rules.min_value == Decimal(1)
  assert (rules.rel_min_price, rules.rel_max_price) == (
    Decimal('0.98'),
    Decimal('1.02'),
  )
  assert rules.fees is not None
  assert (rules.fees.maker_buy, rules.fees.taker_sell) == (
    Decimal('0.002'),
    Decimal('0.002'),
  )
  assert rules.api and rules.fee_asset == 'USDT'
  halted = parse_spot_rules(cast(SpotSymbol, {**SPOT_SYMBOL, 'status': 'halt'}))
  assert not halted.api


def test_perp_rules_scale_the_tick_by_the_price_end_step():
  """The tick is `priceEndStep` units of the last decimal place. Every live contract
  has a step of 1 today, so the multiplier is only visible on a synthetic row."""
  rules = parse_perp_rules(
    cast(MixContract, {**CONTRACT, 'feeRateUpRatio': Decimal(0)})
  )
  assert rules.tick_size == Decimal('0.1')
  assert rules.step_size == Decimal('0.0001')
  assert rules.fixed_min_qty == Decimal('0.0001')
  assert rules.max_qty == Decimal(1200)
  assert rules.min_value == Decimal(5)
  assert rules.fees is not None
  assert (rules.fees.maker_buy, rules.fees.taker_sell) == (
    Decimal('0.0002'),
    Decimal('0.0006'),
  )
  coarse = parse_perp_rules(
    cast(MixContract, {**CONTRACT, 'priceEndStep': 5, 'feeRateUpRatio': Decimal('0.1')})
  )
  assert coarse.tick_size == Decimal('0.5')
  assert coarse.fees is None


def test_open_orders_are_signed_by_side_in_every_shape():
  """A sell reads negative, on the order and on its filled part, on all three
  endpoints; the two open-only listings are always `active`."""
  spot = parse_spot_order(
    cast(
      SpotOpenOrder,
      {
        'orderId': '1',
        'side': 'sell',
        'basePrice': '80000',
        'size': '0.5',
        'baseVolume': '0.1',
      },
    )
  )
  assert (spot.price, spot.qty, spot.filled_qty, spot.active) == (
    Decimal(80000),
    Decimal('-0.5'),
    Decimal('-0.1'),
    True,
  )
  mix = parse_mix_order(
    cast(
      MixOpenOrder,
      {
        'orderId': '2',
        'side': 'buy',
        'price': '70000',
        'size': '0.01',
        'baseVolume': '0',
        'status': 'partially_filled',
      },
    )
  )
  assert (mix.qty, mix.filled_qty, mix.active) == (Decimal('0.01'), Decimal(0), True)
  uta = parse_uta_order(
    cast(
      UnfilledOrder,
      {
        'orderId': '3',
        'side': 'sell',
        'price': '1.5',
        'qty': '10',
        'cumExecQty': '4',
      },
    )
  )
  assert (uta.id, uta.qty, uta.filled_qty, uta.active) == ('3', -10, -4, True)


def mix_fill(**overrides: Any) -> MixOrderFill:
  """One live futures fill: a taker sell charged `-0.00381818` USDT."""
  return cast(
    MixOrderFill,
    {
      'tradeId': '1',
      'price': Decimal('63636.4'),
      'baseVolume': Decimal('0.0001'),
      'side': 'sell',
      'tradeScope': 'taker',
      'feeDetail': [
        {
          'deduction': 'no',
          'feeCoin': 'USDT',
          'totalDeductionFee': None,
          'totalFee': Decimal('-0.00381818'),
        }
      ],
      'cTime': T,
      **overrides,
    },
  )


def test_a_classic_fee_charged_is_reported_positive():
  """Classic signs a fee charged negative; the SDK signs it positive. Dropping the
  sign instead of flipping it would report a rebate as a fee."""
  trade = parse_mix_fill(mix_fill())
  assert trade.fee is not None
  assert trade.fee.amount == Decimal('0.00381818') and trade.fee.asset == 'USDT'
  assert (trade.qty, trade.price, trade.maker) == (
    Decimal('-0.0001'),
    Decimal('63636.4'),
    False,
  )
  rebate = parse_mix_fill(
    mix_fill(
      feeDetail=[
        {
          'deduction': 'no',
          'feeCoin': 'USDT',
          'totalDeductionFee': None,
          'totalFee': Decimal('0.001'),
        }
      ]
    )
  )
  assert rebate.fee is not None and rebate.fee.amount == Decimal('-0.001')


def test_a_zero_fee_is_a_fee_and_no_line_items_is_no_fee():
  """A zero total is a real fee of zero; only an empty `feeDetail` means unknown."""
  zero = parse_mix_fill(
    mix_fill(
      feeDetail=[
        {
          'deduction': 'no',
          'feeCoin': 'USDT',
          'totalDeductionFee': None,
          'totalFee': Decimal(0),
        }
      ]
    )
  )
  assert zero.fee is not None and zero.fee.amount == 0
  assert parse_mix_fill(mix_fill(feeDetail=[])).fee is None


def test_a_classic_spot_fill_reads_its_single_fee_detail():
  """The spot history nests one fee object rather than a list."""
  trade = parse_spot_fill(
    cast(
      SpotOwnFill,
      {
        'tradeId': '9',
        'side': 'buy',
        'priceAvg': '1.42',
        'size': '1.1002',
        'tradeScope': 'maker',
        'feeDetail': {
          'deduction': 'no',
          'feeCoin': 'XRP',
          'totalDeductionFee': '0',
          'totalFee': '-0.0011002',
        },
        'cTime': T,
      },
    )
  )
  assert trade.qty == Decimal('1.1002') and trade.maker
  assert trade.fee is not None
  assert (trade.fee.amount, trade.fee.asset) == (Decimal('0.0011002'), 'XRP')


def test_classic_stream_fills_map_spot_and_futures_shapes_alike():
  """The `fill` channel names price and size differently per product line."""
  spot = parse_classic_stream_fill(
    cast(
      SpotFill,
      {
        'tradeId': '1',
        'symbol': 'BTCUSDT',
        'side': 'buy',
        'priceAvg': '78400',
        'size': '0.001',
        'tradeScope': 'maker',
        'feeDetail': [
          {
            'deduction': 'no',
            'totalDeductionFee': '0',
            'totalFee': '-0.000001',
            'feeCoin': 'BTC',
          }
        ],
        'cTime': T,
      },
    )
  )
  mix = parse_classic_stream_fill(
    cast(
      MixFill1,
      {
        'tradeId': '2',
        'symbol': 'BTCUSDT',
        'side': 'sell',
        'price': '78400',
        'baseVolume': '0.001',
        'tradeScope': 'taker',
        'feeDetail': [],
        'cTime': T,
      },
    )
  )
  assert (spot.price, spot.qty, spot.maker) == (Decimal(78400), Decimal('0.001'), True)
  assert spot.fee is not None and spot.fee.amount == Decimal('0.000001')
  assert (mix.price, mix.qty, mix.maker, mix.fee) == (
    Decimal(78400),
    Decimal('-0.001'),
    False,
    None,
  )


UTA_FILL: dict[str, Any] = {
  'execId': '7',
  'symbol': 'XRPUSDT',
  'side': 'buy',
  'tradeScope': 'taker',
  'execPrice': Decimal('1.42'),
  'execQty': Decimal('1.1002'),
  'feeDetail': [{'feeCoin': 'XRP', 'fee': Decimal('0.0011002')}],
}
"""One live UTA spot fill, with only the fields the mapping reads."""


def test_a_uta_fee_keeps_its_sign_and_a_streamed_fill_maps_like_its_rest_twin():
  """UTA already signs fees the SDK's way. The stream push names its timestamp
  `execTime` where the REST row says `createdTime`; everything else agrees."""
  rest = parse_uta_fill(cast(Fill, {**UTA_FILL, 'createdTime': T}))
  streamed = parse_uta_stream_fill(cast(FillUpdate, {**UTA_FILL, 'execTime': T}))
  assert rest.fee is not None
  assert (rest.fee.amount, rest.fee.asset) == (Decimal('0.0011002'), 'XRP')
  assert (rest.qty, rest.price, rest.maker, rest.time) == (
    Decimal('1.1002'),
    Decimal('1.42'),
    False,
    T,
  )
  assert (streamed.id, streamed.qty, streamed.price, streamed.time, streamed.fee) == (
    rest.id,
    rest.qty,
    rest.price,
    rest.time,
    rest.fee,
  )
  upper = parse_uta_fill(
    cast(Fill, {**UTA_FILL, 'tradeScope': 'MAKER', 'createdTime': T})
  )
  assert upper.maker


def test_candle_rows_keep_the_base_and_quote_volumes():
  """A spot row carries the volume three ways and a futures row two; the base coin
  and the quote coin are kept, the USDT conversion between them dropped."""
  spot = parse_spot_candle(
    (
      T,
      Decimal(1),
      Decimal(3),
      Decimal(0),
      Decimal(2),
      Decimal(10),
      Decimal(15),
      Decimal(20),
    )
  )
  assert (spot.time, spot.open, spot.high, spot.low, spot.close) == (T, 1, 3, 0, 2)
  assert (spot.volume, spot.quote_volume) == (Decimal(10), Decimal(20))
  perp = parse_perp_candle(
    (T, Decimal(1), Decimal(3), Decimal(0), Decimal(2), Decimal(10), Decimal(20))
  )
  assert (perp.volume, perp.quote_volume) == (Decimal(10), Decimal(20))
