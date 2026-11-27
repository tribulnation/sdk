"""Unified Trading Account rows in SDK terms: order requests, order states, fills,
balances, positions and the unified margin pool.

UTA uses one order API for every product line, selected by `tradeType`. Quantities are
base units on spot (`sizeUnit` `BASECCY`) and whole contracts on futures (`UNIT`); every
futures quantity crossing this module is converted with the contract multiplier.

References:
  - [UTA REST V2](https://www.kucoin.com/docs-new/v2/rest/ua/introduction)
"""

from decimal import Decimal
from typing_extensions import Literal, Sequence

from typed_kucoin.schemas import (
  UtaAddOrderLimit,
  UtaAddOrderMarket,
  UtaExecutionEvent,
  UtaFill,
  UtaOrder,
  UtaPosition,
)
from typed_kucoin.uta.account.balance import UtaAccountBalance
from typed_kucoin.uta.account.fee_rate import UtaFeeRates
from typed_kucoin.uta.account.overview import UtaAccountOverview
from typed_kucoin.uta.orders.batch_cancel import UtaBatchCancelItemResult
from tribulnation.sdk.core import ApiError, BadRequest, MissingData, OrderNotFound
from tribulnation.sdk.market import (
  Balance,
  Fees,
  OrderState,
  PerpCollateral,
  PerpPosition,
  Trade,
)
from ..errors import NOT_FOUND_CODES
from .orders import NativeOrder, lots, plain

TradeType = Literal['SPOT', 'FUTURES']
"""The UTA product lines this package trades: spot and futures (cross margin is not)."""
ZERO = Decimal(0)
LIVE = frozenset({0, 1, 2, 4})
"""Order statuses still able to fill: not triggered, triggered, live, partially filled."""
DONE = frozenset({3, 5, 6})
"""Final order statuses: filled, cancelled with nothing filled, partially filled then
cancelled."""
FILL_TYPES = frozenset({'NORMAL', 'LIQUID', 'ADL'})
"""Fill types that change the position; `SETTLEMENT` (delivery) rows do not."""


def decimal(value: Decimal | str | None) -> Decimal | None:
  """A decimal field KuCoin may send as an empty string; `None` when empty."""
  if isinstance(value, Decimal):
    return value
  elif value:
    return Decimal(value)


def sign(side: Literal['BUY', 'SELL']) -> int:
  """`1` for buys and `-1` for sells."""
  return 1 if side == 'BUY' else -1


def order_request(
  symbol: str, order: NativeOrder, *, trade_type: TradeType, multiplier: Decimal
) -> UtaAddOrderLimit | UtaAddOrderMarket:
  """The UTA limit order for a validated SDK order.

  Spot sizes are base units; futures sizes are whole contracts on cross margin. `MARKET`
  stays an IOC limit at the SDK price, so the price remains a protection bound.

  Raises:
    ValueError: A futures quantity is not a whole number of contracts.
  """
  if trade_type == 'SPOT':
    size, unit = plain(order.qty), 'BASECCY'
  else:
    size, unit = Decimal(lots(order.qty, multiplier)), 'UNIT'
  request: UtaAddOrderLimit = {
    'tradeType': trade_type,
    'clientOid': order.client_oid,
    'symbol': symbol,
    'side': 'BUY' if order.side == 'buy' else 'SELL',
    'orderType': 'LIMIT',
    'size': size,
    'sizeUnit': unit,
    'price': plain(order.price),
    'timeInForce': order.time_in_force,
  }
  if order.post_only:
    request['postOnly'] = True
  if trade_type == 'FUTURES':
    request['marginMode'] = 'CROSS'
  return request


def order_state(row: UtaOrder, multiplier: Decimal) -> OrderState:
  """A UTA order with signed base quantities (`multiplier` is `1` on spot)."""
  s = sign(row['side'])
  return OrderState(
    id=row['orderId'],
    price=decimal(row.get('price')) or ZERO,
    qty=s * row['size'] * multiplier,
    filled_qty=s * row['filledSize'] * multiplier,
    active=row['status'] in LIVE,
    details=row,
  )


def trade(row: UtaFill, multiplier: Decimal) -> Trade:
  """One UTA fill with a signed base quantity and its fee (negative is a rebate)."""
  return Trade(
    id=row['tradeId'],
    order_id=row['orderId'],
    client_order_id=row.get('clientOid') or None,
    price=row['price'],
    qty=sign(row['side']) * row['size'] * multiplier,
    time=row['executionTime'],
    maker=row.get('liquidityRole') == 'MAKER',
    fee=Trade.Fee(amount=row['fee'], asset=row['feeCurrency']),
    details=row,
  )


def event_trade(event: UtaExecutionEvent, multiplier: Decimal) -> Trade:
  """One fill from the UTA `execution` channel, with its fee when reported."""
  fee = event.get('f')
  asset = event.get('fC')
  return Trade(
    id=str(event['ti']),
    order_id=event['oi'],
    client_order_id=event.get('ci') or None,
    price=event['p'],
    qty=sign(event['S']) * event['q'] * multiplier,
    time=event['E'],
    maker=event.get('lR') == 'MAKER',
    fee=Trade.Fee(amount=fee, asset=asset) if fee is not None and asset else None,
    details=event,
  )


def cancelled(row: UtaBatchCancelItemResult) -> UtaBatchCancelItemResult | Exception:
  """One batch cancel item: its acknowledgement, or `OrderNotFound`/`BadRequest`."""
  code = row.get('code', '200000')
  if code == '200000':
    return row
  elif code in NOT_FOUND_CODES:
    return OrderNotFound(code, row.get('msg', ''), row)
  else:
    return BadRequest(code, row.get('msg', ''), row)


def fees(rows: UtaFeeRates, symbol: str) -> Fees:
  """The account's rates on one symbol; a negative maker rate is a rebate.

  Raises:
    MissingData: The answer omits the symbol.
  """
  for row in rows['list']:
    if row['symbol'] == symbol:
      return Fees.symmetric(maker=row['makerFeeRate'], taker=row['takerFeeRate'])
  raise MissingData(
    'KuCoin fee rates omit the symbol', market_id=symbol, field='symbol'
  )


def balance(account: UtaAccountBalance, asset: str) -> Balance:
  """One currency of the unified account, zero when it holds none.

  `total` is the actual spot `balance`. `free` is what spot orders can spend, KuCoin's
  rule: `balance + min(unrealized PnL, 0) - hold`, where unrealized PnL is `equity -
  balance`, so futures losses reduce it and futures profits do not add to it.
  """
  total = free = ZERO
  for group in account['accounts']:
    for row in group['currencies']:
      if row['currency'] == asset:
        total += row['balance']
        free += min(row['balance'], row['equity']) - row['hold']
  return Balance(total=total, free=max(free, ZERO))


def position_row(rows: Sequence[UtaPosition], symbol: str) -> UtaPosition | None:
  """The symbol's one-way position row, `None` when flat."""
  for row in rows:
    if row['symbol'] == symbol:
      return row


def perp_position(row: UtaPosition | None, multiplier: Decimal) -> PerpPosition:
  """A one-way position in base units; a missing row or zero size is flat."""
  if row is not None and row['size'] != 0:
    liquidation = decimal(row.get('liquidationPrice'))
    return PerpPosition(
      size=row['size'] * multiplier,
      entry_price=row['entryPrice'],
      liquidation_price=liquidation
      if liquidation is not None and liquidation > 0
      else None,
    )
  else:
    return PerpPosition()


def leverage_of(notional: Decimal, equity: Decimal) -> Decimal:
  """Notional over equity; zero without positive equity."""
  return notional / equity if equity > 0 else ZERO


def unified_collateral(
  overview: UtaAccountOverview, rows: Sequence[UtaPosition]
) -> PerpCollateral:
  """The one unified cross pool behind every cross position and new order, in USD.

  Equity is the collateral-adjusted equity (each collateral currency's value times its
  collateral ratio, USDT and USDC included, less liabilities): what liquidation compares
  maintenance margin against. Free collateral is KuCoin's `availableMargin`; initial and
  maintenance margin are the account's `im` and `mm`. Leverage sums the cross
  positions' values.
  """
  equity = overview['adjustedEquity']
  notional = sum(
    (abs(r['positionValue']) for r in rows if r['marginMode'] == 'CROSS'), ZERO
  )
  return PerpCollateral(
    equity=equity,
    free_collateral=overview['availableMargin'],
    initial_margin=overview['im'],
    maintenance_margin=overview['mm'],
    leverage=leverage_of(notional, equity),
    margin_mode='cross',
  )


def isolated_collateral(row: UtaPosition) -> PerpCollateral:
  """An isolated position's own bucket: its margin plus unrealized PnL."""
  margin = row.get('positionMargin')
  if margin is None:
    raise MissingData(
      'KuCoin isolated position omits its margin',
      market_id=row['symbol'],
      field='positionMargin',
    )
  equity = margin + row['unrealizedPnL']
  initial = row.get('initialMargin', margin)
  return PerpCollateral(
    equity=equity,
    free_collateral=max(equity - initial, ZERO),
    initial_margin=initial,
    maintenance_margin=row['maintenanceMargin'],
    leverage=leverage_of(abs(row['positionValue']), equity),
    margin_mode='isolated',
  )


def ended_unfilled(row: UtaOrder) -> bool:
  """Whether an order is final with nothing filled (an unmatched IOC, a crossing
  post-only cancelled by the venue)."""
  return row['status'] in DONE and row['filledSize'] == 0


def check_leverage(applied: Decimal | None, symbol: str):
  """Raise when a leverage change answered without the leverage it set.

  Raises:
    ApiError: KuCoin's answer carries no leverage.
  """
  if applied is None:
    raise ApiError(f'KuCoin did not change the {symbol} leverage')
