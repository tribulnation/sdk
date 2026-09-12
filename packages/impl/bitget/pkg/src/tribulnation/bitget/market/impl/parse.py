"""Mapping between Bitget payloads and the SDK's market types."""

from typing_extensions import Literal, Sequence
from datetime import datetime, timedelta
from decimal import Decimal

from tribulnation.sdk.market import (
  Book,
  Fees,
  OrderState,
  PerpStats,
  Rules,
  Ticker,
  Trade,
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

from .util import dec

PerpProduct = Literal['USDT-FUTURES', 'USDC-FUTURES', 'COIN-FUTURES']
"""Native futures product lines, excluding dated contracts during discovery."""

Product = Literal['SPOT', 'USDT-FUTURES', 'USDC-FUTURES', 'COIN-FUTURES']
"""Bitget product lines used to address public endpoints.

The same strings name a Classic v2 `productType`/`instType` and a UTA v3
`category`, so one alias serves both account modes.
"""

PERP: Literal['USDT-FUTURES'] = 'USDT-FUTURES'
"""The USDT-margined product behind the `usdt` exchange."""

PERP_PRODUCTS: dict[str, PerpProduct] = {
  'usdt': PERP,
  'usdc': 'USDC-FUTURES',
  'coin-classic': 'COIN-FUTURES',
}
"""Stable SDK exchange IDs mapped to native product types."""


def perp_exchange_id(product: PerpProduct) -> str:
  """Resolve the exchange identity without deriving it from a symbol suffix."""
  return next(key for key, value in PERP_PRODUCTS.items() if value == product)


MARGIN_COIN = 'USDT'
"""Margin coin of every `USDT-FUTURES` contract (confirmed live: 780 of 780)."""

DepthLimit = Literal['1', '5', '15', '50', 'max']
"""Order book depths `classic.mix.market.orderbook` serves."""

DEPTH_LIMITS: Sequence[tuple[int, DepthLimit]] = (
  (1, '1'),
  (5, '5'),
  (15, '15'),
  (50, '50'),
)
"""Numeric depths of the fixed limit enum, ascending; `'max'` is 100 levels (confirmed live)."""


def perp_depth_limit(levels: int | None) -> DepthLimit:
  """The smallest fixed depth that covers `levels`, `'max'` for `None` or anything past 50.

  The futures order book takes a fixed enum where the spot one takes any integer, so a
  requested size is served by the next enum member up and trimmed to size by the caller.
  """
  if levels is None:
    return 'max'
  for depth, limit in DEPTH_LIMITS:
    if levels <= depth:
      return limit
  return 'max'


def parse_book(
  bids: Sequence[tuple[Decimal | float, Decimal | float]],
  asks: Sequence[tuple[Decimal | float, Decimal | float]],
) -> Book:
  """Build a `Book` from Bitget's `[price, size]` level arrays, whichever number shape."""
  return Book(
    bids=[Book.Entry(dec(price), dec(qty)) for price, qty in bids],
    asks=[Book.Entry(dec(price), dec(qty)) for price, qty in asks],
  )


def parse_spot_ticker(ticker: SpotTicker) -> Ticker:
  """Map one spot ticker row onto a `Ticker`.

  `bidSz`/`askSz` are `null` on a one-sided book (2 of 1305 symbols live), which the
  client declares, so they pass through as `None`.
  """
  return Ticker(
    last=ticker['lastPr'],
    bid=ticker['bidPr'],
    ask=ticker['askPr'],
    bid_qty=ticker['bidSz'],
    ask_qty=ticker['askSz'],
    base_volume_24h=ticker['baseVolume'],
  )


def parse_perp_ticker(ticker: MixTicker) -> Ticker:
  """Map one futures ticker row onto a `Ticker`."""
  return Ticker(
    last=ticker['lastPr'],
    bid=ticker['bidPr'],
    ask=ticker['askPr'],
    bid_qty=ticker['bidSz'],
    ask_qty=ticker['askSz'],
    base_volume_24h=ticker['baseVolume'],
  )


def parse_perp_stats(
  ticker: MixTicker, funding: CurrentFundingRate | None
) -> PerpStats:
  """Map one futures ticker row, plus its funding schedule, onto `PerpStats`.

  The ticker carries index, mark, the current rate and open interest (`holdingAmount`,
  in base coin); the settlement time and interval come from the funding-rate endpoint,
  which lists symbols independently, so a contract it omits reports neither.
  """
  return PerpStats(
    index=ticker['indexPrice'],
    mark=ticker['markPrice'],
    funding=ticker['fundingRate'],
    next_funding_time=funding['nextUpdate'] if funding else None,
    funding_interval=(
      timedelta(hours=funding['fundingRateInterval']) if funding else None
    ),
    open_interest=ticker['holdingAmount'],
  )


def parse_spot_rules(symbol: SpotSymbol) -> Rules:
  """Map one spot symbol's trading rules onto `Rules`.

  Bitget publishes decimal-place *counts* (`pricePrecision`, `quantityPrecision`)
  rather than tick and step sizes, so both are derived as powers of ten. The fee rates
  are the venue's default tier, not the account's. `minTradeAmount` is `0` on 1299 of
  1305 symbols, in which case the step size is the effective minimum. `minTradeUSDT`
  is Bitget's USDT-denominated minimum notional, reported as `min_value` whatever the
  quote coin.
  """
  return Rules(
    fee_asset=symbol['quoteCoin'],
    tick_size=Decimal(10) ** -symbol['pricePrecision'],
    step_size=Decimal(10) ** -symbol['quantityPrecision'],
    fixed_min_qty=symbol['minTradeAmount'] or None,
    min_value=symbol['minTradeUSDT'],
    max_qty=symbol['maxTradeAmount'],
    rel_min_price=1 - symbol['sellLimitPriceRatio'],
    rel_max_price=1 + symbol['buyLimitPriceRatio'],
    fees=Fees.symmetric(maker=symbol['makerFeeRate'], taker=symbol['takerFeeRate']),
    api=symbol['status'] == 'online',
    details=symbol,
  )


def parse_perp_rules(contract: MixContract, *, product: PerpProduct = PERP) -> Rules:
  """Map one futures contract's trading rules onto `Rules`.

  The tick is `priceEndStep` ticks of `10 ** -pricePlace` (every live contract has
  `priceEndStep == 1`, so this equals the PoC's bare power of ten); the step is the
  venue's own `sizeMultiplier`.
  """
  return Rules(
    fee_asset=contract['baseCoin']
    if product == 'COIN-FUTURES'
    else contract['quoteCoin'],
    tick_size=contract['priceEndStep'] * Decimal(10) ** -contract['pricePlace'],
    step_size=contract['sizeMultiplier'],
    fixed_min_qty=contract['minTradeNum'],
    # This endpoint denominates its minimum in USDT, not the contract's quote.
    # Do not assume USDT, USDC and USD are interchangeable units.
    min_value=contract['minTradeUSDT'] if product == PERP else None,
    max_qty=Decimal(contract['maxOrderQty']),
    rel_min_price=1 - contract['sellLimitPriceRatio'],
    rel_max_price=1 + contract['buyLimitPriceRatio'],
    # The public markup field is not documented as already included in these rates.
    # Do not claim a combined rate while its composition remains unresolved.
    fees=Fees.symmetric(maker=contract['makerFeeRate'], taker=contract['takerFeeRate'])
    if contract['feeRateUpRatio'] == 0
    else None,
    api=contract['symbolStatus'] == 'normal',
    details=contract,
  )


def sign(side: Literal['buy', 'sell']) -> int:
  """`+1` for a buy, `-1` for a sell: the SDK signs quantities by side."""
  return 1 if side == 'buy' else -1


def parse_spot_order(order: SpotOpenOrder) -> OrderState:
  """Map one Classic spot open order onto an `OrderState`.

  The endpoint lists only currently-open orders, so every row is `active`.
  """
  s = sign(order['side'])
  return OrderState(
    id=order['orderId'],
    price=Decimal(order['basePrice']),
    qty=s * Decimal(order['size']),
    filled_qty=s * Decimal(order['baseVolume']),
    active=True,
    details=order,
  )


def parse_mix_order(order: MixOpenOrder) -> OrderState:
  """Map one Classic futures open order onto an `OrderState`."""
  s = sign(order['side'])
  return OrderState(
    id=order['orderId'],
    price=Decimal(order['price']),
    qty=s * Decimal(order['size']),
    filled_qty=s * Decimal(order['baseVolume']),
    active=order['status'] in ('live', 'partially_filled'),
    details=order,
  )


def parse_uta_order(order: UnfilledOrder) -> OrderState:
  """Map one UTA unfilled order onto an `OrderState`.

  The endpoint lists only currently-unfilled orders, so every row is `active`.
  """
  s = sign(order['side'])
  return OrderState(
    id=order['orderId'],
    price=Decimal(order['price']),
    qty=s * Decimal(order['qty']),
    filled_qty=s * Decimal(order['cumExecQty']),
    active=True,
    details=order,
  )


def classic_fee(details: Sequence[tuple[str, Decimal | str]]) -> Trade.Fee | None:
  """Fold Classic `feeDetail` line items into one `Trade.Fee`.

  Classic v2 signs fees the opposite way to the SDK: a fee charged is a negative
  `totalFee` (confirmed live on futures fills, and in the client's recorded spot order
  history), so the sign is flipped rather than dropped -- a rebate stays a rebate. A
  fill charged in several coins reports the first coin's total only. No line items
  means the fee is unknown; a zero total is a real fee of zero.
  """
  if not details:
    return None
  asset = details[0][0]
  amount = sum((-Decimal(fee) for coin, fee in details if coin == asset), Decimal(0))
  return Trade.Fee(amount=amount, asset=asset)


def uta_fee(details: Sequence[tuple[str, Decimal]]) -> Trade.Fee | None:
  """Fold UTA `feeDetail` line items into one `Trade.Fee`.

  UTA v3 signs fees the SDK's way: positive when charged, negative when rebated. A
  fill charged in several coins reports the first coin's total only.
  """
  if not details:
    return None
  asset = details[0][0]
  amount = sum((fee for coin, fee in details if coin == asset), Decimal(0))
  return Trade.Fee(amount=amount, asset=asset)


def parse_spot_fill(fill: SpotOwnFill) -> Trade:
  """Map one Classic spot fill onto a `Trade`."""
  detail = fill['feeDetail']
  return Trade(
    id=fill['tradeId'],
    price=Decimal(fill['priceAvg']),
    qty=sign(fill['side']) * Decimal(fill['size']),
    time=fill['cTime'],
    maker=fill['tradeScope'] == 'maker',
    fee=classic_fee([(detail['feeCoin'], detail['totalFee'])]),
    details=fill,
  )


def parse_mix_fill(fill: MixOrderFill) -> Trade:
  """Map one Classic futures fill onto a `Trade`."""
  return Trade(
    id=fill['tradeId'],
    price=fill['price'],
    qty=sign(fill['side']) * fill['baseVolume'],
    time=fill['cTime'],
    maker=fill['tradeScope'] == 'maker',
    fee=classic_fee([(d['feeCoin'], d['totalFee']) for d in fill['feeDetail']]),
    details=fill,
  )


def parse_classic_stream_fill(fill: 'SpotFill | MixFill1') -> Trade:
  """Map one Classic `fill` channel push onto a `Trade`.

  The spot and futures shapes name their price and size differently (`priceAvg`/`size`
  against `price`/`baseVolume`) and send every number as a string.
  """
  if 'priceAvg' in fill:
    price, size = fill['priceAvg'], fill['size']
  else:
    price, size = fill['price'], fill['baseVolume']
  return Trade(
    id=fill['tradeId'],
    price=Decimal(price),
    qty=sign(fill['side']) * Decimal(size),
    time=fill['cTime'],
    maker=fill['tradeScope'] == 'maker',
    fee=classic_fee([(d['feeCoin'], d['totalFee']) for d in fill['feeDetail']]),
    details=fill,
  )


def uta_trade(fill: 'Fill | FillUpdate', time: datetime) -> Trade:
  """Map one UTA fill onto a `Trade`, given its timestamp.

  The REST row and the stream push agree on every field read here except the
  timestamp's name, which each caller reads for itself.
  """
  return Trade(
    id=fill['execId'],
    price=fill['execPrice'],
    qty=sign(fill['side']) * fill['execQty'],
    time=time,
    maker=fill['tradeScope'].lower() == 'maker',
    fee=uta_fee([(d['feeCoin'], d['fee']) for d in fill['feeDetail']]),
    details=fill,
  )


def parse_uta_fill(fill: Fill) -> Trade:
  """Map one UTA fill row from the REST history onto a `Trade`."""
  return uta_trade(fill, fill['createdTime'])


def parse_uta_stream_fill(fill: FillUpdate) -> Trade:
  """Map one UTA `fill` channel push onto a `Trade`."""
  return uta_trade(fill, fill['execTime'])
