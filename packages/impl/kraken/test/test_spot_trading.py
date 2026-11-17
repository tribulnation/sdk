"""Spot orders, balances and collateral IDs of a Kraken pair, against an in-memory
Spot REST venue (`FakeSpot`): signed private calls over `httpx.MockTransport`."""

from dataclasses import dataclass, field
from decimal import Decimal
from urllib.parse import parse_qsl
import base64
import hashlib
import hmac
import itertools
from typing_extensions import Any, Iterator

import httpx
import pytest
from typed_core.http import HttpClient

from tribulnation.sdk import ApiError, OrderNotFound, OrderRejected
from tribulnation.sdk.market import Balance, SpotCollateralIds, is_spot
from tribulnation.kraken.market.impl.balances import parse_balance
from tribulnation.kraken.market.impl.mixin import Shared
from tribulnation.kraken.market.impl.orders import add_order_request, rejection
from tribulnation.kraken.market.spot_exchange import SpotExchange
from tribulnation.kraken.market.spot_market import SpotMarket
from tribulnation.kraken.market.venue import KrakenMarket
from typed_kraken import Kraken
from typed_kraken.spot.market_data.asset_pairs import AssetPair

SECRET = base64.b64encode(b'fake-kraken-spot-secret').decode()
API_KEY = 'fake-spot-key'

KAVAUSD: AssetPair = {
  'altname': 'KAVAUSD',
  'wsname': 'KAVA/USD',
  'base': 'KAVA',
  'quote': 'ZUSD',
  'tick_size': Decimal('0.0001'),
  'lot_decimals': 8,
  'pair_decimals': 4,
  'ordermin': Decimal('70'),
  'costmin': Decimal('0.5'),
  'status': 'online',
  'fees': [],
  'fees_maker': [],
}
"""`AssetPairs` row for `KAVAUSD`, recorded from the public endpoint on 2026-11-17
(Kraken now answers empty fee schedules there)."""


def api_sign(path: str, body: str, nonce: str) -> str:
  """The `API-Sign` Kraken expects, computed independently of the client."""
  digest = hashlib.sha256((nonce + body).encode()).digest()
  mac = hmac.new(base64.b64decode(SECRET), path.encode() + digest, hashlib.sha512)
  return base64.b64encode(mac.digest()).decode()


@dataclass
class Resting:
  """One order the fake knows, open or closed."""

  side: str
  price: Decimal
  vol: Decimal
  vol_exec: Decimal = Decimal(0)
  status: str = 'open'
  cl_ord_id: str | None = None

  def wire(self) -> dict[str, Any]:
    """As `OpenOrders` and `QueryOrders` list it."""
    return {
      'refid': None,
      'userref': 0,
      'cl_ord_id': self.cl_ord_id,
      'status': self.status,
      'opentm': 1763380000.0,
      'starttm': 0,
      'expiretm': 0,
      'descr': {
        'pair': 'KAVAUSD',
        'type': self.side,
        'ordertype': 'limit',
        'price': str(self.price),
        'price2': '0',
        'leverage': 'none',
        'order': f'{self.side} {self.vol} KAVAUSD @ limit {self.price}',
        'close': '',
      },
      'vol': str(self.vol),
      'vol_exec': str(self.vol_exec),
      'cost': '0',
      'fee': '0',
      'price': '0',
      'stopprice': '0',
      'limitprice': '0',
      'misc': '',
      'oflags': 'fciq',
    }


@dataclass
class FakeSpot:
  """A Kraken Spot account trading `KAVAUSD` against a fixed book (bid 0.0800, ask
  0.0802): IOC limits cross it in full, other limits rest and hold their funds."""

  usd: Decimal = Decimal(100)
  kava: Decimal = Decimal(1000)
  bid: Decimal = Decimal('0.0800')
  ask: Decimal = Decimal('0.0802')
  orders: dict[str, Resting] = field(default_factory=dict[str, Resting])
  requests: list[tuple[str, dict[str, str]]] = field(
    default_factory=list[tuple[str, dict[str, str]]]
  )
  ids: Iterator[int] = field(default_factory=itertools.count)

  def transport(self) -> httpx.MockTransport:
    """The transport the client's HTTP calls go through."""
    return httpx.MockTransport(self.handle)

  def handle(self, request: httpx.Request) -> httpx.Response:
    """Verify the signature, then dispatch on the private endpoint."""
    path = request.url.path
    body = request.content.decode()
    form = dict(parse_qsl(body))
    assert request.headers['API-Key'] == API_KEY
    assert request.headers['API-Sign'] == api_sign(path, body, form['nonce'])
    self.requests.append((path, form))
    endpoint = path.removeprefix('/0/private/')
    try:
      result = getattr(self, endpoint)(form)
    except KrakenError as e:
      return httpx.Response(200, json={'error': [str(e)]})
    return httpx.Response(200, json={'error': [], 'result': result})

  def held(self, asset: str) -> Decimal:
    """What resting orders hold of `asset`."""
    return sum(
      (
        (o.vol - o.vol_exec) * o.price if asset == 'ZUSD' else o.vol - o.vol_exec
        for o in self.orders.values()
        if o.status == 'open' and (o.side == 'buy') == (asset == 'ZUSD')
      ),
      Decimal(0),
    )

  def BalanceEx(self, form: dict[str, str]) -> dict[str, Any]:
    """Both assets, with what resting orders hold."""
    return {
      'ZUSD': {'balance': str(self.usd), 'hold_trade': str(self.held('ZUSD'))},
      'KAVA': {'balance': str(self.kava), 'hold_trade': str(self.held('KAVA'))},
    }

  def AddOrder(self, form: dict[str, str]) -> dict[str, Any]:
    """Rest or cross one limit order."""
    side, price, vol = form['type'], Decimal(form['price']), Decimal(form['volume'])
    crosses = price >= self.ask if side == 'buy' else price <= self.bid
    if 'post' in form['oflags'].split(',') and crosses:
      raise KrakenError('EOrder:Post only order')
    if side == 'buy' and vol * price > self.usd - self.held('ZUSD'):
      raise KrakenError('EOrder:Insufficient funds')
    if vol < Decimal(70):
      raise KrakenError('EOrder:Order minimum not met')
    txid = f'O{next(self.ids):05d}-FAKE-SPOT'
    order = Resting(side=side, price=price, vol=vol, cl_ord_id=form.get('cl_ord_id'))
    self.orders[txid] = order
    if form.get('timeinforce') == 'IOC':
      if crosses:
        self.fill(txid, vol, at=self.ask if side == 'buy' else self.bid)
      order.status = 'closed' if order.vol_exec > 0 else 'canceled'
    return {'descr': {'order': f'{side} {vol} KAVAUSD @ limit {price}'}, 'txid': [txid]}

  def fill(self, txid: str, qty: Decimal, *, at: Decimal):
    """Fill `qty` of an order at `at`; fees are ignored."""
    order = self.orders[txid]
    order.vol_exec += qty
    sign = 1 if order.side == 'buy' else -1
    self.kava += sign * qty
    self.usd -= sign * qty * at
    if order.vol_exec == order.vol:
      order.status = 'closed'

  def OpenOrders(self, form: dict[str, str]) -> dict[str, Any]:
    """Every open order, of any pair."""
    return {
      'open': {txid: o.wire() for txid, o in self.orders.items() if o.status == 'open'}
    }

  def QueryOrders(self, form: dict[str, str]) -> dict[str, Any]:
    """One order by txid."""
    if form['txid'] not in self.orders:
      raise KrakenError('EOrder:Invalid order')
    return {form['txid']: self.orders[form['txid']].wire()}

  def CancelOrder(self, form: dict[str, str]) -> dict[str, Any]:
    """Cancel an open order."""
    order = self.orders.get(form['txid'])
    if order is None or order.status != 'open':
      raise KrakenError('EOrder:Unknown order')
    order.status = 'canceled'
    return {'count': 1}

  def AmendOrder(self, form: dict[str, str]) -> dict[str, Any]:
    """Change an open order's total quantity and price in place."""
    order = self.orders.get(form['txid'])
    if order is None or order.status != 'open':
      raise KrakenError('EOrder:Unknown order')
    order.vol = Decimal(form['order_qty'])
    order.price = Decimal(form['limit_price'])
    return {'amend_id': 'TEZA4R-DSDGT-IJBOJK'}


class KrakenError(Exception):
  """A Kraken `error` array entry the fake answers with."""


def spot_on(fake: FakeSpot) -> SpotMarket:
  """The `KAVAUSD` market of a Spot client talking to `fake`."""
  http = HttpClient()
  http._client = httpx.AsyncClient(transport=fake.transport())  # type: ignore[attr-defined]
  client = Kraken.new(api_key=API_KEY, private_key=SECRET, http=http)
  shared = Shared(
    client=client,
    account_id='ks',
    pairs={'KAVAUSD': {'key': 'KAVAUSD', 'symbol': 'KAVA/USD', 'info': KAVAUSD}},
  )
  return SpotMarket(shared=shared, meta={'pair': shared.pairs['KAVAUSD']})  # type: ignore[index]


@pytest.fixture
def fake() -> FakeSpot:
  """A fresh fake account."""
  return FakeSpot()


@pytest.mark.asyncio
async def test_rules_balances_and_collateral_ids(fake: FakeSpot):
  """Spot rules name the internal asset ids; collateral IDs are `<acct>:spot:<asset>`."""
  market = spot_on(fake)
  async with market:
    assert is_spot(market) and market.id == 'ks:spot:KAVAUSD'
    rules = await market.rules()
    assert (rules.base, rules.quote, rules.fee_asset) == ('KAVA', 'ZUSD', 'ZUSD')
    assert rules.tick_size == Decimal('0.0001') and rules.fixed_min_qty == 70
    assert rules.fees is None
    assert await market.collateral_ids() == SpotCollateralIds(
      base='ks:spot:KAVA', quote='ks:spot:ZUSD'
    )
    balances = await market.balances()
    assert balances.quote == Balance(total=Decimal(100), free=Decimal(100))
    assert await market.delta() == 1000
    hold = await market.hold(qty=Decimal(100), price=Decimal('0.08'))
    assert hold.collateral_id == 'ks:spot:ZUSD' and hold.amount == 8


@pytest.mark.asyncio
async def test_maker_lifecycle(fake: FakeSpot):
  """A post-only buy rests and holds quote, is amended in place, then cancelled."""
  market = spot_on(fake)
  async with market:
    placed = await market.place_order(
      {
        'type': 'POST_ONLY',
        'qty': Decimal(500),
        'price': Decimal('0.0790'),
        'client_order_id': 'mine-1',
      }
    )
    assert placed.filled_qty is None
    path, form = fake.requests[-1]
    assert path == '/0/private/AddOrder'
    assert form['oflags'] == 'post,fciq' and 'timeinforce' not in form
    assert (form['pair'], form['type'], form['volume'], form['price']) == (
      'KAVAUSD',
      'buy',
      '500',
      '0.079',
    )
    assert form['cl_ord_id'] == 'mine-1'
    (open_order,) = await market.open_orders()
    assert open_order.id == placed.id and open_order.qty == 500 and open_order.active
    quote = (await market.balances()).quote
    assert quote.total == 100 and quote.free == Decimal('60.5')

    fake.fill(placed.id, Decimal(100), at=Decimal('0.0790'))
    amended = await market.replace_order(
      placed.id, {'type': 'POST_ONLY', 'qty': Decimal(300), 'price': Decimal('0.0791')}
    )
    assert amended.id == placed.id
    path, form = fake.requests[-1]
    assert path == '/0/private/AmendOrder'
    assert form['order_qty'] == '400' and form['post_only'] in ('True', 'true')
    state = await market.query_order(placed.id)
    assert state is not None and state.active
    assert state.qty == 400 and state.filled_qty == 100

    await market.cancel_order(placed.id)
    assert await market.open_orders() == []
    with pytest.raises(OrderNotFound):
      await market.cancel_order(placed.id)
    state = await market.query_order(placed.id)
    assert state is not None and not state.active


@pytest.mark.asyncio
async def test_ioc_sell_through_the_book(fake: FakeSpot):
  """`MARKET` and an IOC-settings `LIMIT` are IOC limits; the fill is read back."""
  market = spot_on(fake)
  async with market:
    placed = await market.place_order(
      {'type': 'MARKET', 'qty': Decimal(-200), 'price': Decimal('0.0795')}
    )
    _, form = fake.requests[-1]
    assert form['timeinforce'] == 'IOC' and form['oflags'] == 'fciq'
    assert form['type'] == 'sell'
    state = await market.query_order(placed.id)
    assert state is not None and not state.active and state.filled_qty == -200
    assert await market.delta() == 800

    await market.place_order(
      {'type': 'LIMIT', 'qty': Decimal(100), 'price': Decimal('0.0810')},
      settings={'kraken': {'time_in_force': 'ioc'}},
    )
    assert fake.requests[-1][1]['timeinforce'] == 'IOC'
    assert await market.delta() == 900


@pytest.mark.asyncio
async def test_refusals_are_rejections(fake: FakeSpot):
  """Kraken's order errors are definitive: nothing rests, nothing filled."""
  market = spot_on(fake)
  async with market:
    with pytest.raises(OrderRejected):
      await market.place_order(
        {'type': 'POST_ONLY', 'qty': Decimal(100), 'price': Decimal('0.0810')}
      )
    with pytest.raises(OrderRejected):
      await market.place_order(
        {'type': 'LIMIT', 'qty': Decimal(5000), 'price': Decimal('0.0790')}
      )
    with pytest.raises(OrderRejected):
      await market.place_order(
        {'type': 'LIMIT', 'qty': Decimal(10), 'price': Decimal('0.0790')}
      )
    assert await market.query_order('OUNKNOWN-FAKE-SPOT') is None
    with pytest.raises(ValueError):
      await market.place_order(
        {'type': 'LIMIT', 'qty': Decimal(100), 'price': Decimal('0.0790')},
        settings={'kraken': {'reduce_only': True}},
      )


@pytest.mark.asyncio
async def test_spot_collateral_ids_resolve_through_the_venue(fake: FakeSpot):
  """`collateral('spot:<asset>')` reads one asset's balance; unknown assets raise."""
  market = spot_on(fake)
  venue = KrakenMarket(shared=market.shared)
  async with venue:
    exchange = await venue.exchange('spot')
    assert isinstance(exchange, SpotExchange) and is_spot(exchange)
    await market.place_order(
      {'type': 'LIMIT', 'qty': Decimal(-300), 'price': Decimal('0.0810')}
    )
    kava = await venue.collateral('spot:KAVA')
    assert kava.equity == 1000 and kava.free_collateral == 700
    usd = await venue.collateral('spot:ZUSD')
    assert usd.equity == 100 and usd.free_collateral == 100
    with pytest.raises(ValueError):
      await venue.collateral('spot:USD')


def test_balance_without_a_row_is_zero():
  """An asset never held is absent from `BalanceEx`."""
  assert parse_balance(None) == Balance(total=Decimal(0), free=Decimal(0))
  assert parse_balance(
    {'balance': Decimal(5), 'hold_trade': Decimal(2), 'credit': '0', 'credit_used': '0'}
  ) == Balance(total=Decimal(5), free=Decimal(3))


def test_ambiguous_errors_stay_ambiguous():
  """Service and internal errors may have placed the order: never a rejection."""
  for message in ('EService:Unavailable', 'EGeneral:Internal error', 'EService:Busy'):
    error = ApiError([message])
    assert rejection(error) is error
  assert isinstance(rejection(ApiError(['EOrder:Insufficient funds'])), OrderRejected)


def test_prices_and_sizes_are_plain_decimals(fake: FakeSpot):
  """No exponent notation or trailing zeros reach Kraken's form fields."""
  request = add_order_request(
    spot_on(fake),
    {'type': 'LIMIT', 'qty': Decimal('1E+2'), 'price': Decimal('0.07900')},
    {},
  )
  assert request['volume'] == '100' and request['price'] == '0.079'
  assert 'timeinforce' not in request
