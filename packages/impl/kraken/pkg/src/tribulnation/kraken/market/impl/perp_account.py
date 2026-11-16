"""Kraken Futures account answers as SDK values: positions, collateral, leverage,
orders, fills, fees and funding."""

from decimal import Decimal
from typing_extensions import Literal, Mapping, Sequence, TypedDict, TypeGuard

from tribulnation.sdk.core import ApiError, OrderNotFound, OrderRejected
from tribulnation.sdk.market import (
  Fees,
  FundingPayment,
  Order,
  OrderResponse,
  OrderState,
  PerpCollateral,
  PerpPosition,
  Trade,
)

from typed_kraken.futures.instruments import FuturesInstrument
from typed_kraken.schemas import FuturesMarginLevel
from typed_kraken.futures_trading.types import (
  AccountLogEntry,
  AccountsResult,
  BatchStatus,
  CancelStatus,
  CashAccount,
  EditStatus,
  ExecutionEvent,
  FeeSchedulesResult,
  FeeVolumesResult,
  Fill,
  FlexAccount,
  LeveragePreference,
  MarginAccount,
  OpenOrder,
  OpenPosition,
  OrderEvent,
  OrderStatusEntry,
  OrderType,
  OtherAccount,
  SendStatus,
)

ACCEPTED = frozenset(('placed', 'edited'))
"""Statuses of an order that rests or rested: anything else was not placed."""
ACTIVE = frozenset(('ENTERED_BOOK', 'PARTIALLY_FILLED', 'UNTOUCHED', 'TRIGGER_PLACED'))
"""`orders/status` statuses of an order still on the book."""
IMMEDIATE: frozenset[OrderType] = frozenset(('ioc', 'mkt'))


class KrakenSettings(TypedDict, total=False):
  """Venue settings, under `settings['kraken']`."""

  time_in_force: Literal['lmt', 'post', 'ioc']
  """Order type a `LIMIT` order is sent as: `lmt` (rests, the default), `post`
  (post-only) or `ioc` (immediate-or-cancel)."""
  reduce_only: bool
  """Only reduce the position."""


def order_type(order: Order, settings: KrakenSettings) -> OrderType:
  """The Kraken order type of an SDK order.

  `MARKET` is an `ioc` at the order's price, which bounds it; `POST_ONLY` is `post`.
  """
  match order['type']:
    case 'MARKET':
      return 'ioc'
    case 'POST_ONLY':
      return 'post'
    case 'LIMIT':
      return settings.get('time_in_force', 'lmt')


def is_execution(event: OrderEvent) -> TypeGuard[ExecutionEvent]:
  """Whether an order event is a fill."""
  return event['type'] == 'EXECUTION'


def executed(events: Sequence[OrderEvent]) -> Decimal:
  """Contracts the events filled."""
  return sum((event['amount'] for event in events if is_execution(event)), Decimal(0))


def order_response(
  status: SendStatus | BatchStatus, *, immediate: bool
) -> OrderResponse:
  """The response to an accepted order, or the rejection it was.

  An order is accepted when it was placed or filled on arrival: an IOC that filled
  in part reports `placed` with its executions, the rest cancelled.

  Args:
    status: `sendorder`'s or one batch instruction's status.
    immediate: The order was IOC, so what filled at placement is final.

  Raises:
    OrderRejected: Nothing was placed (`postWouldExecute`, `iocWouldNotExecute`,
      `insufficientAvailableFunds`, ...).
  """
  events = status.get('orderEvents') or []
  filled = executed(events)
  order_id = status.get('order_id')
  if (status['status'] in ACCEPTED or filled > 0) and order_id is not None:
    return OrderResponse(
      id=order_id,
      details=status,
      filled_qty=filled if immediate or filled > 0 else None,
    )
  else:
    raise OrderRejected(f'Kraken Futures refused the order: {status["status"]}', status)


def edit_outcome(status: EditStatus | BatchStatus, id: str) -> OrderResponse:
  """The response to an edit: the same order, resting with its new size and price.

  Raises:
    OrderNotFound: The order no longer rests (`orderForEditNotFound`).
    OrderRejected: The post-only edit would have crossed and the order was cancelled
      (`postWouldExecute`).
    ApiError: Any other refusal; the order still rests as it was.
  """
  match status['status']:
    case 'edited' | 'filled':
      return OrderResponse(
        id=id, details=status, filled_qty=executed(status.get('orderEvents') or [])
      )
    case 'orderForEditNotFound':
      raise OrderNotFound(f'Kraken Futures order {id} not found for edit', status)
    case 'postWouldExecute':
      raise OrderRejected(f'Kraken Futures post-only edit of {id} would cross', status)
    case other:
      raise ApiError(f'Kraken Futures did not edit order {id}: {other}', status)


def cancel_outcome(status: CancelStatus | BatchStatus, id: str) -> str | Exception:
  """A cancel's outcome: `cancelled`, or the reason it was not, as an error."""
  match status['status']:
    case 'cancelled':
      return 'cancelled'
    case 'notFound' | 'filled':
      return OrderNotFound(f'Kraken Futures order {id}: {status["status"]}', status)
    case other:
      return ApiError(f'Kraken Futures did not cancel order {id}: {other}', status)


def signed(side: str, qty: Decimal) -> Decimal:
  """`qty` signed by its side: buys and longs positive."""
  return qty if side in ('buy', 'long') else -qty


def open_order_state(row: OpenOrder) -> OrderState:
  """An open order: `qty` is its whole size, filled part included."""
  return OrderState(
    id=row['order_id'],
    price=row.get('limitPrice') or Decimal(0),
    qty=signed(row['side'], row['filledSize'] + row['unfilledSize']),
    filled_qty=signed(row['side'], row['filledSize']),
    active=True,
    details=row,
  )


def status_state(entry: OrderStatusEntry) -> OrderState:
  """An order's state from `orders/status`."""
  order = entry['order']
  return OrderState(
    id=order['orderId'],
    price=order.get('limitPrice') or Decimal(0),
    qty=signed(order['side'], order['quantity']),
    filled_qty=signed(order['side'], order['filled']),
    active=entry['status'] in ACTIVE,
    details=entry,
  )


def position(rows: Sequence[OpenPosition], symbol: str) -> PerpPosition:
  """The position in `symbol`, flat when there is none."""
  for row in rows:
    if row['symbol'].upper() == symbol.upper():
      return PerpPosition(
        size=signed(row['side'], row['size']), entry_price=row['price']
      )
  return PerpPosition()


def flex_account(result: AccountsResult) -> FlexAccount:
  """The multi-collateral account, which backs every `PF_` contract.

  Raises:
    ApiError: The user has no multi-collateral account.
  """
  account = result['accounts'].get('flex')
  if account is not None and is_flex(account):
    return account
  else:
    raise ApiError('Kraken Futures has no multi-collateral (flex) account', result)


def is_flex(
  account: FlexAccount | CashAccount | MarginAccount | OtherAccount,
) -> TypeGuard[FlexAccount]:
  """Whether an account is the multi-collateral one; other types stay open-ended."""
  return account['type'] == 'multiCollateralMarginAccount'


def flex_collateral(account: FlexAccount, *, notional: Decimal) -> PerpCollateral:
  """The multi-collateral (cross) bucket.

  Equity is `marginEquity` (haircut collateral plus unrealized P&L), free collateral
  `availableMargin` (what orders and positions do not hold).

  Args:
    account: The `flex` account.
    notional: Total position notional, for `leverage`.
  """
  equity = account['marginEquity']
  return PerpCollateral(
    equity=equity,
    free_collateral=account['availableMargin'],
    initial_margin=account['initialMarginWithOrders'],
    maintenance_margin=account['maintenanceMargin'],
    leverage=notional / equity if equity > 0 else Decimal(0),
    margin_mode='cross',
  )


def leverage_of(
  instrument: FuturesInstrument,
  preferences: Sequence[LeveragePreference],
  *,
  schedule: str | None,
) -> Decimal:
  """The leverage new positions in a market open at.

  A market with a leverage preference trades isolated at that leverage. Otherwise it
  trades cross, at the inverse of its first-tier retail initial margin: of the
  `marginSchedules` platform `schedule` when given, else the instrument's
  `retailMarginLevels`.

  Raises:
    ValueError: The instrument publishes no margin levels.
  """
  for row in preferences:
    if row['symbol'].upper() == instrument['symbol'].upper():
      return row['maxLeverage']
  levels: list[FuturesMarginLevel] = []
  if schedule is not None:
    if (margin := instrument.get('marginSchedules', {}).get(schedule)) is not None:
      levels = margin['retail']
  else:
    levels = instrument.get('retailMarginLevels') or instrument.get('marginLevels', [])
  if levels:
    return 1 / Decimal(str(levels[0]['initialMargin']))
  else:
    raise ValueError(f'Kraken instrument {instrument["symbol"]} has no margin levels')


def fees_of(
  instrument: FuturesInstrument,
  schedules: FeeSchedulesResult,
  volumes: FeeVolumesResult,
) -> Fees:
  """The account's rates in a market: its fee schedule's tier for the 30-day volume.

  Rates are published in percent.

  Raises:
    ValueError: The instrument names no known fee schedule.
  """
  uid = instrument.get('feeScheduleUid', '')
  for schedule in schedules['feeSchedules']:
    if schedule['uid'] == uid:
      volume = volumes['volumesByFeeSchedule'].get(uid, Decimal(0))
      tier = max(
        (t for t in schedule['tiers'] if t['usdVolume'] <= volume),
        key=lambda t: t['usdVolume'],
      )
      maker, taker = tier['makerFee'] / 100, tier['takerFee'] / 100
      return Fees(maker_buy=maker, maker_sell=maker, taker_buy=taker, taker_sell=taker)
  raise ValueError(
    f'Kraken instrument {instrument["symbol"]} has no known fee schedule ({uid})'
  )


def parse_fill(fill: Fill) -> Trade:
  """An own fill from `GET /fills`, which carries no fee."""
  return Trade(
    id=fill['fill_id'],
    order_id=fill['order_id'],
    client_order_id=fill.get('cliOrdId'),
    price=fill['price'],
    qty=signed(fill['side'], fill['size']),
    time=fill['fillTime'],
    maker=fill['fillType'] == 'maker',
    details=fill,
  )


def funding_payment(row: AccountLogEntry) -> FundingPayment | None:
  """A funding settlement from an account log row, received-positive."""
  if (amount := row.get('realized_funding')) is not None and (
    time := row.get('date')
  ) is not None:
    return FundingPayment(amount=amount, time=time)


def total_notional(
  rows: Sequence[OpenPosition], marks: Mapping[str, Decimal]
) -> Decimal:
  """Total position notional at mark prices, entry price where no mark is known."""
  return sum(
    (row['size'] * marks.get(row['symbol'].upper(), row['price']) for row in rows),
    Decimal(0),
  )
