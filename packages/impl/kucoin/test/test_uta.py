"""KuCoin Unified Trading Account (UTA) trading and account reads against fake responses.

The fake rows follow KuCoin's UTA REST V2 and WebSocket V2 documentation examples, in
the shape typed-kucoin returns them: decimal strings as `Decimal`, timestamps as aware
`datetime`. Futures quantities are contracts (`sizeUnit` `UNIT`), spot quantities base
units.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from typing_extensions import Any, AsyncIterator, cast
from typed_core.exceptions import (
  ApiError as TypedApiError,
  BadRequest as TypedBadRequest,
)
from typed_kucoin import KuCoin
from typed_kucoin.schemas import FuturesContract, SpotSymbol

from tribulnation.kucoin import KucoinMarket
from tribulnation.kucoin.market.common import Mode, Shared
from tribulnation.kucoin.market.exchanges import UtaPerpExchange, UtaSpotExchange
from tribulnation.kucoin.market.uta import UtaPerpMarket, UtaSpotMarket
from tribulnation.sdk import (
  ApiError,
  LeverageNotSet,
  MarketSDK,
  OrderNotFound,
  OrderRejected,
  PositionLimitExceeded,
  accounts,
)
from tribulnation.sdk.core import BadRequest
from tribulnation.sdk.market import Order

D = Decimal
NOW = datetime.now(timezone.utc).replace(microsecond=0)
MULTIPLIER = D('0.001')
Row = dict[str, Any]
"""A fake venue row."""


def spot_symbol() -> SpotSymbol:
  """BTC-USDT constraints as `/api/v2/symbols` sends them."""
  return cast(
    SpotSymbol,
    dict(
      symbol='BTC-USDT',
      baseCurrency='BTC',
      quoteCurrency='USDT',
      feeCurrency='USDT',
      enableTrading=True,
      priceIncrement=D('0.1'),
      baseIncrement=D('0.00001'),
      baseMinSize=D('0.00001'),
      baseMaxSize=D('10000'),
      minFunds=D('0.1'),
    ),
  )


def contract(symbol: str = 'XBTUSDTM', settle: str = 'USDT') -> FuturesContract:
  """A linear contract of 0.001 BTC per lot."""
  return cast(
    FuturesContract,
    dict(
      symbol=symbol,
      expireDate=None,
      isInverse=False,
      quoteCurrency=settle,
      settleCurrency=settle,
      multiplier=0.001,
      status='Open',
      lotSize=1,
      tickSize=0.1,
      maxOrderQty=1000000,
    ),
  )


def shared(
  *,
  account: object = None,
  orders: object = None,
  positions: object = None,
  streams: object = None,
  mode: Mode | None = 'unified',
  credentials: object = 'creds',
) -> Shared:
  """A UTA client over fake typed endpoints."""
  client = SimpleNamespace(
    default_client=SimpleNamespace(credentials=credentials),
    uta=SimpleNamespace(account=account, orders=orders, positions=positions),
    streams=streams,
  )
  return Shared(
    client=cast(KuCoin, client),
    spot={'BTC-USDT': spot_symbol()},
    perp={'XBTUSDTM': contract(), 'XBTUSDCM': contract('XBTUSDCM', 'USDC')},
    account_id='kc',
    mode=mode,
  )


def markets(**kwargs: Any) -> tuple[UtaSpotMarket, UtaPerpMarket]:
  """A UTA spot and perpetual market over one fake client."""
  s = shared(**kwargs)
  return (
    UtaSpotMarket(shared=s, symbol='BTC-USDT'),
    UtaPerpMarket(shared=s, symbol='XBTUSDTM', contract_multiplier=MULTIPLIER),
  )


def last_call(mock: AsyncMock) -> Any:
  """The last call a mock was awaited with."""
  assert mock.await_args is not None
  return mock.await_args


def refused(code: str, msg: str = 'refused') -> TypedBadRequest:
  """A KuCoin envelope error as typed-kucoin raises it."""
  return TypedBadRequest(code, msg, {'code': code, 'msg': msg})


def order_row(**fields: Any) -> Row:
  """A UTA order as Get Order Details sends it (the docs' futures example)."""
  row: Row = {
    'tradeType': 'FUTURES',
    'orderId': 'o1',
    'clientOid': 'mine',
    'symbol': 'XBTUSDTM',
    'side': 'BUY',
    'orderType': 'LIMIT',
    'size': D(3),
    'sizeUnit': 'UNIT',
    'price': D('64750'),
    'filledSize': D(0),
    'avgPrice': D(0),
    'fee': D(0),
    'feeCurrency': 'USDT',
    'status': 2,
    'timeInForce': 'GTC',
    'postOnly': True,
    'reduceOnly': False,
    'stp': '',
    'orderTime': NOW,
    'updatedTime': NOW,
  }
  return row | fields


# --- account mode --------------------------------------------------------------------


async def test_mode_is_detected_once_and_selects_the_uta_surfaces():
  """`mode=None` reads the account mode once; a UNIFIED account gets UTA exchanges."""
  mode = AsyncMock(return_value={'selfAccountMode': 'UNIFIED'})
  s = shared(account=SimpleNamespace(mode=mode), mode=None)
  venue = KucoinMarket(shared=s)
  assert isinstance(await venue.exchange('spot'), UtaSpotExchange)
  assert isinstance(await venue.exchange('perp'), UtaPerpExchange)
  names = [e['name'] for e in await venue.exchanges()]
  assert names == ['Unified Spot', 'Unified Linear Perpetuals']
  assert isinstance(await venue.market('perp:XBTUSDTM'), UtaPerpMarket)
  assert mode.await_count == 1


async def test_classic_accounts_public_clients_and_overrides_skip_uta():
  """CLASSIC keeps the Classic surfaces; public clients and an explicit mode never ask."""
  mode = AsyncMock(return_value={'selfAccountMode': 'CLASSIC'})
  venue = KucoinMarket(shared=shared(account=SimpleNamespace(mode=mode), mode=None))
  assert not isinstance(await venue.exchange('spot'), UtaSpotExchange)
  public = KucoinMarket(
    shared=shared(account=SimpleNamespace(mode=mode), mode=None, credentials=None)
  )
  assert not isinstance(await public.exchange('perp'), UtaPerpExchange)
  forced = KucoinMarket(
    shared=shared(account=SimpleNamespace(mode=mode), mode='unified')
  )
  assert isinstance(await forced.exchange('perp'), UtaPerpExchange)
  assert mode.await_count == 1


async def test_market_sdk_passes_the_mode(monkeypatch: pytest.MonkeyPatch):
  """`accounts.Kucoin(mode=...)` reaches the venue; unset, the venue detects it."""
  monkeypatch.setenv('KUCOIN_API_KEY', 'key')
  monkeypatch.setenv('KUCOIN_API_SECRET', 'secret')
  monkeypatch.setenv('KUCOIN_API_PASSPHRASE', 'phrase')
  sdk = MarketSDK({'uta': accounts.Kucoin(mode='unified'), 'auto': accounts.Kucoin()})
  uta = await sdk.venue('uta')
  auto = await sdk.venue('auto')
  assert isinstance(uta, KucoinMarket) and uta.shared.mode == 'unified'
  assert isinstance(auto, KucoinMarket) and auto.shared.mode is None


# --- placement -----------------------------------------------------------------------


async def test_spot_post_only_goes_through_the_unified_endpoint():
  """SPOT, base units, a GTC limit with `postOnly` and the client ID; no margin mode."""
  place = AsyncMock(
    return_value={'tradeType': 'SPOT', 'orderId': 'o1', 'clientOid': 'mine', 'ts': NOW}
  )
  spot, _ = markets(orders=SimpleNamespace(place=place))
  response = await spot.place_order(
    {
      'type': 'POST_ONLY',
      'qty': D('0.0010'),
      'price': D('100.0'),
      'client_order_id': 'mine',
    }
  )
  assert response.id == 'o1' and response.filled_qty is None
  request = last_call(place).args[0]
  assert request == {
    'tradeType': 'SPOT',
    'clientOid': 'mine',
    'symbol': 'BTC-USDT',
    'side': 'BUY',
    'orderType': 'LIMIT',
    'size': D('0.001'),
    'sizeUnit': 'BASECCY',
    'price': D('100'),
    'timeInForce': 'GTC',
    'postOnly': True,
  }
  assert str(request['size']) == '0.001' and str(request['price']) == '100'


async def test_perp_limit_sends_whole_contracts_on_cross_margin():
  """FUTURES orders are contracts (`UNIT`) on CROSS; no leverage is sent."""
  place = AsyncMock(return_value={'tradeType': 'FUTURES', 'orderId': 'p1'})
  _, perp = markets(orders=SimpleNamespace(place=place))
  await perp.place_order({'type': 'LIMIT', 'qty': D('-0.003'), 'price': D('64750')})
  request = last_call(place).args[0]
  assert (
    request['tradeType'],
    request['side'],
    request['size'],
    request['sizeUnit'],
  ) == (
    'FUTURES',
    'SELL',
    D(3),
    'UNIT',
  )
  assert request['marginMode'] == 'CROSS' and 'leverage' not in request
  assert 'postOnly' not in request and len(request['clientOid']) == 32
  with pytest.raises(ValueError):
    await perp.place_order({'type': 'LIMIT', 'qty': D('0.0005'), 'price': D('64750')})


async def test_market_orders_are_ioc_and_read_back_once():
  """MARKET is an IOC limit; done with nothing filled is refused, else the fill counts."""
  place = AsyncMock(return_value={'tradeType': 'FUTURES', 'orderId': 'p2'})
  detail = AsyncMock(
    side_effect=[
      order_row(orderId='p2', status=5, filledSize=D(0)),
      order_row(orderId='p2', status=6, filledSize=D(2)),
      TypedApiError('500000', 'busy', {'code': '500000'}),
    ]
  )
  _, perp = markets(orders=SimpleNamespace(place=place, detail=detail))
  order: Order = {'type': 'MARKET', 'qty': D('0.003'), 'price': D('65000')}
  with pytest.raises(OrderRejected):
    await perp.place_order(order)
  assert last_call(place).args[0]['timeInForce'] == 'IOC'
  assert (await perp.place_order(order)).filled_qty == D('0.002')
  assert (await perp.place_order(order)).filled_qty is None
  assert last_call(detail).kwargs == {'symbol': 'XBTUSDTM', 'order_id': 'p2'}


@pytest.mark.parametrize(
  ('error', 'expected'),
  [
    (refused('116355', 'Insufficient funds.'), OrderRejected),
    (
      refused('116239', 'Positions have reached the system risk limit.'),
      PositionLimitExceeded,
    ),
    (refused('116217', 'Maximum risk limit exceeded.'), PositionLimitExceeded),
    (TypedApiError('500000', 'Server busy', {'code': '500000'}), ApiError),
    (TypedApiError('111209', 'Network busy', {'code': '111209'}), ApiError),
    (refused('116104', 'Please switch to Unified Account mode.'), ApiError),
  ],
)
async def test_placement_errors_map_to_sdk_types(
  error: Exception, expected: type[Exception]
):
  """Definitive codes are refusals; busy, timeout and account-mode answers are not."""
  place = AsyncMock(side_effect=error)
  spot, _ = markets(orders=SimpleNamespace(place=place))
  with pytest.raises(expected) as caught:
    await spot.place_order({'type': 'LIMIT', 'qty': D(1), 'price': D(100)})
  if expected is ApiError:
    assert not isinstance(caught.value, OrderRejected)


async def test_batch_placement_sends_each_order_alone():
  """UTA REST has no batch placement: one request per order, one result per order."""
  place = AsyncMock(
    side_effect=[
      {'tradeType': 'SPOT', 'orderId': 'a'},
      refused('116355', 'Insufficient funds.'),
    ]
  )
  spot, _ = markets(orders=SimpleNamespace(place=place))
  results = await spot.place_orders(
    [
      {'type': 'LIMIT', 'qty': D(1), 'price': D(100)},
      {'type': 'LIMIT', 'qty': D(1), 'price': D(100)},
      {'type': 'LIMIT', 'qty': D(1), 'price': D('100.05')},
    ]
  )
  assert [type(r).__name__ for r in results] == [
    'OrderResponse',
    'OrderRejected',
    'ValueError',
  ]
  assert place.await_count == 2


# --- cancels and queries -------------------------------------------------------------


async def test_cancels_report_missing_orders():
  """`110179` and friends are OrderNotFound; batches answer per order; cancel-all loops."""
  cancel = AsyncMock(
    side_effect=[
      {'tradeType': 'SPOT', 'orderId': 'o1'},
      refused('110179', 'Order not found.'),
    ]
  )
  batch_cancel = AsyncMock(
    return_value={
      'tradeType': 'FUTURES',
      'items': [
        {'code': '200000', 'msg': 'success', 'orderId': 'a', 'ts': NOW},
        {'code': '116101', 'msg': 'Order ID not found.', 'orderId': 'b'},
        {'code': '116050', 'msg': 'Order cancellation in progress.', 'orderId': 'c'},
      ],
    }
  )
  cancel_all = AsyncMock(
    side_effect=[
      {'tradeType': 'FUTURES', 'items': [{'orderId': str(i)} for i in range(100)]},
      {'tradeType': 'FUTURES', 'items': [{'orderId': 'x'}]},
    ]
  )
  spot, perp = markets(
    orders=SimpleNamespace(
      cancel=cancel, batch_cancel=batch_cancel, cancel_all=cancel_all
    )
  )
  await spot.cancel_order('o1')
  assert last_call(cancel).args == ('SPOT',)
  assert last_call(cancel).kwargs == {'symbol': 'BTC-USDT', 'order_id': 'o1'}
  with pytest.raises(OrderNotFound):
    await spot.cancel_order('o1')
  ok, missing, other = await perp.cancel_orders(['a', 'b', 'c'])
  assert isinstance(missing, OrderNotFound) and isinstance(other, BadRequest)
  assert not isinstance(ok, Exception)
  assert last_call(batch_cancel).kwargs['cancel_order_list'][0] == {
    'symbol': 'XBTUSDTM',
    'orderId': 'a',
  }
  await perp.cancel_open_orders()
  assert cancel_all.await_count == 2
  assert last_call(cancel_all).kwargs == {
    'symbol': 'XBTUSDTM',
    'order_filter': 'NORMAL',
  }


async def test_order_states_use_signed_base_units():
  """Contracts convert to base units; status decides `active`; unknown IDs are None."""
  detail = AsyncMock(
    side_effect=[
      order_row(side='SELL', size=D(3), filledSize=D(1), status=4),
      order_row(status=5),
      order_row(symbol='ETHUSDTM'),
      refused('110179', 'Order not found.'),
    ]
  )
  open_orders = AsyncMock(
    side_effect=[
      {
        'tradeType': 'SPOT',
        'items': [order_row(symbol='BTC-USDT', size=D('0.5'), price='')] * 200,
      },
      {'tradeType': 'SPOT', 'items': [order_row(symbol='BTC-USDT', size=D('0.5'))]},
    ]
  )
  spot, perp = markets(orders=SimpleNamespace(detail=detail, open_orders=open_orders))
  state = await perp.query_order('o1')
  assert state is not None and state.active
  assert (state.qty, state.filled_qty, state.price) == (
    D('-0.003'),
    D('-0.001'),
    D('64750'),
  )
  done = await perp.query_order('o1')
  assert done is not None and not done.active
  assert await perp.query_order('o1') is None
  assert await perp.query_order('gone') is None
  rows = await spot.open_orders()
  assert len(rows) == 201 and rows[0].qty == D('0.5') and rows[0].price == 0
  assert last_call(open_orders).kwargs['page_number'] == 2


# --- account reads -------------------------------------------------------------------


async def test_fees_pass_rebates_through():
  """The fee-rate endpoint's negative maker rate is a rebate."""
  fee_rate = AsyncMock(
    return_value={
      'tradeType': 'FUTURES',
      'list': [
        {
          'symbol': 'XBTUSDTM',
          'makerFeeRate': D('-0.0001'),
          'takerFeeRate': D('0.0004'),
        }
      ],
    }
  )
  _, perp = markets(account=SimpleNamespace(fee_rate=fee_rate))
  fees = await perp.fees()
  assert (fees.maker_buy, fees.taker_sell) == (D('-0.0001'), D('0.0004'))
  assert last_call(fee_rate).args == ('FUTURES',)


async def test_spot_balances_count_only_futures_losses():
  """`free` is `min(balance, equity) - hold`: losses reduce it, profits do not add."""
  balance = AsyncMock(
    return_value={
      'accountType': 'UNIFIED',
      'accounts': [
        {
          'currencies': [
            {
              'currency': 'USDT',
              'balance': D(1000),
              'equity': D(950),
              'hold': D(100),
              'available': D(850),
              'liability': D(0),
            },
            {
              'currency': 'BTC',
              'balance': D('0.5'),
              'equity': D('0.6'),
              'hold': D('0.1'),
              'available': D('0.5'),
              'liability': D(0),
            },
          ]
        }
      ],
    }
  )
  s = shared(account=SimpleNamespace(balance=balance))
  spot = UtaSpotMarket(shared=s, symbol='BTC-USDT')
  balances = await spot.balances()
  assert (balances.quote.total, balances.quote.free) == (D(1000), D(850))
  assert (balances.base.total, balances.base.free) == (D('0.5'), D('0.4'))
  eth = await UtaSpotExchange(shared=s).balance('ETH', ttl=timedelta(seconds=5))
  assert (eth.total, eth.free) == (0, 0)


def position(**fields: Any) -> Row:
  """An open UTA position, the docs' example shape."""
  row: Row = {
    'symbol': 'XBTUSDTM',
    'id': '1',
    'marginMode': 'CROSS',
    'size': D(-5),
    'entryPrice': D(100000),
    'positionValue': D('-500'),
    'positionMargin': D(50),
    'markPrice': D(100000),
    'leverage': D(10),
    'unrealizedPnL': D(-2),
    'realizedPnL': D(0),
    'initialMargin': D(50),
    'mmr': D('0.005'),
    'maintenanceMargin': D('2.5'),
    'liquidationPrice': D(150000),
  }
  return row | fields


OVERVIEW: Row = {
  'accountType': 'UNIFIED',
  'riskRatio': D('0.01'),
  'equity': D(1010),
  'liability': D(0),
  'availableMargin': D(950),
  'adjustedEquity': D(1000),
  'im': D(50),
  'mm': D('2.5'),
}


async def test_positions_and_the_unified_pool():
  """Contracts to base units; the pool is the overview's adjusted equity and margins."""
  open_positions = AsyncMock(return_value=[position()])
  overview = AsyncMock(return_value=OVERVIEW)
  s = shared(
    account=SimpleNamespace(overview=overview),
    positions=SimpleNamespace(open_positions=open_positions),
  )
  perp = UtaPerpMarket(shared=s, symbol='XBTUSDTM', contract_multiplier=MULTIPLIER)
  pos = await perp.perp_position()
  assert (pos.size, pos.entry_price, pos.liquidation_price) == (
    D('-0.005'),
    D(100000),
    D(150000),
  )
  pool = await perp.perp_collateral(ttl=timedelta(seconds=5))
  assert (
    pool.equity,
    pool.free_collateral,
    pool.initial_margin,
    pool.maintenance_margin,
  ) == (
    D(1000),
    D(950),
    D(50),
    D('2.5'),
  )
  assert pool.leverage == D('0.5') and pool.margin_mode == 'cross'
  assert (
    await UtaPerpExchange(shared=s).perp_collateral(ttl=timedelta(seconds=5)) == pool
  )
  assert open_positions.await_count == 1 and overview.await_count == 1
  usdc = UtaPerpMarket(shared=s, symbol='XBTUSDCM', contract_multiplier=MULTIPLIER)
  assert await perp.collateral_id() == await usdc.collateral_id() == 'kc:perp'
  flat = await usdc.perp_position(ttl=timedelta(seconds=5))
  assert flat.size == 0


async def test_isolated_positions_have_their_own_bucket():
  """An isolated position reports its margin plus unrealized PnL."""
  open_positions = AsyncMock(
    return_value=[position(marginMode='ISOLATED', liquidationPrice='')]
  )
  _, perp = markets(positions=SimpleNamespace(open_positions=open_positions))
  bucket = await perp.perp_collateral()
  assert (bucket.equity, bucket.free_collateral, bucket.maintenance_margin) == (
    D(48),
    D(0),
    D('2.5'),
  )
  assert bucket.margin_mode == 'isolated'
  assert (await perp.perp_position()).liquidation_price is None


async def test_leverage_reads_and_sets_the_contract_setting():
  """Cross leverage per contract; none reported is LeverageNotSet; set forgets the cache."""
  leverage = AsyncMock(
    side_effect=[
      [{'symbol': 'XBTUSDTM', 'leverage': D(5), 'marginMode': 'CROSS'}],
      [{'symbol': 'XBTUSDTM', 'leverage': D(3), 'marginMode': 'ISOLATE'}],
    ]
  )
  modify = AsyncMock(return_value={'code': '200000', 'leverage': D('7.00')})
  overview = AsyncMock(return_value=OVERVIEW)
  open_positions = AsyncMock(return_value=[])
  _, perp = markets(
    account=SimpleNamespace(
      leverage=leverage, modify_leverage=modify, overview=overview
    ),
    positions=SimpleNamespace(open_positions=open_positions),
  )
  assert await perp.leverage() == 5
  assert await perp.available_notional(ttl=timedelta(seconds=5)) == D(950) * 5
  assert last_call(leverage).kwargs == {'symbol': 'XBTUSDTM', 'margin_mode': 'CROSS'}
  with pytest.raises(LeverageNotSet):
    await perp.leverage()
  await perp.set_leverage(D(7))
  assert last_call(modify).args == ('XBTUSDTM',) and last_call(modify).kwargs == {
    'leverage': 7
  }
  with pytest.raises(ValueError):
    await perp.set_leverage(D('2.5'))
  modify.return_value = {}
  with pytest.raises(ApiError):
    await perp.set_leverage(D(2))


# --- history -------------------------------------------------------------------------


def pager(*pages: list[Row]):
  """A typed pager whose `.via(call)` yields fixed pages, recording its arguments."""
  calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

  def paged(*args: Any, **kwargs: Any):
    """Record one window's request."""
    calls.append((args, kwargs))

    async def walk() -> AsyncIterator[list[Row]]:
      """Yield the fixed pages for this window."""
      for page in pages:
        yield page

    return SimpleNamespace(via=lambda call: walk())  # pyright: ignore[reportUnknownLambdaType]

  return paged, calls


def fill(**fields: Any) -> Row:
  """A UTA fill as Get Trade History sends it (the docs' futures example)."""
  row: Row = {
    'tradeType': 'FUTURES',
    'orderId': 'p',
    'symbol': 'XBTUSDTM',
    'orderType': 'LIMIT',
    'side': 'SELL',
    'tradeId': 't1',
    'size': D(4),
    'price': D('78430.6'),
    'value': D('313.7224'),
    'executionTime': NOW - timedelta(days=1),
    'fee': D('-0.01'),
    'feeCurrency': 'USDT',
    'liquidityRole': 'MAKER',
    'fillType': 'NORMAL',
    'clientOid': '',
  }
  return row | fields


async def test_trade_history_walks_windows_and_skips_settlements():
  """Seven-day windows by cursor; settlement rows and repeats are dropped."""
  paged, calls = pager(
    [
      fill(),
      fill(tradeId='t2', fillType='SETTLEMENT'),
      fill(tradeId='t3', fillType='ADL'),
    ],
    [fill()],
  )
  _, perp = markets(orders=SimpleNamespace(trade_history_paged=paged))
  start = NOW - timedelta(days=10)
  trades = [t async for page in perp.trades_history(start, NOW) for t in page]
  assert len(calls) == 2 and calls[0][0] == ('FUTURES',)
  assert calls[0][1]['end_at'] - calls[0][1]['start_at'] < timedelta(days=7)
  assert [t.id for t in trades] == ['t1', 't3']
  first = trades[0]
  assert first.qty == D('-0.004') and first.maker and first.client_order_id is None
  assert first.fee is not None and first.fee.amount == D('-0.01')
  with pytest.raises(ValueError):
    perp.trades_history(start.replace(tzinfo=None), NOW)


async def test_funding_payments_walk_90_day_windows():
  """Settled funding by cursor; positive was received; other symbols and rows outside
  a window are dropped."""
  inside = NOW - timedelta(hours=8)
  paged, calls = pager(
    [
      {
        'symbol': 'XBTUSDTM',
        'fundingFee': D('0.0547'),
        'settleCurrency': 'USDT',
        'settlementTime': inside,
      },
      {
        'symbol': 'ETHUSDTM',
        'fundingFee': D('1'),
        'settleCurrency': 'USDT',
        'settlementTime': inside,
      },
    ]
  )
  _, perp = markets(positions=SimpleNamespace(funding_history_paged=paged))
  rows = [
    p
    async for page in perp.funding_payments(NOW - timedelta(days=100), NOW)
    for p in page
  ]
  assert len(calls) == 2 and calls[0][1]['symbol'] == 'XBTUSDTM'
  assert [(p.amount, p.time) for p in rows] == [(D('0.0547'), inside)]


# --- streams -------------------------------------------------------------------------


class FakeStream:
  """A typed private subscription: pushes from a queue."""

  def __init__(self):
    self.queue: asyncio.Queue[Row] = asyncio.Queue()
    self.unsubscribed = False

  def __aiter__(self):
    return self

  async def __anext__(self) -> Row:
    return await self.queue.get()

  async def unsubscribe(self):
    """Record the unsubscribe."""
    self.unsubscribed = True


def execution(**fields: Any) -> Row:
  """A push of the UTA `execution` channel (the docs' example)."""
  row: Row = {
    'oi': 'o1',
    'ci': 'mine',
    's': 'BTC-USDT',
    'S': 'BUY',
    'oT': 'LIMIT',
    'p': D(100),
    'q': D('0.1'),
    'ti': 22221471895799808,
    'E': NOW,
    'lR': 'MAKER',
    'f': D('-0.00001'),
    'fC': 'USDT',
    'fT': 'NORMAL',
  }
  return row | fields


async def test_one_execution_feed_serves_spot_and_perp_fills():
  """One UTA connection; each market keeps its symbol's fills, with fees, in base units."""
  stream = FakeStream()
  connect = AsyncMock(return_value=stream)
  spot, perp = markets(
    streams=SimpleNamespace(uta_private=SimpleNamespace(execution=connect))
  )
  async with spot.trades_stream() as spot_fills, perp.trades_stream() as perp_fills:
    stream.queue.put_nowait(execution(s='ETH-USDT'))
    stream.queue.put_nowait(execution())
    stream.queue.put_nowait(execution(s='XBTUSDTM', fT='SETTLEMENT', q=D(9)))
    stream.queue.put_nowait(
      execution(s='XBTUSDTM', S='SELL', q=D(5), lR='TAKER', ti='t9', ci='')
    )
    got = await asyncio.wait_for(anext(aiter(spot_fills)), 1)
    assert (got.qty, got.price, got.maker, got.id) == (
      D('0.1'),
      D(100),
      True,
      '22221471895799808',
    )
    assert (
      got.client_order_id == 'mine'
      and got.fee is not None
      and got.fee.amount == D('-0.00001')
    )
    perp_fill = await asyncio.wait_for(anext(aiter(perp_fills)), 1)
    assert (perp_fill.qty, perp_fill.maker, perp_fill.client_order_id) == (
      D('-0.005'),
      False,
      None,
    )
  assert connect.await_count == 1 and stream.unsubscribed
