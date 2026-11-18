"""Trading a USDT-margined perpetual on a Unified Trading Account (UTA).

Orders go on cross margin in one-way position mode, the account's settings this
adapter supports: a Classic account and the USDC product line raise
`NotImplementedError` rather than place an order whose margin bucket is a guess, and a
hedge-mode account is refused by Bitget itself (it requires a `posSide`).
"""

from typing_extensions import Any, Literal, TypedDict, cast
from decimal import Decimal

from tribulnation.sdk.core import (
  ApiError,
  BadRequest,
  LeverageNotSet,
  OrderNotFound,
  OrderRejected,
)
from tribulnation.sdk.util import whole_leverage
from tribulnation.sdk.market import Order, OrderResponse, OrderState, Settings
from typed_bitget.uta.trade.order.info import OrderInfo
from typed_bitget.uta.trade.order.place import LimitOrderRequest

from .mixin import MarketMixin
from .orders import open_orders
from .parse import PERP

TimeInForce = Literal['gtc', 'ioc', 'fok', 'post_only']


class BitgetSettings(TypedDict, total=False):
  """Venue settings, under `settings['bitget']`."""

  time_in_force: Literal['gtc', 'ioc', 'fok']
  """Time in force a `LIMIT` order is sent with: `gtc` (rests, the default), `ioc` or
  `fok`."""
  reduce_only: bool
  """Only reduce the position."""


NOT_FOUND_CODES = frozenset({'25204', '40768', '43001'})
"""Codes answering that an order does not exist: `25204` (UTA, confirmed live on
`order-info` for an unknown ID, 2026-11-16), `40768`/`43001` (Classic v2's)."""

REJECTED_CODES = frozenset({'22002', '40762', '43012', '45110'})
"""Codes refusing an order outright, nothing placed: no position to reduce (`22002`),
size over the balance (`40762`), insufficient balance (`43012`), under the minimum
order value (`45110`). Malformed requests (`BadRequest`) are refusals too; any other
error stays an ambiguous `ApiError`."""

TERMINAL_STATUSES = frozenset({'filled', 'cancelled', 'canceled', 'rejected'})
"""`orderStatus` values of an order that no longer rests; any other (`live`,
`partially_filled`, ...) is active."""


def error_code(e: ApiError) -> str | None:
  """Bitget's embedded error code of an SDK `ApiError`, if it carries one."""
  if e.args and isinstance(code := e.args[0], str):
    return code


def venue_settings(settings: Settings) -> BitgetSettings:
  """This venue's entry of `settings`."""
  return cast(BitgetSettings, settings.get('bitget') or {})


def time_in_force(order: Order, settings: BitgetSettings) -> TimeInForce:
  """The Bitget time in force of an SDK order.

  `POST_ONLY` is `post_only`; `MARKET` is an `ioc` limit at the order's price, which
  bounds it; `LIMIT` takes `settings['time_in_force']`, `gtc` by default.
  """
  match order['type']:
    case 'POST_ONLY':
      return 'post_only'
    case 'MARKET':
      return 'ioc'
    case 'LIMIT':
      return settings.get('time_in_force', 'gtc')


def order_request(
  market: MarketMixin, order: Order, settings: BitgetSettings
) -> LimitOrderRequest:
  """The UTA `place-order` request placing `order` on cross margin."""
  qty = Decimal(order['qty'])
  request: LimitOrderRequest = {
    'category': PERP,
    'symbol': market.symbol,
    'qty': abs(qty),
    'price': Decimal(order['price']),
    'side': 'buy' if qty > 0 else 'sell',
    'orderType': 'limit',
    'timeInForce': time_in_force(order, settings),
    'marginMode': 'crossed',
  }
  if (client_oid := order.get('client_order_id')) is not None:
    request['clientOid'] = client_oid
  if (reduce_only := settings.get('reduce_only')) is not None:
    request['reduceOnly'] = 'yes' if reduce_only else 'no'
  return request


def parse_order_info(info: OrderInfo) -> OrderState:
  """Map a UTA `order-info` row onto an `OrderState`, terminal states included."""
  s = 1 if info['side'] == 'buy' else -1
  return OrderState(
    id=info['orderId'],
    price=info['price'],
    qty=s * info['qty'],
    filled_qty=s * info['cumExecQty'],
    active=info['orderStatus'] not in TERMINAL_STATUSES,
    details=info,
  )


async def require_trading(self: MarketMixin):
  """Refuse to trade anywhere but a UTA account's USDT-margined perpetuals.

  Raises:
    NotImplementedError: Not a `USDT-FUTURES` market, or a Classic account.
  """
  if self.product != PERP:
    raise NotImplementedError(
      f'Bitget trading is implemented for USDT-FUTURES only, not {self.product}.'
    )
  if not await self.is_uta():
    raise NotImplementedError(
      'Bitget trading is implemented for Unified Trading Accounts only.'
    )


def refusal(e: ApiError) -> ApiError:
  """`e` as `OrderRejected` when Bitget refused the order outright, else unchanged."""
  if isinstance(e, BadRequest) or error_code(e) in REJECTED_CODES:
    return OrderRejected(*e.args)
  else:
    return e


async def order_info(self: MarketMixin, id: str) -> OrderInfo | None:
  """The UTA `order-info` row of order `id`, or `None` if Bitget does not know it."""
  try:
    return await self.call(
      lambda: self.client.uta.trade.order.info(order_id=id, validate=self.validate)
    )
  except ApiError as e:
    if error_code(e) not in NOT_FOUND_CODES:
      raise


async def place_order(
  self: MarketMixin, order: Order, *, settings: Settings = {}
) -> OrderResponse:
  """Place a `LIMIT` (`gtc`, or the settings' time in force), `POST_ONLY` or `MARKET`
  (an `ioc` limit at `price`) order.

  Bitget's placement answers only the order ID. An immediate order (IOC, FOK or
  `MARKET`) is read back once: if it is already done, `filled_qty` is its final fill,
  else `None`.

  Raises:
    OrderRejected: Bitget refused it outright (`BadRequest`, or a code in
      `REJECTED_CODES`): nothing was placed.
  """
  await require_trading(self)
  request = order_request(self, order, venue_settings(settings))
  try:
    result = await self.call(
      lambda: self.client.uta.trade.order.place(request, validate=self.validate)
    )
  except ApiError as e:
    if (mapped := refusal(e)) is not e:
      raise mapped from e
    raise
  filled = None
  if request.get('timeInForce') in ('ioc', 'fok'):
    info = await order_info(self, result['orderId'])
    if info is not None and info['orderStatus'] in TERMINAL_STATUSES:
      filled = info['cumExecQty']
  return OrderResponse(id=result['orderId'], details=result, filled_qty=filled)


async def cancel_order(self: MarketMixin, id: str) -> Any:
  """Cancel order `id`.

  Raises:
    OrderNotFound: Bitget answered that the order does not exist (filled, cancelled,
      or never placed).
  """
  await require_trading(self)
  try:
    return await self.call(
      lambda: self.client.uta.trade.order.cancel(
        order_id=id, category=PERP, symbol=self.symbol, validate=self.validate
      )
    )
  except ApiError as e:
    if error_code(e) in NOT_FOUND_CODES:
      raise OrderNotFound(*e.args) from e
    raise


async def cancel_open_orders(self: MarketMixin) -> Any:
  """Cancel every open order on this symbol in one request.

  With nothing open, Bitget answers `25204` (order does not exist; confirmed live,
  2026-11-16): that is nothing to cancel, so an empty result is returned.
  """
  await require_trading(self)
  try:
    return await self.call(
      lambda: self.client.uta.trade.order.cancel_symbol(
        PERP, symbol=self.symbol, validate=self.validate
      )
    )
  except ApiError as e:
    if error_code(e) in NOT_FOUND_CODES:
      return {'list': []}
    raise


async def replace_order(
  self: MarketMixin, id: str, order: Order, *, settings: Settings = {}
) -> OrderResponse:
  """Replace resting order `id` with `order`.

  An order with nothing filled, of the same side and time in force, is modified in
  place (`modify-order` with `autoCancel`, so a failed modify leaves nothing resting)
  and the answer's order ID returned. Any other is cancelled and `order` placed anew:
  Bitget's modified `qty` is the order's total size, filled part included.

  Raises:
    OrderRejected: Bitget refused the modification; `id` is cancelled.
  """
  await require_trading(self)
  info = await order_info(self, id)
  qty = Decimal(order['qty'])
  modifiable = (
    info is not None
    and info['orderStatus'] not in TERMINAL_STATUSES
    and info['cumExecQty'] == 0
    and info['side'] == ('buy' if qty > 0 else 'sell')
    and info['timeInForce'] == time_in_force(order, venue_settings(settings))
  )
  if modifiable:
    try:
      result = await self.call(
        lambda: self.client.uta.trade.order.modify(
          order_id=id,
          qty=str(abs(qty)),
          price=Decimal(order['price']),
          auto_cancel='yes',
          symbol=self.symbol,
          category=PERP,
          validate=self.validate,
        )
      )
    except ApiError as e:
      if (mapped := refusal(e)) is not e:
        raise mapped from e
      raise
    return OrderResponse(id=result['orderId'] or id, details=result)
  else:
    try:
      await cancel_order(self, id)
    except OrderNotFound:
      pass
    return await place_order(self, order, settings=settings)


async def query_order(self: MarketMixin, id: str) -> OrderState | None:
  """The state of order `id`, resting or done; `None` if Bitget does not know it.

  A Classic account finds resting orders only (the scan of `open_orders`).
  """
  self.require_account_surface()
  if self.product == PERP and await self.is_uta():
    info = await order_info(self, id)
    return None if info is None else parse_order_info(info)
  else:
    return next((o for o in await open_orders(self) if o.id == id), None)


async def cross_leverage(self: MarketMixin) -> Decimal:
  """The cross leverage set for this symbol on a UTA account (`account.settings`).

  Bitget lists a symbol's leverage only once it has been set, so a symbol without a
  cross row raises rather than guess the venue's default.

  Raises:
    NotImplementedError: Not a UTA account's `USDT-FUTURES` market.
    LeverageNotSet: No cross leverage is set for the symbol.
  """
  await require_trading(self)
  settings = await self.call(
    lambda: self.client.uta.account.settings(validate=self.validate)
  )
  rows = [
    Decimal(c['leverage'])
    for c in settings['symbolConfigList']
    if c['symbol'] == self.symbol
    and c['category'] == PERP
    and c['marginMode'] == 'crossed'
  ]
  if rows:
    return rows[0]
  else:
    raise LeverageNotSet(
      f'No cross leverage set on Bitget for {self.symbol}: set it once '
      '(`set_leverage`, or the app) before trading.'
    )


async def set_cross_leverage(self: MarketMixin, leverage: Decimal):
  """Set the symbol's cross leverage on a UTA account (`account/set-leverage`).

  Raises:
    NotImplementedError: Not a UTA account's `USDT-FUTURES` market.
    ValueError: `leverage` is not a positive whole number.
  """
  value = whole_leverage(leverage)
  await require_trading(self)
  await self.call(
    lambda: self.client.uta.account.leverage.set(
      PERP,
      symbol=self.symbol,
      leverage=str(value),
      margin_mode='crossed',
      validate=self.validate,
    )
  )
