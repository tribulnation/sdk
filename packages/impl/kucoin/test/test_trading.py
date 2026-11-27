"""KuCoin trading and account reads against recorded-shape fake responses.

Every fake row carries the fields the adapter reads, in the units the venue sends them:
spot quantities in base units, futures quantities in contracts (lots).
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
  NetworkError as TypedNetworkError,
  RateLimited as TypedRateLimited,
)
from typed_kucoin import KuCoin
from typed_kucoin.schemas import FuturesContract, SpotSymbol

from tribulnation.kucoin import KucoinMarket, retry_after
from tribulnation.kucoin.market.common import Shared
from tribulnation.kucoin.market.exchanges import LinearPerpExchange, SpotExchange
from tribulnation.kucoin.market.orders import lots, native_order
from tribulnation.kucoin.market.perp import LinearPerpMarket
from tribulnation.kucoin.market.spot import SpotMarket
from tribulnation.sdk import (
  ApiError,
  MarketSDK,
  NetworkError,
  OrderNotFound,
  OrderRejected,
  PositionLimitExceeded,
  RateLimited,
  accounts,
)
from tribulnation.sdk.core import BadRequest
from tribulnation.sdk.market import Order, OrderResponse

D = Decimal
NOW = datetime.now(timezone.utc).replace(microsecond=0)
MULTIPLIER = D('0.001')


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
  """A linear contract of 0.001 BTC per lot, as `/api/v1/contracts/active` sends it."""
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


def market_pair(
  *,
  spot: object = None,
  futures: object = None,
  account: object = None,
  streams: object = None,
  futures_api: object = None,
) -> tuple[SpotMarket, LinearPerpMarket]:
  """A spot and a perpetual market over one fake client."""
  shared = Shared(
    client=cast(
      KuCoin,
      SimpleNamespace(spot=spot, futures=futures, account=account, streams=streams),
    ),
    spot={'BTC-USDT': spot_symbol()},
    perp={'XBTUSDTM': contract(), 'XBTUSDCM': contract('XBTUSDCM', 'USDC')},
    account_id='kc',
  )
  vars(shared)['futures_api'] = futures_api
  return (
    SpotMarket(shared=shared, symbol='BTC-USDT'),
    LinearPerpMarket(shared=shared, symbol='XBTUSDTM', contract_multiplier=MULTIPLIER),
  )


Row = dict[str, Any]
"""A fake venue row."""


def sent(mock: AsyncMock) -> Any:
  """The last call a mock was awaited with."""
  assert mock.await_args is not None
  return mock.await_args


def refused(code: str, msg: str = 'refused') -> TypedBadRequest:
  """A KuCoin envelope error as typed-kucoin raises it."""
  return TypedBadRequest(code, msg, {'code': code, 'msg': msg})


# --- validation and lot conversion -------------------------------------------------


async def test_orders_are_checked_on_the_grid_before_anything_is_sent():
  """Off-grid, undersized or partial-lot orders raise ValueError without a request."""
  add = AsyncMock()
  spot, perp = market_pair(
    spot=SimpleNamespace(orders_hf=SimpleNamespace(add_sync=add)),
    futures=SimpleNamespace(orders=SimpleNamespace(add=add)),
  )
  bad: list[tuple[SpotMarket | LinearPerpMarket, Order]] = [
    (spot, {'type': 'LIMIT', 'qty': D('0.000015'), 'price': D(100)}),
    (spot, {'type': 'LIMIT', 'qty': D('0.001'), 'price': D('100.05')}),
    (spot, {'type': 'LIMIT', 'qty': D('0.00001'), 'price': D(100)}),
    (spot, {'type': 'LIMIT', 'qty': D(0), 'price': D(100)}),
    (perp, {'type': 'POST_ONLY', 'qty': D('0.0015'), 'price': D(100)}),
    (perp, {'type': 'POST_ONLY', 'qty': D('0.001'), 'price': D(-1)}),
  ]
  for market, order in bad:
    with pytest.raises(ValueError):
      await market.place_order(order)
  add.assert_not_awaited()


async def test_lots_convert_base_units_exactly():
  """Base quantities map to whole contracts; anything else is refused."""
  assert lots(D('0.003'), MULTIPLIER) == 3
  assert lots(D('20'), D(10)) == 2
  with pytest.raises(ValueError):
    lots(D('0.0035'), MULTIPLIER)
  _, perp = market_pair()
  native = native_order(
    {'type': 'MARKET', 'qty': D('-0.25'), 'price': D('99.9')}, await perp.rules()
  )
  assert (native.side, native.qty, native.time_in_force) == ('sell', D('0.25'), 'IOC')
  assert len(native.client_oid) == 32


# --- spot placement ----------------------------------------------------------------


async def test_spot_post_only_is_sent_synchronously_with_its_client_id():
  """POST_ONLY sets `postOnly` on a GTC limit; the sync answer reports the fill state."""
  add = AsyncMock(
    return_value={
      'orderId': 'o1',
      'clientOid': 'mine',
      'status': 'open',
      'dealSize': D(0),
      'canceledSize': D(0),
    }
  )
  spot, _ = market_pair(spot=SimpleNamespace(orders_hf=SimpleNamespace(add_sync=add)))
  response = await spot.place_order(
    {
      'type': 'POST_ONLY',
      'qty': D('0.0010'),
      'price': D('100.0'),
      'client_order_id': 'mine',
    }
  )
  assert response.id == 'o1' and response.filled_qty == 0
  request = sent(add).args[0]
  assert request == {
    'clientOid': 'mine',
    'symbol': 'BTC-USDT',
    'type': 'limit',
    'side': 'buy',
    'price': D('100'),
    'size': D('0.001'),
    'timeInForce': 'GTC',
    'postOnly': True,
  }
  assert str(request['price']) == '100' and str(request['size']) == '0.001'


async def test_spot_crossing_post_only_and_unmatched_ioc_are_rejected():
  """A sync answer `done` with nothing dealt means nothing rests: OrderRejected."""
  add = AsyncMock(
    return_value={
      'orderId': 'o2',
      'status': 'done',
      'dealSize': D(0),
      'canceledSize': D(1),
    }
  )
  spot, _ = market_pair(spot=SimpleNamespace(orders_hf=SimpleNamespace(add_sync=add)))
  with pytest.raises(OrderRejected):
    await spot.place_order({'type': 'POST_ONLY', 'qty': D(1), 'price': D(100)})
  with pytest.raises(OrderRejected):
    await spot.place_order({'type': 'MARKET', 'qty': D(-1), 'price': D(90)})
  assert sent(add).args[0]['timeInForce'] == 'IOC'
  assert sent(add).args[0]['side'] == 'sell'


async def test_spot_market_order_reports_what_filled():
  """MARKET is an IOC limit at the protection price; `dealSize` is its fill."""
  add = AsyncMock(
    return_value={
      'orderId': 'o3',
      'status': 'done',
      'dealSize': D('0.5'),
      'canceledSize': D('0.5'),
    }
  )
  spot, _ = market_pair(spot=SimpleNamespace(orders_hf=SimpleNamespace(add_sync=add)))
  response = await spot.place_order({'type': 'MARKET', 'qty': D(1), 'price': D(101)})
  assert response.filled_qty == D('0.5')


@pytest.mark.parametrize(
  ('error', 'expected'),
  [
    (refused('400100', 'Order size below the minimum requirement.'), OrderRejected),
    (refused('200004', 'Balance insufficient'), OrderRejected),
    (refused('126042', 'Exceeded maximum position limit'), PositionLimitExceeded),
    (TypedApiError('500000', 'Internal Server Error', {'code': '500000'}), ApiError),
    (TypedApiError(502, 'Bad Gateway'), ApiError),
    (TypedNetworkError('timeout'), NetworkError),
  ],
)
async def test_placement_errors_map_to_sdk_types(
  error: Exception, expected: type[Exception]
):
  """Definitive codes are OrderRejected; ambiguous ones stay ApiError/NetworkError."""
  add = AsyncMock(side_effect=error)
  spot, _ = market_pair(spot=SimpleNamespace(orders_hf=SimpleNamespace(add_sync=add)))
  with pytest.raises(expected) as caught:
    await spot.place_order({'type': 'LIMIT', 'qty': D(1), 'price': D(100)})
  if expected is ApiError:
    assert not isinstance(caught.value, OrderRejected)


async def test_spot_batch_answers_each_order():
  """Invalid orders never leave; KuCoin's per-order failures become OrderRejected."""
  batch = AsyncMock(
    return_value=[
      {
        'orderId': 'a',
        'clientOid': 'x',
        'success': True,
        'status': 'open',
        'dealSize': D(0),
      },
      {
        'orderId': '',
        'clientOid': 'y',
        'success': False,
        'failMsg': 'Balance insufficient',
      },
    ]
  )
  spot, _ = market_pair(
    spot=SimpleNamespace(orders_hf=SimpleNamespace(batch_add_sync=batch))
  )
  results = await spot.place_orders(
    [
      {'type': 'POST_ONLY', 'qty': D(1), 'price': D(100)},
      {'type': 'LIMIT', 'qty': D(1), 'price': D('100.01')},
      {'type': 'LIMIT', 'qty': D(2), 'price': D(100)},
    ]
  )
  assert isinstance(results[0], OrderResponse) and results[0].id == 'a'
  assert isinstance(results[1], ValueError)
  assert isinstance(results[2], OrderRejected)
  assert len(sent(batch).args[0]) == 2


# --- futures placement -------------------------------------------------------------


async def test_perp_limit_sends_lots_cross_margin_and_the_cross_leverage():
  """Base quantities become contracts; the symbol's cross leverage goes with the order."""
  add = AsyncMock(return_value={'orderId': 'f1', 'clientOid': 'c'})
  read_leverage = AsyncMock(return_value={'symbol': 'XBTUSDTM', 'leverage': D('5')})
  _, perp = market_pair(
    futures=SimpleNamespace(
      orders=SimpleNamespace(add=add),
      positions=SimpleNamespace(get_cross_margin_leverage=read_leverage),
    )
  )
  response = await perp.place_order(
    {'type': 'POST_ONLY', 'qty': D('-0.003'), 'price': D('100.1')}
  )
  await perp.place_order({'type': 'LIMIT', 'qty': D('0.001'), 'price': D(100)})
  assert response.id == 'f1' and response.filled_qty is None
  request = add.await_args_list[0].args[0]
  assert request['size'] == 3 and request['side'] == 'sell'
  assert request['leverage'] == 5 and request['marginMode'] == 'CROSS'
  assert request['postOnly'] is True and request['timeInForce'] == 'GTC'
  assert 'postOnly' not in add.await_args_list[1].args[0]
  read_leverage.assert_awaited_once()


async def test_perp_market_order_is_read_back_once():
  """An IOC is read back: done with fills reports them, done without is refused."""
  add = AsyncMock(return_value={'orderId': 'f2', 'clientOid': 'c'})
  get = AsyncMock(
    side_effect=[
      {'id': 'f2', 'symbol': 'XBTUSDTM', 'status': 'done', 'filledSize': 7},
      {'id': 'f2', 'symbol': 'XBTUSDTM', 'status': 'done', 'filledSize': 0},
      TypedBadRequest('100001', 'error.getOrder.orderNotExist', {'code': '100001'}),
    ]
  )
  _, perp = market_pair(
    futures=SimpleNamespace(orders=SimpleNamespace(add=add, get_by_order_id=get))
  )
  perp.shared.leverages['XBTUSDTM'] = 3
  order: Order = {'type': 'MARKET', 'qty': D('0.01'), 'price': D(105)}
  assert (await perp.place_order(order)).filled_qty == D('0.007')
  with pytest.raises(OrderRejected):
    await perp.place_order(order)
  assert (await perp.place_order(order)).filled_qty is None
  assert sent(add).args[0]['timeInForce'] == 'IOC'


async def test_perp_batch_placement_maps_item_codes():
  """Each batch item's own code decides its result."""
  batch = AsyncMock(
    return_value=[
      {
        'orderId': 'a',
        'clientOid': 'x',
        'symbol': 'XBTUSDTM',
        'code': '200000',
        'msg': '',
      },
      {
        'orderId': '',
        'clientOid': 'y',
        'symbol': 'XBTUSDTM',
        'code': '300003',
        'msg': 'Balance not enough',
      },
    ]
  )
  _, perp = market_pair(
    futures=SimpleNamespace(orders=SimpleNamespace(batch_add=batch))
  )
  perp.shared.leverages['XBTUSDTM'] = 2
  results = await perp.place_orders(
    [
      {'type': 'POST_ONLY', 'qty': D('0.002'), 'price': D(100)},
      {'type': 'POST_ONLY', 'qty': D('0.002'), 'price': D(101)},
      {'type': 'POST_ONLY', 'qty': D('0.0025'), 'price': D(101)},
    ]
  )
  assert isinstance(results[0], OrderResponse)
  assert isinstance(results[1], OrderRejected)
  assert isinstance(results[2], ValueError)
  assert [r['size'] for r in sent(batch).args[0]] == [2, 2]


# --- cancel, query, open orders ----------------------------------------------------


async def test_cancels_report_missing_orders():
  """Spot's `400100` order-not-exist message and futures' `100001` are OrderNotFound."""
  spot_cancel = AsyncMock(
    side_effect=refused('400100', 'order_not_exist_or_not_allow_to_cancel')
  )
  perp_cancel = AsyncMock(
    side_effect=refused('100004', 'Order is in not cancelable state')
  )
  spot, perp = market_pair(
    spot=SimpleNamespace(
      orders_hf=SimpleNamespace(cancel_by_order_id_sync=spot_cancel)
    ),
    futures=SimpleNamespace(orders=SimpleNamespace(cancel_by_order_id=perp_cancel)),
  )
  with pytest.raises(OrderNotFound):
    await spot.cancel_order('o1')
  with pytest.raises(OrderNotFound):
    await perp.cancel_order('f1')
  assert sent(spot_cancel).kwargs == {'order_id': 'o1', 'symbol': 'BTC-USDT'}
  spot_cancel.side_effect = refused('400100', 'symbol suspended')
  with pytest.raises(BadRequest) as caught:
    await spot.cancel_order('o1')
  assert not isinstance(caught.value, OrderNotFound)


async def test_replace_cancels_then_places():
  """No native amend is used: replace is cancel plus place, a gone order tolerated."""
  cancel = AsyncMock(side_effect=refused('126043', 'Order does not exist'))
  add = AsyncMock(return_value={'orderId': 'new', 'status': 'open', 'dealSize': D(0)})
  spot, _ = market_pair(
    spot=SimpleNamespace(
      orders_hf=SimpleNamespace(cancel_by_order_id_sync=cancel, add_sync=add)
    )
  )
  response = await spot.replace_order(
    'old', {'type': 'POST_ONLY', 'qty': D(1), 'price': D(99)}
  )
  assert response.id == 'new'


async def test_futures_batch_cancel_reports_each_order():
  """Batches of ten; per-item codes become acknowledgements or errors."""
  calls: list[list[str]] = []

  async def batch_cancel(ids: list[str]) -> list[Row]:
    """Answer the first id as cancelled and the rest as missing."""
    calls.append(ids)
    return [
      {
        'orderId': i,
        'clientOid': None,
        'code': '200000' if n == 0 else '100001',
        'msg': '',
      }
      for n, i in enumerate(ids)
    ]

  _, perp = market_pair(
    futures=SimpleNamespace(orders=SimpleNamespace(batch_cancel=batch_cancel))
  )
  results = await perp.cancel_orders([str(i) for i in range(12)])
  assert [len(c) for c in calls] == [10, 2]
  assert isinstance(results[0], dict)
  assert isinstance(results[1], OrderNotFound)
  assert isinstance(results[10], dict)


async def test_cancel_open_orders_is_one_symbol_scoped_request():
  """Both lines cancel every open order of the symbol natively."""
  spot_all = AsyncMock(return_value='success')
  perp_all = AsyncMock(return_value={'cancelledOrderIds': ['a']})
  spot, perp = market_pair(
    spot=SimpleNamespace(orders_hf=SimpleNamespace(cancel_all_by_symbol=spot_all)),
    futures=SimpleNamespace(orders=SimpleNamespace(cancel_all=perp_all)),
  )
  await spot.cancel_open_orders()
  await perp.cancel_open_orders()
  spot_all.assert_awaited_once_with('BTC-USDT')
  perp_all.assert_awaited_once_with('XBTUSDTM')


def hf_order_json(**fields: object) -> dict[str, object]:
  """A spot HF order as `/api/v1/hf/orders/{orderId}` sends it, before validation."""
  row: dict[str, object] = {
    'id': 's1',
    'symbol': 'BTC-USDT',
    'opType': 'DEAL',
    'type': 'limit',
    'side': 'buy',
    'price': '100',
    'size': '1',
    'funds': '0',
    'dealSize': '0',
    'dealFunds': '0',
    'fee': '0',
    'feeCurrency': 'USDT',
    'stp': None,
    'timeInForce': 'GTC',
    'postOnly': False,
    'hidden': False,
    'iceberg': False,
    'visibleSize': '0',
    'cancelAfter': 0,
    'channel': 'API',
    'clientOid': 'c1',
    'remark': None,
    'tags': None,
    'cancelExist': False,
    'createdAt': 1764000000000,
    'lastUpdatedAt': 1764000000000,
    'tradeType': 'TRADE',
    'inOrderBook': True,
    'cancelledSize': '0',
    'cancelledFunds': '0',
    'remainSize': '0',
    'remainFunds': '0',
    'tax': '0',
    'cancelReason': None,
    'active': True,
  }
  return row | fields


async def test_order_states_use_signed_base_units():
  """Open orders and queries are signed; futures lots convert, other symbols are None.

  A spot query KuCoin answers with `data: null` (an unknown order ID, seen live) is
  `None`, not a validation error.
  """
  spot_row = hf_order_json(id='s1', side='sell', price='100', size='2', dealSize='0.5')
  perp_row: Row = {
    'id': 'p1',
    'symbol': 'XBTUSDTM',
    'side': 'buy',
    'price': D(100),
    'size': 10,
    'filledSize': 4,
    'isActive': True,
  }

  async def order_pages() -> AsyncIterator[list[Row]]:
    """One page of active futures orders."""
    yield [perp_row]

  def order_list(status: str, symbol: str) -> SimpleNamespace:
    """The typed active-order pager."""
    return SimpleNamespace(via=lambda call: order_pages())  # pyright: ignore[reportUnknownLambdaType]

  spot, perp = market_pair(
    spot=SimpleNamespace(
      orders_hf=SimpleNamespace(
        get_open_orders=AsyncMock(return_value=None),
        get_by_order_id=AsyncMock(
          side_effect=[spot_row, None, spot_row | {'symbol': 'ETH-USDT'}]
        ),
      )
    ),
    futures=SimpleNamespace(
      orders=SimpleNamespace(
        get_order_list_paged=order_list,
        get_by_order_id=AsyncMock(
          side_effect=[
            perp_row,
            perp_row | {'symbol': 'ETHUSDTM'},
            refused('100001', 'error.getOrder.orderNotExist'),
          ]
        ),
      )
    ),
  )
  assert await spot.open_orders() == []
  state = await spot.query_order('s1')
  assert state is not None and (state.qty, state.filled_qty) == (D(-2), D('-0.5'))
  assert await spot.query_order('missing') is None
  assert await spot.query_order('s1') is None
  (open_perp,) = await perp.open_orders()
  assert (open_perp.qty, open_perp.filled_qty) == (D('0.010'), D('0.004'))
  assert (await perp.query_order('p1')) is not None
  assert await perp.query_order('p1') is None
  assert await perp.query_order('p1') is None


# --- account reads -----------------------------------------------------------------


async def test_fees_pass_market_maker_rebates_through_as_negative_rates():
  """Account rates come back as sent: a negative maker rate stays exactly negative."""
  spot_fee = AsyncMock(
    return_value=[
      {'symbol': 'BTC-USDT', 'makerFeeRate': D('-0.00005'), 'takerFeeRate': D('0.0004')}
    ]
  )
  perp_fee = AsyncMock(
    return_value={
      'symbol': 'XBTUSDTM',
      'makerFeeRate': D('-0.000075'),
      'takerFeeRate': D('0.0003'),
    }
  )
  spot, perp = market_pair(
    account=SimpleNamespace(trade_fee=SimpleNamespace(actual_fee=spot_fee)),
    futures_api=SimpleNamespace(trade_fee=SimpleNamespace(actual_fee_futures=perp_fee)),
  )
  sf, pf = await spot.fees(), await perp.fees()
  assert sf.maker_buy == sf.maker_sell == D('-0.00005')
  assert sf.taker_buy == sf.taker_sell == D('0.0004')
  assert pf.maker_buy == pf.maker_sell == D('-0.000075')
  assert pf.taker_buy == D('0.0003')
  assert str(pf.maker_buy) == '-0.000075'
  perp_fee.assert_awaited_once_with('XBTUSDTM')


async def test_fees_add_reported_tax_rates():
  """Where KuCoin reports a tax rate it is part of the combined rate."""
  spot_fee = AsyncMock(
    return_value=[
      {
        'symbol': 'BTC-USDT',
        'makerFeeRate': D('0.001'),
        'takerFeeRate': D('0.001'),
        'buyTaxRate': D('0.0002'),
        'sellTaxRate': D('0'),
      }
    ]
  )
  spot, _ = market_pair(
    account=SimpleNamespace(trade_fee=SimpleNamespace(actual_fee=spot_fee))
  )
  fees = await spot.fees()
  assert fees.maker_buy == D('0.0012') and fees.maker_sell == D('0.001')


def position(**fields: Any) -> Row:
  """A position row, flat unless overridden."""
  row: Row = {
    'symbol': 'XBTUSDTM',
    'crossMode': True,
    'currentQty': 0,
    'avgEntryPrice': 0.0,
    'liquidationPrice': 0.0,
    'markValue': 0.0,
    'posMaint': 0.0,
    'posMargin': 0.0,
    'posInit': 0.0,
    'unrealisedPnl': 0.0,
    'settleCurrency': 'USDT',
  }
  return row | fields


async def test_positions_and_cross_collateral_from_shared_reads():
  """One position list serves every market; quantities convert from lots."""
  rows = [
    position(
      currentQty=-25,
      avgEntryPrice=100.5,
      liquidationPrice=180.25,
      markValue=-2.5,
      posMaint=0.0125,
    ),
    position(symbol='ETHUSDTM', currentQty=3, markValue=7.5, posMaint=0.05),
  ]
  overview: Row = {
    'currency': 'USDT',
    'accountEquity': 100.0,
    'availableBalance': 80.0,
    'positionMargin': 15.0,
    'orderMargin': 5.0,
  }
  position_list = AsyncMock(return_value=rows)
  futures_account = AsyncMock(return_value=overview)
  _, perp = market_pair(
    futures=SimpleNamespace(positions=SimpleNamespace(get_position_list=position_list)),
    futures_api=SimpleNamespace(futures_account=futures_account),
  )
  pos = await perp.perp_position(ttl=timedelta(seconds=5))
  assert pos.size == D('-0.025') and pos.entry_price == D('100.5')
  assert pos.liquidation_price == D('180.25')
  collateral = await perp.perp_collateral(ttl=timedelta(seconds=5))
  assert position_list.await_count == 1
  assert collateral.margin_mode == 'cross'
  assert collateral.equity == 100 and collateral.free_collateral == 80
  assert collateral.initial_margin == 20
  assert collateral.maintenance_margin == D('0.0625')
  assert collateral.leverage == D('0.1')
  futures_account.assert_awaited_once_with('USDT')
  assert await perp.collateral_id() == 'kc:perp'
  pool = await LinearPerpExchange(shared=perp.shared).perp_collateral(
    ttl=timedelta(seconds=5)
  )
  assert pool.equity == 100


async def test_flat_and_isolated_positions():
  """A missing row is flat with no liquidation price; an isolated one has its own bucket."""
  rows = [
    position(
      symbol='XBTUSDTM',
      crossMode=False,
      currentQty=10,
      markValue=1.0,
      posMargin=0.5,
      unrealisedPnl=0.1,
      posInit=0.2,
      posMaint=0.01,
    )
  ]
  _, perp = market_pair(
    futures=SimpleNamespace(
      positions=SimpleNamespace(get_position_list=AsyncMock(side_effect=[[], rows]))
    )
  )
  flat = await perp.perp_position()
  assert flat.size == 0 and flat.liquidation_price is None
  bucket = await perp.perp_collateral()
  assert bucket.margin_mode == 'isolated'
  assert bucket.equity == D('0.6') and bucket.free_collateral == D('0.4')


async def test_usdc_contracts_have_no_pool_id():
  """`<account>:perp` names the USDT pool only."""
  spot, _ = market_pair()
  usdc = LinearPerpMarket(
    shared=spot.shared, symbol='XBTUSDCM', contract_multiplier=MULTIPLIER
  )
  with pytest.raises(NotImplementedError):
    await usdc.collateral_id()


async def test_spot_balances_and_collateral_resolution():
  """Spot balances read the `trade` account; IDs resolve through the exchange."""
  accounts_read = AsyncMock(
    return_value=[
      {
        'currency': 'BTC',
        'type': 'trade',
        'balance': D('0.5'),
        'available': D('0.4'),
        'holds': D('0.1'),
      },
      {
        'currency': 'USDT',
        'type': 'trade',
        'balance': D(1000),
        'available': D(900),
        'holds': D(100),
      },
    ]
  )
  spot, _ = market_pair(account=SimpleNamespace(spot_accounts=accounts_read))
  balances = await spot.balances()
  assert (balances.base.total, balances.base.free) == (D('0.5'), D('0.4'))
  assert (balances.quote.total, balances.quote.free) == (D(1000), D(900))
  assert sent(accounts_read).kwargs == {'type': 'trade'}
  ids = await spot.collateral_ids()
  assert ids.quote == 'kc:spot:USDT'
  eth = await SpotExchange(shared=spot.shared).balance('ETH')
  assert eth.total == eth.free == 0


async def test_leverage_reads_and_sets_cross_leverage():
  """`set_leverage` takes whole multiples and becomes the next order's leverage."""
  modify = AsyncMock(return_value=True)
  read = AsyncMock(return_value={'symbol': 'XBTUSDTM', 'leverage': D('3')})
  _, perp = market_pair(
    futures=SimpleNamespace(
      positions=SimpleNamespace(
        get_cross_margin_leverage=read, modify_cross_margin_leverage=modify
      )
    )
  )
  assert await perp.leverage() == 3
  await perp.set_leverage(D(7))
  assert sent(modify).kwargs == {'leverage': D(7)}
  assert await perp.order_leverage() == 7
  with pytest.raises(ValueError):
    await perp.set_leverage(D('2.5'))
  modify.return_value = False
  with pytest.raises(ApiError):
    await perp.set_leverage(D(2))


# --- history -----------------------------------------------------------------------


def pager(*pages: list[dict[str, Any]]):
  """A typed pager whose `.via(call)` yields fixed pages, recording its arguments."""
  calls: list[dict[str, Any]] = []

  def paged(**kwargs: Any):
    """Record one window's request."""
    calls.append(kwargs)

    async def walk() -> AsyncIterator[list[dict[str, Any]]]:
      """Yield the fixed pages for this window."""
      for page in pages:
        yield page

    return SimpleNamespace(via=lambda call: walk())  # pyright: ignore[reportUnknownLambdaType]

  return paged, calls


async def test_trade_history_walks_windows_and_keeps_each_fill_once():
  """Seven-day windows; rows outside a window (retention fallback) are dropped."""
  inside = NOW - timedelta(days=1)
  spot_rows: list[Row] = [
    {
      'id': 1,
      'tradeId': 11,
      'orderId': 'o',
      'side': 'buy',
      'liquidity': 'maker',
      'price': D(100),
      'size': D('0.2'),
      'fee': D('-0.001'),
      'feeCurrency': 'USDT',
      'createdAt': inside,
    }
  ]
  perp_rows: list[Row] = [
    {
      'tradeId': 't1',
      'orderId': 'p',
      'side': 'sell',
      'liquidity': 'taker',
      'price': D(100),
      'size': 4,
      'fee': D('0.01'),
      'feeCurrency': 'USDT',
      'tradeType': 'trade',
      'tradeTime': inside,
      'createdAt': inside,
    },
    {
      'tradeId': 't2',
      'orderId': 'p',
      'side': 'sell',
      'liquidity': 'taker',
      'price': D(100),
      'size': 4,
      'fee': D('0'),
      'feeCurrency': 'USDT',
      'tradeType': 'settlement',
      'tradeTime': inside,
      'createdAt': inside,
    },
  ]
  spot_paged, spot_calls = pager(spot_rows)
  perp_paged, perp_calls = pager(perp_rows)
  spot, perp = market_pair(
    spot=SimpleNamespace(orders_hf=SimpleNamespace(get_trade_history_paged=spot_paged)),
    futures=SimpleNamespace(orders=SimpleNamespace(get_trade_history_paged=perp_paged)),
  )
  start = NOW - timedelta(days=10)
  spot_trades = [t async for page in spot.trades_history(start, NOW) for t in page]
  perp_trades = [t async for page in perp.trades_history(start, NOW) for t in page]
  assert len(spot_calls) == len(perp_calls) == 2
  assert spot_calls[0]['end_at'] - spot_calls[0]['start_at'] < timedelta(days=7)
  (fill,) = spot_trades
  assert fill.qty == D('0.2') and fill.maker and fill.fee is not None
  assert fill.fee.amount == D('-0.001')
  (perp_fill,) = perp_trades
  assert perp_fill.qty == D('-0.004') and not perp_fill.maker
  with pytest.raises(ValueError):
    spot.trades_history(start.replace(tzinfo=None), NOW)


async def test_funding_payments_walk_day_windows():
  """Settled funding per day; a page that would overflow raises instead of truncating."""
  inside = NOW - timedelta(hours=30)
  history = AsyncMock(
    side_effect=[
      {'dataList': [{'funding': -0.25, 'timePoint': inside}], 'hasMore': False},
      {'dataList': [], 'hasMore': False},
    ]
  )
  _, perp = market_pair(
    futures=SimpleNamespace(
      funding_fees=SimpleNamespace(private_funding_history=history)
    )
  )
  rows = [
    p
    async for page in perp.funding_payments(NOW - timedelta(hours=47), NOW)
    for p in page
  ]
  assert [(p.amount, p.time) for p in rows] == [(D('-0.25'), inside)]
  history.side_effect = [{'dataList': [], 'hasMore': True}]
  with pytest.raises(ApiError):
    [p async for p in perp.funding_payments(NOW - timedelta(hours=1), NOW)]


# --- streams -----------------------------------------------------------------------


class FakeStream:
  """A typed private subscription: pushes from a queue, a drop as an exception."""

  def __init__(self):
    self.queue: asyncio.Queue[dict[str, Any] | Exception] = asyncio.Queue()
    self.unsubscribed = False

  def __aiter__(self):
    return self

  async def __anext__(self) -> dict[str, Any]:
    item = await self.queue.get()
    if isinstance(item, Exception):
      raise item
    return item

  async def unsubscribe(self):
    """Record the unsubscribe."""
    self.unsubscribed = True


def push(**fields: Any) -> Row:
  """An order push of BTC-USDT / XBTUSDTM shape."""
  row: Row = {
    'symbol': 'BTC-USDT',
    'orderId': 'o1',
    'clientOid': 'mine',
    'side': 'buy',
    'type': 'match',
    'matchPrice': D(100),
    'matchSize': D('0.1'),
    'tradeId': 't',
    'liquidity': 'taker',
    'feeType': 'makerFee',
    'ts': NOW,
  }
  return row | fields


async def test_fill_streams_keep_matches_of_their_symbol():
  """Only `match` pushes of the market's symbol are fills; lots convert on futures."""
  spot_stream, perp_stream = FakeStream(), FakeStream()
  streams = SimpleNamespace(
    spot_margin_private=SimpleNamespace(order_v2=AsyncMock(return_value=spot_stream)),
    futures_private=SimpleNamespace(all_orders=AsyncMock(return_value=perp_stream)),
  )
  spot, perp = market_pair(streams=streams)
  async with spot.trades_stream() as spot_fills, perp.trades_stream() as perp_fills:
    spot_stream.queue.put_nowait(push(type='open'))
    spot_stream.queue.put_nowait(push(symbol='ETH-USDT'))
    spot_stream.queue.put_nowait(push())
    perp_stream.queue.put_nowait(
      push(symbol='XBTUSDTM', side='sell', matchSize=5, feeType=None, liquidity='maker')
    )
    fill = await asyncio.wait_for(anext(aiter(spot_fills)), 1)
    assert (fill.qty, fill.price, fill.maker) == (D('0.1'), D(100), True)
    assert fill.client_order_id == 'mine' and fill.order_id == 'o1'
    assert fill.fee is None
    perp_fill = await asyncio.wait_for(anext(aiter(perp_fills)), 1)
    assert perp_fill.qty == D('-0.005') and perp_fill.maker
  assert spot_stream.unsubscribed and perp_stream.unsubscribed


async def test_dropped_stream_fails_and_resubscribes():
  """A drop fails subscribers with NetworkError; the next subscription opens anew."""
  first, second = FakeStream(), FakeStream()
  order_v2 = AsyncMock(side_effect=[first, second])
  spot, _ = market_pair(
    streams=SimpleNamespace(spot_margin_private=SimpleNamespace(order_v2=order_v2))
  )
  async with spot.trades_stream() as fills:
    first.queue.put_nowait(TypedNetworkError('connection closed'))
    with pytest.raises(NetworkError):
      await asyncio.wait_for(anext(aiter(fills)), 1)
  async with spot.trades_stream() as fills:
    second.queue.put_nowait(push())
    assert (await asyncio.wait_for(anext(aiter(fills)), 1)).qty == D('0.1')
  assert order_v2.await_count == 2


# --- errors and construction -------------------------------------------------------


async def test_rate_limits_carry_the_reset():
  """A throttled request is RateLimited, with KuCoin's reset readable."""
  error = TypedRateLimited(
    429, {'code': '429000'}, {'remaining': 0, 'reset': timedelta(milliseconds=800)}
  )
  add = AsyncMock(side_effect=error)
  spot, _ = market_pair(spot=SimpleNamespace(orders_hf=SimpleNamespace(add_sync=add)))
  with pytest.raises(RateLimited) as caught:
    await spot.place_order({'type': 'LIMIT', 'qty': D(1), 'price': D(100)})
  assert not isinstance(caught.value, OrderRejected)
  assert retry_after(caught.value) == timedelta(milliseconds=800)
  assert retry_after(RateLimited('429000', 'throttled')) is None


async def test_market_sdk_passes_credentials(monkeypatch: pytest.MonkeyPatch):
  """A private account builds an authenticated client from the KUCOIN_* variables."""
  monkeypatch.setenv('KUCOIN_API_KEY', 'key')
  monkeypatch.setenv('KUCOIN_API_SECRET', 'secret')
  monkeypatch.setenv('KUCOIN_API_PASSPHRASE', 'phrase')
  sdk = MarketSDK({'kc': accounts.Kucoin()})
  venue = await sdk.venue('kc')
  assert isinstance(venue, KucoinMarket)
  credentials = venue.shared.client.default_client.credentials
  assert credentials is not None and credentials.api_key == 'key'
  assert venue.shared.client.futures_rest_client.credentials == credentials


def test_unspecified_public_follows_the_credentials(monkeypatch: pytest.MonkeyPatch):
  """Without credentials the venue is public, as SDK builders before trading expect."""
  for name in ('KUCOIN_API_KEY', 'KUCOIN_API_SECRET', 'KUCOIN_API_PASSPHRASE'):
    monkeypatch.delenv(name, raising=False)
  assert KucoinMarket.new().shared.client.default_client.credentials is None
  private = KucoinMarket.new('k', 's', 'p')
  assert private.shared.client.default_client.credentials is not None
