"""A small in-memory Bitget Unified Trading Account venue for perpetual trading tests.

Signed REST over `httpx.MockTransport`: it verifies every `ACCESS-SIGN`, matches
orders against a fixed book of one USDT-margined perpetual, keeps the position and
the resting orders, and answers the UTA v3 trading and account endpoints the SDK
calls, so the order lifecycle can be exercised end to end without the venue.
"""

from typing_extensions import Any, Literal
from dataclasses import dataclass, field
from decimal import Decimal
from urllib.parse import parse_qsl, urlsplit
import base64
import hashlib
import hmac
import itertools
import json

import httpx
import pytest
from typed_bitget import Bitget
from typed_core.http import HttpClient

from tribulnation.bitget.core import SdkMixin
from tribulnation.bitget.market.impl import Cache
from tribulnation.bitget.market.perp_market import PerpMarket

ACCESS_KEY = 'fake-access'
SECRET = 'fake-secret'
PASSPHRASE = 'fake-passphrase'
SYMBOL = 'IOTXUSDT'
NOW = '1794831592000'

CONTRACT: dict[str, Any] = {
  'symbol': SYMBOL,
  'baseCoin': 'IOTX',
  'quoteCoin': 'USDT',
  'symbolType': 'perpetual',
  'maxLever': Decimal(50),
}


def signature(prehash: str) -> str:
  """The signature Bitget expects, computed independently of the client."""
  mac = hmac.new(SECRET.encode(), prehash.encode(), hashlib.sha256)
  return base64.b64encode(mac.digest()).decode()


@dataclass
class Resting:
  """An order the venue knows."""

  id: str
  client_oid: str
  side: str
  price: Decimal
  qty: Decimal
  tif: str
  filled: Decimal = Decimal(0)
  status: str = 'new'

  def info(self) -> dict[str, Any]:
    """As `order-info` answers it."""
    return {
      'orderId': self.id,
      'clientOid': self.client_oid,
      'category': 'USDT-FUTURES',
      'symbol': SYMBOL,
      'orderType': 'limit',
      'side': self.side,
      'price': str(self.price),
      'qty': str(self.qty),
      'amount': '0',
      'cumExecQty': str(self.filled),
      'cumExecValue': str(self.filled * self.price),
      'avgPrice': str(self.price if self.filled else 0),
      'timeInForce': self.tif,
      'orderStatus': self.status,
      'posSide': '',
      'holdMode': 'one_way_mode',
      'reduceOnly': 'NO',
      'feeDetail': [],
      'cancelReason': '',
      'execType': 'normal',
      'stpMode': 'none',
      'createdTime': NOW,
      'updatedTime': NOW,
    }

  def unfilled(self) -> dict[str, Any]:
    """As `unfilled-orders` lists it."""
    info = self.info()
    keys = (
      'orderId clientOid category symbol orderType side price qty cumExecQty '
      'avgPrice orderStatus createdTime updatedTime'
    ).split()
    return {k: info[k] for k in keys}


@dataclass
class FakeBitget:
  """The venue's state, and its REST side."""

  bid: Decimal = Decimal('0.002405')
  ask: Decimal = Decimal('0.002409')
  depth: Decimal = Decimal(10000)
  """Size available at the best bid and at the best ask."""
  position: Decimal = Decimal(0)
  orders: dict[str, Resting] = field(default_factory=dict[str, Resting])
  symbol_configs: list[dict[str, str]] = field(
    default_factory=lambda: [
      {
        'category': 'USDT-FUTURES',
        'symbol': SYMBOL,
        'marginMode': 'crossed',
        'leverage': '5',
      }
    ]
  )
  reject_code: str | None = None
  """An error code `place-order` answers instead of placing, when set."""
  reject_msg: str = 'refused'
  """The message sent with `reject_code`."""
  info_failure: Literal['network', 'api'] | None = None
  """How `order-info` fails, when set: a dropped connection or an error code."""
  requests: list[tuple[str, str, dict[str, Any]]] = field(
    default_factory=list[tuple[str, str, dict[str, Any]]]
  )
  ids: 'itertools.count[int]' = field(default_factory=lambda: itertools.count(1001))

  def transport(self) -> httpx.MockTransport:
    """The REST side."""
    return httpx.MockTransport(self.handle)

  def handle(self, request: httpx.Request) -> httpx.Response:
    """Verify the signature and answer one request."""
    url = urlsplit(str(request.url))
    body = request.content.decode()
    path = url.path + (f'?{url.query}' if url.query else '')
    headers = request.headers
    assert headers['ACCESS-KEY'] == ACCESS_KEY
    assert headers['ACCESS-PASSPHRASE'] == PASSPHRASE
    prehash = f'{headers["ACCESS-TIMESTAMP"]}{request.method}{path}{body}'
    assert headers['ACCESS-SIGN'] == signature(prehash), 'bad signature'
    params: dict[str, Any] = json.loads(body) if body else dict(parse_qsl(url.query))
    endpoint = url.path.removeprefix('/api/v3/')
    self.requests.append((request.method, endpoint, params))
    match endpoint:
      case 'trade/place-order':
        return self.place(params)
      case 'trade/order-info':
        return self.order_info(params['orderId'])
      case 'trade/cancel-order':
        return self.cancel(params['orderId'])
      case 'trade/cancel-symbol-order':
        rows = [
          self.cancel_one(o)
          for o in list(self.orders.values())
          if o.status in ('new', 'partially_filled')
        ]
        if not rows:
          return self.error('25204', 'Order does not exist')
        return self.answer({'list': rows})
      case 'trade/modify-order':
        return self.modify(params)
      case 'trade/unfilled-orders':
        rows = [
          o.unfilled()
          for o in self.orders.values()
          if o.status in ('new', 'partially_filled')
        ]
        return self.answer({'list': rows, 'cursor': None})
      case 'account/settings':
        return self.answer(self.settings())
      case 'account/set-leverage':
        return self.set_leverage(params)
      case 'account/assets':
        return self.answer(ASSETS)
      case 'position/current-position':
        return self.answer({'list': self.positions()})
      case _:
        raise AssertionError(f'unexpected request {request.method} {url.path}')

  def set_leverage(self, params: dict[str, Any]) -> httpx.Response:
    """Set a symbol's cross leverage, replacing its cross row."""
    assert params['category'] == 'USDT-FUTURES' and params['marginMode'] == 'crossed'
    self.symbol_configs[:] = [
      c
      for c in self.symbol_configs
      if not (c['symbol'] == params['symbol'] and c['marginMode'] == 'crossed')
    ]
    self.symbol_configs.append(
      {
        'category': 'USDT-FUTURES',
        'symbol': params['symbol'],
        'marginMode': 'crossed',
        'leverage': params['leverage'],
      }
    )
    return self.answer('success')

  def answer(self, data: Any) -> httpx.Response:
    """A successful envelope."""
    return httpx.Response(
      200, json={'code': '00000', 'msg': 'success', 'requestTime': 1, 'data': data}
    )

  def error(self, code: str, msg: str) -> httpx.Response:
    """An error envelope, sent with HTTP 400 as Bitget does."""
    return httpx.Response(
      400, json={'code': code, 'msg': msg, 'requestTime': 1, 'data': None}
    )

  def place(self, params: dict[str, Any]) -> httpx.Response:
    """Place an order: match what crosses, rest the rest unless immediate."""
    if self.reject_code is not None:
      return self.error(self.reject_code, self.reject_msg)
    assert params['category'] == 'USDT-FUTURES' and params['symbol'] == SYMBOL
    assert params['orderType'] == 'limit' and params['marginMode'] == 'crossed'
    order = Resting(
      id=str(next(self.ids)),
      client_oid=params.get('clientOid', ''),
      side=params['side'],
      price=Decimal(params['price']),
      qty=Decimal(params['qty']),
      tif=params['timeInForce'],
    )
    self.orders[order.id] = order
    crosses = (
      order.price >= self.ask if order.side == 'buy' else order.price <= self.bid
    )
    if crosses and order.tif == 'post_only':
      order.status = 'cancelled'
    elif crosses:
      self.execute(order, min(order.qty, self.depth))
    if order.tif in ('ioc', 'fok') and order.status not in ('filled', 'cancelled'):
      order.status = 'cancelled'
    return self.answer({'orderId': order.id, 'clientOid': order.client_oid})

  def execute(self, order: Resting, qty: Decimal):
    """Fill `qty` of `order`."""
    order.filled += qty
    self.position += qty if order.side == 'buy' else -qty
    order.status = 'filled' if order.filled == order.qty else 'partially_filled'

  def order_info(self, id: str) -> httpx.Response:
    """One order's state, or Bitget's not-found code."""
    if self.info_failure == 'network':
      raise httpx.ConnectError('connection reset')
    if self.info_failure == 'api':
      return self.error('50000', 'system error')
    if (order := self.orders.get(id)) is None:
      return self.error('25204', 'Order does not exist')
    return self.answer(order.info())

  def cancel_one(self, order: Resting) -> dict[str, str]:
    """Cancel a resting order."""
    order.status = 'cancelled'
    return {'orderId': order.id, 'clientOid': order.client_oid}

  def cancel(self, id: str) -> httpx.Response:
    """Cancel one order, if it rests."""
    order = self.orders.get(id)
    if order is None or order.status not in ('new', 'partially_filled'):
      return self.error('25204', 'Order does not exist')
    return self.answer(self.cancel_one(order))

  def modify(self, params: dict[str, Any]) -> httpx.Response:
    """Modify a resting order in place: Bitget answers a new order ID."""
    old = self.orders.get(params['orderId'])
    if old is None or old.status not in ('new', 'partially_filled'):
      return self.error('25204', 'Order does not exist')
    old.status = 'cancelled'
    new = Resting(
      id=str(next(self.ids)),
      client_oid=old.client_oid,
      side=old.side,
      price=Decimal(params.get('price', old.price)),
      qty=Decimal(params.get('qty', old.qty)),
      tif=old.tif,
    )
    self.orders[new.id] = new
    return self.answer({'orderId': new.id, 'clientOid': new.client_oid})

  def settings(self) -> dict[str, Any]:
    """The account settings: unified, one-way."""
    return {
      'uid': '1',
      'accountMode': 'unified',
      'assetMode': 'multi_assets',
      'accountLevel': 'advanced',
      'holdMode': 'one_way_mode',
      'stpMode': 'none',
      'symbolConfigList': self.symbol_configs,
      'coinConfigList': [],
    }

  def positions(self) -> list[dict[str, Any]] | None:
    """The one-way position, if any."""
    if self.position == 0:
      return None
    return [
      {
        'category': 'USDT-FUTURES',
        'symbol': SYMBOL,
        'marginCoin': 'USDT',
        'holdMode': 'one_way_mode',
        'posSide': 'long' if self.position > 0 else 'short',
        'marginMode': 'crossed',
        'positionBalance': '1',
        'available': str(abs(self.position)),
        'frozen': '0',
        'total': str(abs(self.position)),
        'leverage': '5',
        'curRealisedPnl': '0',
        'avgPrice': str(self.ask),
        'positionStatus': 'normal',
        'unrealisedPnl': '0',
        'liquidationPrice': '0',
        'mmr': '0',
        'profitRate': '0',
        'markPrice': str(self.bid),
        'breakEvenPrice': '0',
        'totalFunding': '0',
        'openFeeTotal': '0',
        'closeFeeTotal': '0',
        'createdTime': NOW,
        'updatedTime': NOW,
      }
    ]


ASSETS: dict[str, Any] = {
  'accountEquity': '1010',
  'usdtEquity': '1010',
  'btcEquity': '0.01',
  'unrealisedPnl': '0',
  'usdtUnrealisedPnl': '0',
  'btcUnrealizedPnl': '0',
  'effEquity': '1000',
  'mmr': '20',
  'imr': '200',
  'mgnRatio': '0.02',
  'positionMgnRatio': '0',
  'positionValue': '1000',
  'leverage': '1',
  'assets': [],
}
"""A pool with 1000 USD of effective equity, 200 of it initial margin in use."""


def market_on(fake: FakeBitget, *, uta: bool = True) -> PerpMarket:
  """A market whose client talks to `fake`."""
  http = HttpClient()
  http._client = httpx.AsyncClient(transport=fake.transport())  # type: ignore[attr-defined]
  client = Bitget.new(
    access_key=ACCESS_KEY, secret_key=SECRET, passphrase=PASSPHRASE, http=http
  )
  cache = Cache(account_id='bg', perp={'USDT-FUTURES': {SYMBOL: CONTRACT}})  # type: ignore[dict-item]
  return PerpMarket(
    account=SdkMixin(client=client, uta=uta), cache=cache, symbol=SYMBOL
  )


@pytest.fixture
def fake() -> FakeBitget:
  """A fresh venue."""
  return FakeBitget()


@pytest.fixture
def market(fake: FakeBitget) -> PerpMarket:
  """A UTA market on the fake venue."""
  return market_on(fake)


@pytest.fixture
def classic_market(fake: FakeBitget) -> PerpMarket:
  """A Classic-account market on the fake venue."""
  return market_on(fake, uta=False)
