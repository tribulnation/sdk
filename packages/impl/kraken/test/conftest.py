"""Fixtures for Kraken perpetual trading tests: a small in-memory Kraken Futures venue: signed REST over `httpx.MockTransport`
and the WebSocket feeds over a local server.

It matches orders against a fixed book of one perpetual, keeps positions, open
orders and fills, verifies every `Authent` signature, and pushes fills and book
updates on the feeds, so the SDK's order lifecycle can be exercised end to end
without the venue.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import parse_qsl, urlsplit
import asyncio
import base64
import hashlib
import hmac
import itertools
import json

import httpx
import pytest_asyncio
import websockets
from typed_core.http import HttpClient

from tribulnation.kraken.market.impl.futures_state import FuturesState
from tribulnation.kraken.market.impl.mixin import Shared
from tribulnation.kraken.market.perp_market import PerpMarket
from typed_kraken import Kraken
from typed_kraken.futures_trading.client import KrakenFutures

SECRET = base64.b64encode(b'fake-kraken-futures-secret').decode()
API_KEY = 'fake-key'
SYMBOL = 'PF_POPCATUSD'
NOW = '2026-11-16T10:00:00.000Z'


def authent(post_data: str, nonce: str, path: str) -> str:
  """The signature Kraken expects, computed independently of the client."""
  sha = hashlib.sha256((post_data + nonce + path.removeprefix('/derivatives')).encode())
  mac = hmac.new(base64.b64decode(SECRET), sha.digest(), hashlib.sha512)
  return base64.b64encode(mac.digest()).decode()


def num(value: Decimal) -> float:
  """A JSON number, as the venue sends."""
  return float(value)


@dataclass
class Resting:
  """A resting order."""

  id: str
  cli: str | None
  side: str
  kind: str
  price: Decimal
  size: Decimal
  filled: Decimal = Decimal(0)

  def wire(self) -> dict:
    """As events and order status carry it."""
    return {
      'orderId': self.id,
      'cliOrdId': self.cli,
      'type': self.kind,
      'symbol': SYMBOL,
      'side': self.side,
      'quantity': num(self.size + self.filled),
      'filled': num(self.filled),
      'limitPrice': num(self.price),
      'reduceOnly': False,
      'timestamp': NOW,
      'lastUpdateTimestamp': NOW,
    }


@dataclass
class FakeFutures:
  """The venue's state."""

  bid: Decimal = Decimal('0.0276')
  ask: Decimal = Decimal('0.0277')
  depth: Decimal = Decimal('10000')
  """Size available at the best bid and ask."""
  position: Decimal = Decimal(0)
  entry: Decimal = Decimal(0)
  orders: dict[str, Resting] = field(default_factory=dict)
  closed: dict[str, tuple[Resting, str]] = field(default_factory=dict)
  fills: list[dict] = field(default_factory=list)
  requests: list[tuple[str, str, dict]] = field(default_factory=list)
  sockets: set = field(default_factory=set)
  fill_subscribers: set = field(default_factory=set)
  ids: itertools.count = field(default_factory=lambda: itertools.count(1))
  loop: asyncio.AbstractEventLoop | None = None

  def transport(self) -> httpx.MockTransport:
    """The REST side."""
    return httpx.MockTransport(self.handle)

  def handle(self, request: httpx.Request) -> httpx.Response:
    """Verify the signature and answer one request."""
    url = urlsplit(str(request.url))
    body = request.content.decode()
    if url.path.endswith('/feeschedules'):
      return self.answer({'feeSchedules': FEE_SCHEDULES})
    signed = body if body else url.query
    assert request.headers['APIKey'] == API_KEY
    assert request.headers['Authent'] == authent(
      signed, request.headers['Nonce'], url.path
    ), 'bad signature'
    params = dict(parse_qsl(url.query))
    endpoint = url.path.rsplit('/v3/', 1)[1]
    self.requests.append((request.method, endpoint, params))
    match endpoint:
      case 'sendorder':
        return self.answer({'sendStatus': self.send(params)})
      case 'editorder':
        return self.answer({'editStatus': self.edit(params)})
      case 'cancelorder':
        return self.answer({'cancelStatus': self.cancel(params['order_id'])})
      case 'batchorder':
        batch = json.loads(dict(parse_qsl(body))['json'])['batchOrder']
        return self.answer({'batchStatus': [self.instruction(i) for i in batch]})
      case 'openorders':
        return self.answer(
          {'openOrders': [self.open_row(o) for o in self.orders.values()]}
        )
      case 'orders/status':
        ids = [v for k, v in parse_qsl(url.query) if k == 'orderIds']
        return self.answer(
          {'orders': [self.status(id) for id in ids if self.known(id)]}
        )
      case 'openpositions':
        return self.answer({'openPositions': self.positions()})
      case 'accounts':
        return self.answer({'accounts': {'flex': FLEX}})
      case 'leveragepreferences':
        return self.answer({'leveragePreferences': []})
      case 'feeschedules/volumes':
        return self.answer({'volumesByFeeSchedule': {FEE_UID: 6_000_000}})
      case 'fills':
        return self.answer({'fills': self.fills[::-1]})
      case _:
        return httpx.Response(404)

  def answer(self, payload: dict) -> httpx.Response:
    """A success envelope."""
    return httpx.Response(200, json={'result': 'success', 'serverTime': NOW, **payload})

  def known(self, id: str) -> bool:
    """Whether an order ID was ever seen."""
    return id in self.orders or id in self.closed

  def status(self, id: str) -> dict:
    """An `orders/status` entry."""
    if id in self.orders:
      order, status = self.orders[id], 'ENTERED_BOOK'
    else:
      order, status = self.closed[id]
    return {'order': {'type': 'ORDER', **order.wire()}, 'status': status}

  def open_row(self, order: Resting) -> dict:
    """An `openorders` row."""
    return {
      'order_id': order.id,
      'cliOrdId': order.cli,
      'status': 'partiallyFilled' if order.filled else 'untouched',
      'side': order.side,
      'orderType': 'lmt',
      'symbol': SYMBOL,
      'limitPrice': num(order.price),
      'filledSize': num(order.filled),
      'unfilledSize': num(order.size),
      'reduceOnly': False,
      'receivedTime': NOW,
      'lastUpdateTime': NOW,
    }

  def positions(self) -> list[dict]:
    """The open position, if any."""
    if self.position == 0:
      return []
    return [
      {
        'side': 'long' if self.position > 0 else 'short',
        'symbol': SYMBOL,
        'price': num(self.entry),
        'fillTime': NOW,
        'size': num(abs(self.position)),
        'unrealizedFunding': 0.0,
      }
    ]

  def crossing(self, side: str, price: Decimal) -> Decimal | None:
    """The price an order at `price` would take at, if it crosses."""
    if side == 'buy' and price >= self.ask:
      return self.ask
    if side == 'sell' and price <= self.bid:
      return self.bid

  def execute(self, order: Resting, qty: Decimal, price: Decimal, *, maker: bool):
    """Fill `qty` of `order` and push the fill."""
    order.filled += qty
    order.size -= qty
    signed = qty if order.side == 'buy' else -qty
    new = self.position + signed
    if self.position == 0 or (self.position > 0) == (signed > 0):
      self.entry = (self.entry * abs(self.position) + price * qty) / abs(new)
    self.position = new
    fill = {
      'fill_id': f'f{next(self.ids)}',
      'symbol': SYMBOL,
      'side': order.side,
      'order_id': order.id,
      'cliOrdId': order.cli,
      'size': num(qty),
      'price': num(price),
      'fillTime': NOW,
      'fillType': 'maker' if maker else 'taker',
    }
    self.fills.append(fill)
    self.push_fill(fill, fee=qty * price * Decimal('0.0005' if not maker else '0.0002'))
    return {
      'type': 'EXECUTION',
      'executionId': fill['fill_id'],
      'price': num(price),
      'amount': num(qty),
      'orderPriorExecution': order.wire(),
    }

  def send(self, params: dict) -> dict:
    """`sendorder`."""
    kind, side = params['orderType'], params['side']
    order = Resting(
      id=f'o{next(self.ids)}',
      cli=params.get('cliOrdId'),
      side=side,
      kind=kind,
      price=Decimal(params['limitPrice']),
      size=Decimal(params['size']),
    )
    take = self.crossing(side, order.price)
    if kind == 'post' and take is not None:
      return {'status': 'postWouldExecute', 'order_id': order.id, 'orderEvents': []}
    if kind == 'ioc' and take is None:
      return {'status': 'iocWouldNotExecute', 'order_id': order.id, 'orderEvents': []}
    events = []
    if take is not None:
      events.append(self.execute(order, min(order.size, self.depth), take, maker=False))
    if kind == 'ioc' or order.size == 0:
      if order.size > 0:
        events.append({'type': 'CANCEL', 'order': order.wire()})
      self.closed[order.id] = (
        order,
        'FULLY_EXECUTED' if order.size == 0 else 'CANCELLED',
      )
    else:
      self.orders[order.id] = order
      events.append({'type': 'PLACE', 'order': order.wire()})
    return {
      'status': 'placed',
      'order_id': order.id,
      'receivedTime': NOW,
      'orderEvents': events,
    }

  def edit(self, params: dict) -> dict:
    """`editorder`: the open size and price become the new ones."""
    order = self.orders.get(params['orderId'])
    if order is None:
      return {'status': 'orderForEditNotFound', 'orderEvents': []}
    price = Decimal(params['limitPrice'])
    if order.kind == 'post' and self.crossing(order.side, price) is not None:
      del self.orders[order.id]
      self.closed[order.id] = (order, 'CANCELLED')
      return {'status': 'postWouldExecute', 'orderId': order.id, 'orderEvents': []}
    old = order.wire()
    order.price, order.size = price, Decimal(params['size'])
    return {
      'status': 'edited',
      'orderId': order.id,
      'orderEvents': [{'type': 'EDIT', 'old': old, 'new': order.wire()}],
    }

  def cancel(self, id: str) -> dict:
    """`cancelorder`."""
    order = self.orders.pop(id, None)
    if order is None:
      return {'status': 'notFound', 'orderEvents': []}
    self.closed[id] = (order, 'CANCELLED')
    return {
      'status': 'cancelled',
      'order_id': id,
      'orderEvents': [{'type': 'CANCEL', 'order': order.wire()}],
    }

  def instruction(self, instruction: dict) -> dict:
    """One batch instruction."""
    if instruction['order'] == 'send':
      params = {
        k: str(v) for k, v in instruction.items() if k not in ('order', 'order_tag')
      }
      return {**self.send(params), 'order_tag': instruction['order_tag']}
    else:
      return self.cancel(instruction['order_id'])

  def fill_maker(self, id: str, qty: Decimal):
    """Fill a resting order as maker (another trader takes it)."""
    order = self.orders[id]
    self.execute(order, qty, order.price, maker=True)
    if order.size == 0:
      del self.orders[id]
      self.closed[id] = (order, 'FULLY_EXECUTED')

  def push_fill(self, fill: dict, *, fee: Decimal):
    """Push a fill on every `fills` subscriber."""
    message = json.dumps(
      {
        'feed': 'fills',
        'username': 'fake',
        'fills': [
          {
            'instrument': SYMBOL,
            'time': int(datetime.now(timezone.utc).timestamp() * 1000),
            'price': fill['price'],
            'seq': len(self.fills),
            'buy': fill['side'] == 'buy',
            'qty': fill['size'],
            'order_id': fill['order_id'],
            'cli_ord_id': fill['cliOrdId'],
            'fill_id': fill['fill_id'],
            'fill_type': fill['fillType'],
            'fee_paid': num(fee),
            'fee_currency': 'USD',
          }
        ],
      }
    )
    for ws in list(self.fill_subscribers):
      asyncio.ensure_future(ws.send(message))

  async def serve(self, ws):
    """The WebSocket side: challenge, `book` and `fills`."""
    self.sockets.add(ws)
    try:
      async for raw in ws:
        msg = json.loads(raw)
        if msg['event'] == 'challenge':
          await ws.send(json.dumps({'event': 'challenge', 'message': 'fake-challenge'}))
        elif msg['event'] == 'subscribe' and msg['feed'] == 'fills':
          sha = hashlib.sha256(b'fake-challenge').digest()
          expected = base64.b64encode(
            hmac.new(base64.b64decode(SECRET), sha, hashlib.sha512).digest()
          ).decode()
          if msg.get('signed_challenge') != expected:
            await ws.send(
              json.dumps(
                {
                  'event': 'alert',
                  'message': 'Failed to subscribe to authenticated feed',
                }
              )
            )
            continue
          await ws.send(json.dumps({'event': 'subscribed', 'feed': 'fills'}))
          await ws.send(
            json.dumps({'feed': 'fills_snapshot', 'account': 'fake', 'fills': []})
          )
          self.fill_subscribers.add(ws)
        elif msg['event'] == 'subscribe' and msg['feed'] == 'book':
          product = msg['product_ids'][0]
          await ws.send(
            json.dumps(
              {'event': 'subscribed', 'feed': 'book', 'product_ids': [product]}
            )
          )
          await ws.send(json.dumps(self.book_snapshot(product)))
          for seq, (side, price, qty) in enumerate(BOOK_UPDATES, start=101):
            await ws.send(
              json.dumps(
                {
                  'feed': 'book',
                  'product_id': product,
                  'side': side,
                  'seq': seq,
                  'price': price,
                  'qty': qty,
                  'timestamp': 1700000000100 + seq,
                }
              )
            )
    finally:
      self.sockets.discard(ws)
      self.fill_subscribers.discard(ws)

  def book_snapshot(self, product: str) -> dict:
    """The `book_snapshot` frame."""
    return {
      'feed': 'book_snapshot',
      'product_id': product,
      'timestamp': 1700000000000,
      'seq': 100,
      'tickSize': None,
      'bids': [
        {'price': num(self.bid), 'qty': num(self.depth)},
        {'price': 0.0275, 'qty': 500.0},
      ],
      'asks': [
        {'price': num(self.ask), 'qty': num(self.depth)},
        {'price': 0.0278, 'qty': 700.0},
      ],
    }


BOOK_UPDATES = [('sell', 0.0277, 0.0), ('buy', 0.02765, 42.0)]
"""Updates after the snapshot: the best ask leaves, a bid joins inside the spread."""

FEE_UID = '723888f7-0a8e-4183-8648-f920a22339e3'
FEE_SCHEDULES = [
  {
    'uid': FEE_UID,
    'name': 'MTF Linear Rebate Fees',
    'tiers': [
      {'makerFee': 0.02, 'takerFee': 0.05, 'usdVolume': 0.0},
      {'makerFee': 0.0175, 'takerFee': 0.045, 'usdVolume': 5000000.0},
      {'makerFee': 0.015, 'takerFee': 0.04, 'usdVolume': 10000000.0},
    ],
  }
]
FLEX = {
  'type': 'multiCollateralMarginAccount',
  'currencies': {
    'USD': {
      'quantity': 1000.0,
      'value': 1000.0,
      'collateral': 1000.0,
      'available': 900.0,
    }
  },
  'initialMargin': 10.0,
  'initialMarginWithOrders': 25.0,
  'maintenanceMargin': 5.0,
  'balanceValue': 1000.0,
  'portfolioValue': 1001.0,
  'collateralValue': 1000.0,
  'pnl': 1.0,
  'unrealizedFunding': 0.0,
  'totalUnrealized': 1.0,
  'totalUnrealizedAsMargin': 1.0,
  'availableMargin': 976.0,
  'marginEquity': 1001.0,
}


INSTRUMENT = {
  'symbol': SYMBOL,
  'type': 'flexible_futures',
  'tradeable': True,
  'tradfi': False,
  'platformsPermitted': [],
  'countriesBanned': [],
  'isExpired': False,
  'quote': 'USD',
  'base': 'POPCAT',
  'contractSize': 1,
  'contractValueTradePrecision': 0,
  'tickSize': 0.00001,
  'feeScheduleUid': '723888f7-0a8e-4183-8648-f920a22339e3',
  'retailMarginLevels': [
    {'numNonContractUnits': 0, 'initialMargin': 0.05, 'maintenanceMargin': 0.025}
  ],
  'marginSchedules': {
    'europa': {
      'retail': [
        {'numNonContractUnits': 0, 'initialMargin': 0.1, 'maintenanceMargin': 0.05}
      ]
    }
  },
}


@pytest_asyncio.fixture
async def venue():
  """The fake venue, its WebSocket server running, and a market factory for it."""
  fake = FakeFutures()
  async with websockets.serve(fake.serve, 'localhost', 0) as server:
    fake.loop = asyncio.get_running_loop()
    port = server.sockets[0].getsockname()[1]
    url = f'ws://localhost:{port}'
    yield fake, lambda **kw: market_on(fake, url, **kw)


def market_on(
  fake: FakeFutures, ws_url: str, *, schedule: str | None = None
) -> PerpMarket:
  """A market whose Futures client talks to `fake`."""
  http = HttpClient()
  http._client = httpx.AsyncClient(transport=fake.transport())
  futures = KrakenFutures.new(
    api_key=API_KEY, private_key=SECRET, http=http, ws_url=ws_url
  )
  shared = Shared(
    client=Kraken.new(public=True),
    perp=FuturesState(client=futures, margin_schedule=schedule),
    perp_instruments={SYMBOL: INSTRUMENT},  # type: ignore[dict-item]
    fee_asset='ZUSD',
    account_id='kf',
  )
  return PerpMarket(shared=shared, symbol=SYMBOL)
