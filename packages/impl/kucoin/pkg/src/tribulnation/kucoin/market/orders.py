"""SDK orders in KuCoin terms: validation on the grid, lot conversion and native rows.

Spot quantities are base units. A linear perpetual trades whole lots (contracts) of
`multiplier` base units each; every quantity crossing this module converts between the
two, and refuses a base quantity that is not a whole number of lots.
"""

import secrets
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal
from typing_extensions import Literal

from typed_kucoin.schemas import (
  FuturesBatchAddOrderResult,
  FuturesBatchCancelResult,
  FuturesAddOrderLimit,
  FuturesOrder,
  FuturesOrderEvent,
  FuturesTrade,
  HfAddOrderLimit,
  HfFill,
  HfOrder,
)
from typed_kucoin.streams.spot_margin_private.order_v2 import OrderChangeEvent
from tribulnation.sdk.core import ApiError, BadRequest, OrderNotFound, OrderRejected
from tribulnation.sdk.market import Order, OrderResponse, OrderState, Rules, Trade
from tribulnation.sdk.util import to_decimal
from ..errors import AMBIGUOUS_CODES, NOT_FOUND_CODES

Side = Literal['buy', 'sell']
TimeInForce = Literal['GTC', 'IOC']


@dataclass(frozen=True, kw_only=True)
class NativeOrder:
  """A validated SDK order: side, unsigned base quantity, price and execution flags."""

  side: Side
  qty: Decimal
  """Unsigned base quantity, a whole number of steps."""
  price: Decimal
  """Limit price on the tick grid; for `MARKET`, the worst acceptable price."""
  time_in_force: TimeInForce
  post_only: bool
  client_oid: str


def random_client_oid() -> str:
  """128 random bits as 32 hex digits, within both products' 40-character `clientOid`."""
  return secrets.token_hex(16)


def native_order(order: Order, rules: Rules) -> NativeOrder:
  """Validate an SDK order against the market's rules and map its type.

  `LIMIT` rests (GTC), `POST_ONLY` sets `postOnly`, and `MARKET` is an IOC limit at the
  SDK price, so the price stays a protection bound. Nothing is rounded: an off-grid value
  is the caller's to fix.

  Raises:
    ValueError: The quantity is zero, not a multiple of the step size, below the minimum
      size or notional, or above the maximum; or the price is not positive or off the
      tick grid.
  """
  qty = to_decimal(order['qty'])
  price = to_decimal(order['price'])
  size = abs(qty)
  if not qty.is_finite() or not qty:
    raise ValueError('Order quantity must be finite and nonzero')
  if not price.is_finite() or price <= 0:
    raise ValueError('Order price must be finite and positive')
  if not rules.valid_price(price):
    raise ValueError(
      f'Price {price} is not a multiple of the tick size {rules.tick_size}'
    )
  if size % rules.step_size != 0:
    raise ValueError(
      f'Quantity {size} is not a multiple of the step size {rules.step_size}'
    )
  if rules.fixed_min_qty is not None and size < rules.fixed_min_qty:
    raise ValueError(f'Quantity {size} is below the minimum {rules.fixed_min_qty}')
  if rules.max_qty is not None and size > rules.max_qty:
    raise ValueError(f'Quantity {size} is above the maximum {rules.max_qty}')
  if rules.min_value is not None and size * price < rules.min_value:
    raise ValueError(
      f'Order value {size * price} is below the minimum {rules.min_value}'
    )
  return NativeOrder(
    side='buy' if qty > 0 else 'sell',
    qty=size,
    price=price,
    time_in_force='IOC' if order['type'] == 'MARKET' else 'GTC',
    post_only=order['type'] == 'POST_ONLY',
    client_oid=order.get('client_order_id') or random_client_oid(),
  )


def plain(x: Decimal) -> Decimal:
  """`x` without exponent form or trailing zeros, as KuCoin parses it."""
  return Decimal(f'{x.normalize():f}')


def spot_request(symbol: str, order: NativeOrder) -> HfAddOrderLimit:
  """The HF limit order for a validated spot order."""
  request: HfAddOrderLimit = {
    'clientOid': order.client_oid,
    'symbol': symbol,
    'type': 'limit',
    'side': order.side,
    'price': plain(order.price),
    'size': plain(order.qty),
    'timeInForce': order.time_in_force,
  }
  if order.post_only:
    request['postOnly'] = True
  return request


def lots(qty: Decimal, multiplier: Decimal) -> int:
  """Whole contracts for an unsigned base quantity.

  Raises:
    ValueError: `qty` is not a whole number of contracts.
  """
  contracts = qty / multiplier
  if contracts != contracts.to_integral_value():
    raise ValueError(
      f'Quantity {qty} is not a whole number of contracts of {multiplier}'
    )
  return int(contracts)


def perp_request(
  symbol: str, order: NativeOrder, *, multiplier: Decimal, leverage: int
) -> FuturesAddOrderLimit:
  """The cross-margin limit order, in lots, for a validated perpetual order.

  Raises:
    ValueError: The quantity is not a whole number of contracts.
  """
  request: FuturesAddOrderLimit = {
    'clientOid': order.client_oid,
    'symbol': symbol,
    'side': order.side,
    'leverage': leverage,
    'type': 'limit',
    'price': plain(order.price),
    'size': lots(order.qty, multiplier),
    'timeInForce': order.time_in_force,
    'marginMode': 'CROSS',
  }
  if order.post_only:
    request['postOnly'] = True
  return request


def sign(side: Side) -> int:
  """`1` for buys and `-1` for sells."""
  return 1 if side == 'buy' else -1


def spot_order_state(row: HfOrder) -> OrderState:
  """A spot HF order with signed base quantities."""
  s = sign(row['side'])
  return OrderState(
    id=row['id'],
    price=row['price'],
    qty=s * row['size'],
    filled_qty=s * row['dealSize'],
    active=row['active'],
    details=row,
  )


def perp_order_state(row: FuturesOrder, multiplier: Decimal) -> OrderState:
  """A futures order, its lots converted to signed base quantities."""
  s = sign(row['side'])
  return OrderState(
    id=row['id'],
    price=row['price'],
    qty=s * row['size'] * multiplier,
    filled_qty=s * row['filledSize'] * multiplier,
    active=row['isActive'],
    details=row,
  )


def spot_trade(row: HfFill) -> Trade:
  """One spot HF fill with a signed base quantity and its fee asset."""
  return Trade(
    id=str(row['tradeId']),
    order_id=row['orderId'],
    price=row['price'],
    qty=sign(row['side']) * row['size'],
    time=row['createdAt'],
    maker=row['liquidity'] == 'maker',
    fee=Trade.Fee(amount=row['fee'], asset=row['feeCurrency']),
    details=row,
  )


def perp_trade(row: FuturesTrade, multiplier: Decimal) -> Trade:
  """One futures fill, its lots converted to a signed base quantity."""
  return Trade(
    id=row['tradeId'],
    order_id=row['orderId'],
    price=row['price'],
    qty=sign(row['side']) * row['size'] * multiplier,
    time=row['tradeTime'],
    maker=row['liquidity'] == 'maker',
    fee=Trade.Fee(amount=row['fee'], asset=row['feeCurrency']),
    details=row,
  )


def maker(event: OrderChangeEvent | FuturesOrderEvent) -> bool:
  """The fill's liquidity role: the fee charged when reported, else `liquidity`.

  KuCoin reports `liquidity` `taker` for a maker order matched against a hidden
  counterparty; `feeType` names the fee actually charged.
  """
  if (fee_type := event.get('feeType')) is not None:
    return fee_type == 'makerFee'
  else:
    return event.get('liquidity') == 'maker'


def spot_event_trade(event: OrderChangeEvent) -> Trade | None:
  """The fill a spot order push reports, if it is a `match`; pushes carry no fee."""
  if (
    event['type'] == 'match'
    and (price := event.get('matchPrice')) is not None
    and (size := event.get('matchSize')) is not None
  ):
    return Trade(
      id=event.get('tradeId'),
      order_id=event['orderId'],
      client_order_id=event['clientOid'] or None,
      price=price,
      qty=sign(event['side']) * size,
      time=event['ts'],
      maker=maker(event),
      details=event,
    )


def perp_event_trade(event: FuturesOrderEvent, multiplier: Decimal) -> Trade | None:
  """The fill a futures order push reports, if it is a `match`, in base units."""
  if (
    event['type'] == 'match'
    and (price := event.get('matchPrice')) is not None
    and (size := event.get('matchSize')) is not None
  ):
    return Trade(
      id=event.get('tradeId'),
      order_id=event['orderId'],
      client_order_id=event.get('clientOid') or None,
      price=price,
      qty=sign(event['side']) * size * multiplier,
      time=event['ts'],
      maker=maker(event),
      details=event,
    )


def batch_placed(
  row: FuturesBatchAddOrderResult,
) -> OrderResponse | Exception:
  """One batch placement item: its acknowledgement or its refusal."""
  if row['code'] == '200000':
    return OrderResponse(id=row['orderId'], details=row)
  elif row['code'] in AMBIGUOUS_CODES:
    return ApiError(row['code'], row['msg'], row)
  else:
    return OrderRejected(row['code'], row['msg'], row)


def batch_cancelled(
  row: FuturesBatchCancelResult,
) -> FuturesBatchCancelResult | Exception:
  """One batch cancel item: its acknowledgement, or `OrderNotFound`/`BadRequest`."""
  if row['code'] == '200000':
    return row
  elif row['code'] in NOT_FOUND_CODES:
    return OrderNotFound(row['code'], row['msg'], row)
  else:
    return BadRequest(row['code'], row['msg'], row)


def order_leverage(value: Decimal) -> int:
  """The whole leverage an order states: the setting rounded down, at least 1."""
  return max(int(value.to_integral_value(rounding=ROUND_FLOOR)), 1)
