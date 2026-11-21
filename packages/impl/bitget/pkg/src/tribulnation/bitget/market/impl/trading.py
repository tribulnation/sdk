"""Trading a USDT-margined perpetual or a spot-margin pair on a Unified Trading
Account (UTA).

Perpetual orders go on cross margin in one-way position mode, the account's settings
this adapter supports: a Classic account and the USDC product line raise
`NotImplementedError` rather than place an order whose margin bucket is a guess, and a
hedge-mode account is refused by Bitget itself (it requires a `posSide`).

Spot-margin (`MARGIN`) orders trade the pair's spot book on the unified pool: a sell of
more base than the pool holds auto-borrows the rest at placement, and a buy repays
debt first (the account's `repayMode: auto`). Bitget takes no `marginMode` or
`reduceOnly` on them.
"""

from typing_extensions import Any, Literal, TypedDict, cast
from decimal import Decimal
import logging

from tribulnation.sdk.core import (
  ApiError,
  BadRequest,
  LeverageNotSet,
  NetworkError,
  OrderNotFound,
  OrderRejected,
)
from tribulnation.sdk.market import Order, OrderResponse, OrderState, Settings
from tribulnation.sdk.util import to_decimal, whole_leverage
from typed_bitget.uta.trade.order.info import OrderInfo
from typed_bitget.uta.trade.order.place import LimitOrderRequest

from .mixin import MarketMixin
from .orders import open_orders
from .parse import MARGIN, PERP

log = logging.getLogger(__name__)

TimeInForce = Literal['gtc', 'ioc', 'fok', 'post_only']


class BitgetSettings(TypedDict, total=False):
  """Venue settings, under `settings['bitget']`."""

  time_in_force: Literal['gtc', 'ioc', 'fok']
  """Time in force a `LIMIT` order is sent with: `gtc` (rests, the default), `ioc` or
  `fok`."""
  reduce_only: bool
  """Only reduce the position. Perpetuals only: a spot-margin order refuses it."""


NOT_FOUND_CODES = frozenset({'25204', '40768', '43001'})
"""Codes answering that an order does not exist: `25204` (UTA, confirmed live on
`order-info` for an unknown ID, 2026-11-16), `40768`/`43001` (Classic v2's)."""

REJECTED_CODES = frozenset({'22002', '40092', '40762', '43012', '45110'})
"""Codes refusing an order outright, nothing placed: no position to reduce (`22002`),
service unavailable to the account for regulatory or eligibility reasons (`40092`,
seen live), size over the balance (`40762`), insufficient balance (`43012`), under the
minimum order value (`45110`). Malformed requests (`BadRequest`) are refusals too; any other
error stays an ambiguous `ApiError`."""

TradingProduct = Literal['USDT-FUTURES', 'MARGIN']
"""The categories this adapter trades."""

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


def trading_product(market: MarketMixin) -> TradingProduct:
  """The market's category, when it is one this adapter trades.

  Raises:
    NotImplementedError: Not a `USDT-FUTURES` or `MARGIN` market.
  """
  product = market.product
  if product == PERP or product == MARGIN:
    return product
  else:
    raise NotImplementedError(
      f'Bitget trading is implemented for USDT-FUTURES and MARGIN only, not {product}.'
    )


def order_request(
  market: MarketMixin, order: Order, settings: BitgetSettings
) -> LimitOrderRequest:
  """The UTA `place-order` request placing `order`: on cross margin for a perpetual,
  on the unified pool (auto-borrowing) for a spot-margin pair.

  Raises:
    NotImplementedError: `reduce_only` was asked of a spot-margin order, which Bitget
      does not take: sending the order without it would place a different order.
  """
  qty = to_decimal(order['qty'])
  product = trading_product(market)
  request: LimitOrderRequest = {
    'category': product,
    'symbol': market.symbol,
    'qty': abs(qty),
    'price': to_decimal(order['price']),
    'side': 'buy' if qty > 0 else 'sell',
    'orderType': 'limit',
    'timeInForce': time_in_force(order, settings),
  }
  if product == PERP:
    request['marginMode'] = 'crossed'
  if (client_oid := order.get('client_order_id')) is not None:
    request['clientOid'] = client_oid
  if (reduce_only := settings.get('reduce_only')) is not None:
    if product == MARGIN:
      raise NotImplementedError('Bitget spot-margin orders take no reduce-only flag.')
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


async def require_trading(self: MarketMixin) -> TradingProduct:
  """Refuse to trade anywhere but a UTA account's USDT-margined perpetuals and
  spot-margin pairs; the market's category otherwise.

  Raises:
    NotImplementedError: Not a `USDT-FUTURES` or `MARGIN` market, or a Classic
      account.
  """
  product = trading_product(self)
  if not await self.is_uta():
    raise NotImplementedError(
      'Bitget trading is implemented for Unified Trading Accounts only.'
    )
  return product


async def require_perp_trading(self: MarketMixin):
  """`require_trading`, narrowed to a UTA account's USDT-margined perpetuals.

  Raises:
    NotImplementedError: Not a `USDT-FUTURES` market, or a Classic account.
  """
  if await require_trading(self) != PERP:
    raise NotImplementedError('Bitget per-symbol leverage is a perpetual setting.')


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
  else `None`. A failed read-back is logged and also leaves `filled_qty` `None`: the
  order was placed, so the placement is returned rather than an error a caller could
  retry into a second order.

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
    try:
      info = await order_info(self, result['orderId'])
    except (NetworkError, ApiError) as e:
      log.warning('Reading back placed order %s failed: %s', result['orderId'], e)
    else:
      if info is not None and info['orderStatus'] in TERMINAL_STATUSES:
        filled = info['cumExecQty']
  return OrderResponse(id=result['orderId'], details=result, filled_qty=filled)


async def cancel_order(self: MarketMixin, id: str) -> Any:
  """Cancel order `id`.

  Raises:
    OrderNotFound: Bitget answered that the order does not exist (filled, cancelled,
      or never placed).
  """
  product = await require_trading(self)
  try:
    return await self.call(
      lambda: self.client.uta.trade.order.cancel(
        order_id=id, category=product, symbol=self.symbol, validate=self.validate
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
  product = await require_trading(self)
  try:
    return await self.call(
      lambda: self.client.uta.trade.order.cancel_symbol(
        product, symbol=self.symbol, validate=self.validate
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

  On a perpetual, an order with nothing filled, of the same side and time in force, is
  modified in place (`modify-order` with `autoCancel`, so a failed modify leaves
  nothing resting) and the answer's order ID returned. Any other is cancelled and
  `order` placed anew: Bitget's modified `qty` is the order's total size, filled part
  included. A spot-margin order is always cancelled and placed anew, so the borrow
  taken at placement follows the new order alone.

  Raises:
    OrderRejected: Bitget refused the modification; `id` is cancelled.
  """
  product = await require_trading(self)
  info = None if product == MARGIN else await order_info(self, id)
  qty = to_decimal(order['qty'])
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
          price=to_decimal(order['price']),
          auto_cancel='yes',
          symbol=self.symbol,
          category=product,
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
  if self.product in (PERP, MARGIN) and await self.is_uta():
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
  await require_perp_trading(self)
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


async def set_cross_leverage(self: MarketMixin, leverage: Decimal) -> int:
  """Set the symbol's cross leverage on a UTA account (`account/set-leverage`).

  The SDK trades Bitget on cross margin only, so the cross setting is the one sent;
  an isolated row is left alone. The value must be a whole multiple no higher than
  the contract's `maxLever`, checked before anything is sent. Leverage reads are not
  shared, so the next `leverage()` reads the new setting. Returns the value sent.

  Raises:
    ValueError: `leverage` is not a positive whole number, or exceeds `maxLever`.
    NotImplementedError: Not a UTA account's `USDT-FUTURES` market.
  """
  value = whole_leverage(leverage)
  await require_perp_trading(self)
  contracts = await self.perp_contracts(PERP)
  max_leverage = contracts[self.symbol]['maxLever']
  if value > max_leverage:
    raise ValueError(
      f'Leverage {value} exceeds the maximum of {max_leverage} on Bitget {self.symbol}'
    )
  await self.call(
    lambda: self.client.uta.account.leverage.set(
      PERP,
      symbol=self.symbol,
      leverage=str(value),
      margin_mode='crossed',
      validate=self.validate,
    )
  )
  return value
