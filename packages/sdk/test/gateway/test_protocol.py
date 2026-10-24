"""Gateway wire protocol: every message kind, v1 frames, the schema and the handshake."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing_extensions import Sequence, TypedDict, cast, get_args
import json
import os


import aiohttp
from aiohttp import web
import msgspec
import pytest
import pytest_asyncio

from tribulnation.sdk.gateway import codec
from tribulnation.sdk.gateway.proxy import GatewayError, ProxySDK
from tribulnation.sdk.gateway.server import Gateway
from tribulnation.sdk.market import (
  Book,
  Candle,
  Collateral,
  Fees,
  FundingPayment,
  FundingRate,
  NextFunding,
  OrderResponse,
  OrderState,
  PerpCollateral,
  PerpPosition,
  PerpStats,
  Position,
  Rules,
  Balance,
  SpotBalances,
  SpotRules,
  Settings,
  Ticker,
  Trade,
  TradingMarkets,
)
from tribulnation.sdk.market.venue import TradingVenue

SCHEMA = Path(__file__).resolve().parents[4] / 'docs/gateway-protocol.schema.json'
T = datetime(2026, 10, 19, 12, 30, 0, 123456, tzinfo=timezone.utc)
T_OFFSET = datetime(2026, 10, 19, 14, 30, tzinfo=timezone(timedelta(hours=2)))
D = Decimal
SETTINGS = cast(
  Settings, {'dydx': {'good_til_blocks': 20}, 'hyperliquid': {'limit_tif': 'Alo'}}
)
FEES = Fees(
  maker_buy=D('0.0001'),
  maker_sell=D('0.0001'),
  taker_buy=D('0.00035'),
  taker_sell=D('0.00035'),
)
BOOK = Book(
  bids=[Book.Entry(price=D('99.5'), qty=D('2'))],
  asks=[Book.Entry(price=D('100.5'), qty=D('3.25'))],
  time=T,
)
TRADE = Trade(
  id='t1',
  order_id='o1',
  client_order_id='c1',
  price=D('100'),
  qty=D('-1.5'),
  time=T,
  maker=True,
  fee=Trade.Fee(amount=D('0.01'), asset='USDC'),
  details={'height': 10, 'path': [1, 'a', None]},
)
ORDER_STATE = OrderState(
  id='o1',
  price=D('100'),
  qty=D('1'),
  filled_qty=D('0.25'),
  active=True,
  details={'s': 1},
)
PERP_COLLATERAL = PerpCollateral(
  equity=D('1000.5'),
  free_collateral=D('800'),
  initial_margin=D('150'),
  maintenance_margin=D('75'),
  leverage=D('3.5'),
  margin_mode='cross',
)


class MarketArgs(TypedDict):
  """Fields of a market-addressed request."""

  id: str
  market_id: str


class ExchangeArgs(TypedDict):
  """Fields of an exchange-addressed request."""

  id: str
  account_id: str
  exchange_id: str


MARKET: MarketArgs = {'id': 'r', 'market_id': 'dydx:perp:BTC-USD'}
EXCHANGE: ExchangeArgs = {'id': 'r', 'account_id': 'hl', 'exchange_id': 'perp'}

CLIENT_MESSAGES: list[codec.ClientMsg] = [
  codec.DepthReq(**MARKET, levels=10, settings=SETTINGS),
  codec.RulesReq(**MARKET, refetch=True),
  codec.OpenOrdersReq(**MARKET),
  codec.QueryOrderReq(**MARKET, order_id='o1'),
  codec.TradesHistoryReq(**MARKET, start=T, end=T_OFFSET),
  codec.PositionReq(**MARKET),
  codec.AvailableNotionalReq(**MARKET),
  codec.PlaceOrderReq(
    **MARKET,
    order={
      'type': 'POST_ONLY',
      'qty': D('0.015'),
      'price': D('64120.5'),
      'client_order_id': '42',
    },
    settings=SETTINGS,
  ),
  codec.CancelOrderReq(**MARKET, order_id='o1', settings=SETTINGS),
  codec.CancelOpenOrdersReq(**MARKET),
  codec.IndexReq(**MARKET),
  codec.NextFundingReq(**MARKET),
  codec.FundingRatesReq(**MARKET, start=T),
  codec.FundingPaymentsReq(**MARKET, start=T, end=T_OFFSET),
  codec.PerpPositionReq(**MARKET),
  codec.CollateralReq(**MARKET),
  codec.PerpCollateralReq(**MARKET),
  codec.ExchangePerpCollateralReq(**EXCHANGE),
  codec.MarketsReq(**EXCHANGE),
  codec.ExchangesReq(id='r', account_id='hl'),
  codec.VenueReq(id='r', account_id='hl'),
  codec.VenuesReq(id='r'),
  codec.DepthStreamReq(**MARKET, levels=20, settings=SETTINGS),
  codec.TradesStreamReq(**MARKET, queue_size=10, overflow='latest'),
  codec.UnsubMsg(id='r'),
  codec.FeesReq(**MARKET, refetch=True),
  codec.LeverageReq(**MARKET),
  codec.CandlesReq(**MARKET, interval='1h', start=T, end=T_OFFSET),
  codec.ExchangeReq(**EXCHANGE),
  codec.TickersReq(**EXCHANGE, markets=['BTC', 'ETH'], settings=SETTINGS),
  codec.PerpStatsReq(**EXCHANGE),
  codec.ExchangeCollateralReq(**EXCHANGE),
  codec.BalanceReq(id='r', account_id='hl', exchange_id='spot', asset='0'),
  codec.BalancesReq(id='r', market_id='hl:spot:UBTC/USDC:142'),
  codec.CollateralIdReq(**MARKET),
]

SERVER_MESSAGES: list[codec.ServerMsg] = [
  codec.DepthResp(id='r', book=BOOK),
  codec.RulesResp(
    id='r',
    rules=Rules(
      fee_asset='USDC',
      tick_size=D('0.5'),
      step_size=D('0.001'),
      min_value=D('10'),
      fees=FEES,
      api=True,
      details={'k': 'v'},
    ),
  ),
  codec.RulesResp(
    id='r',
    rules=SpotRules(
      base='197',
      quote='0',
      fee_asset=None,
      tick_size=D('0.5'),
      step_size=D('0.001'),
      api=True,
    ),
  ),
  codec.BalanceResp(id='r', balance=Balance(total=D('10'), free=D('6'))),
  codec.BalancesResp(
    id='r',
    balances=SpotBalances(
      base=Balance(total=D('2'), free=D('1.5')),
      quote=Balance(total=D('120'), free=D('100')),
    ),
  ),
  codec.CollateralIdResp(id='r', value='hl:spot:0'),
  codec.OpenOrdersResp(id='r', orders=[ORDER_STATE]),
  codec.QueryOrderResp(id='r', order=None),
  codec.QueryOrderResp(id='r', order=ORDER_STATE),
  codec.TradesHistoryResp(id='r', trades=[TRADE]),
  codec.PositionResp(id='r', position=Position(size=D('1.5'))),
  codec.AvailableNotionalResp(id='r', value=D('1234.5678')),
  codec.PlaceOrderResp(
    id='r',
    response=OrderResponse(id='o1', details={'tx': {'height': 1}}, filled_qty=D('0.5')),
  ),
  codec.CancelOrderResp(id='r', result={'tx_response': {'code': 0}}),
  codec.CancelOpenOrdersResp(id='r', result=None),
  codec.IndexResp(id='r', value=D('64000.1')),
  codec.NextFundingResp(
    id='r',
    rate=NextFunding(
      rate=D('0.0001'), time=T_OFFSET, premium=D('0.00002'), interval=timedelta(hours=8)
    ),
  ),
  codec.FundingRatesResp(id='r', rates=[FundingRate(rate=D('-0.0002'), time=T)]),
  codec.FundingPaymentsResp(
    id='r', payments=[FundingPayment(amount=D('-1.25'), time=T)]
  ),
  codec.PerpPositionResp(
    id='r', position=PerpPosition(size=D('-2'), entry_price=D('99.5'))
  ),
  codec.CollateralResp(id='r', collateral=PERP_COLLATERAL),
  codec.CollateralResp(
    id='r', collateral=Collateral(equity=D('10'), free_collateral=D('9'))
  ),
  codec.PerpCollateralResp(id='r', collateral=PERP_COLLATERAL),
  codec.MarketsResp(id='r', markets=['BTC', 'ETH']),
  codec.ExchangesResp(
    id='r',
    exchanges=[
      {
        'id': 'perp',
        'type': 'perp',
        'name': 'Perpetuals',
        'url': 'https://example.com',
      },
      {'id': '', 'type': 'spot', 'name': 'Spot'},
    ],
  ),
  codec.VenueResp(id='r', venue_id='hyperliquid'),
  codec.VenuesResp(id='r', venues=['hl', 'dydx']),
  codec.DepthDataMsg(id='r', book=BOOK),
  codec.TradesDataMsg(id='r', trade=TRADE),
  codec.ErrMsg(id='r', error='boom', exc='ApiError'),
  codec.EndMsg(id='r'),
  codec.EndMsg(id='r', exc='NetworkError', error='gone'),
  codec.FeesResp(id='r', fees=FEES),
  codec.LeverageResp(id='r', value=D('1.818181818181818181818181818')),
  codec.CandlesResp(
    id='r',
    candles=[
      Candle(time=T, open=D('1'), high=D('2'), low=D('0.5'), close=D('1.5'), trades=3)
    ],
  ),
  codec.ExchangeResp(id='r', type='perp', venue_id='dydx'),
  codec.TickersResp(id='r', tickers={'BTC': Ticker(last=D('1'), bid=D('0.9'))}),
  codec.PerpStatsResp(
    id='r',
    stats={
      'BTC': PerpStats(
        index=D('1'),
        mark=D('1.01'),
        next_funding_time=T,
        funding_interval=timedelta(hours=1),
      )
    },
  ),
]


def kinds(union: object) -> set[type]:
  """Every message class of a wire union."""
  return set(get_args(union))


def test_samples_cover_every_message_kind():
  """The round-trip samples below exercise every client and server message kind."""
  assert {type(m) for m in CLIENT_MESSAGES} == kinds(codec.ClientMsg)
  assert {type(m) for m in SERVER_MESSAGES} == kinds(codec.ServerMsg)


@pytest.mark.parametrize('msg', CLIENT_MESSAGES, ids=lambda m: codec.tag(m))
def test_client_messages_roundtrip(msg: codec.ClientMsg):
  """Every client message decodes back to an equal value, Decimals and times included."""
  assert codec.decode_client(codec.encode_client(msg)) == msg


@pytest.mark.parametrize('msg', SERVER_MESSAGES, ids=lambda m: codec.tag(m))
def test_server_messages_roundtrip(msg: codec.ServerMsg):
  """Every server message decodes back to an equal value, of the same payload types."""
  decoded = codec.decode_server(codec.encode_server(msg))
  assert decoded == msg
  for name in msg.__struct_fields__:
    assert type(getattr(decoded, name)) is type(getattr(msg, name))


def test_times_keep_their_offset():
  """A non-UTC time crosses with its offset, not converted."""
  msg = codec.FundingPaymentsReq(**MARKET, start=T, end=T_OFFSET)
  decoded = codec.decode_client(codec.encode_client(msg))
  assert isinstance(decoded, codec.FundingPaymentsReq)
  assert decoded.end.utcoffset() == timedelta(hours=2)


V1_CLIENT_FRAMES: list[tuple[bytes, codec.ClientMsg]] = [
  (
    b'{"id":"r","market_id":"dydx:perp:BTC-USD","order":{"type":"POST_ONLY","qty":"0.015",'
    b'"price":"64120.5","client_order_id":"42"},"settings":{"dydx":{"good_til_blocks":20}},'
    b'"tag":"place_order"}',
    codec.PlaceOrderReq(
      **MARKET,
      order={
        'type': 'POST_ONLY',
        'qty': D('0.015'),
        'price': D('64120.5'),
        'client_order_id': '42',
      },
      settings=cast(Settings, {'dydx': {'good_til_blocks': 20}}),
    ),
  ),
  (
    b'{"id":"r","market_id":"dydx:perp:BTC-USD","order_id":"o1","settings":{},"tag":"cancel_order"}',
    codec.CancelOrderReq(**MARKET, order_id='o1'),
  ),
]
"""Frames written by the pydantic codec that preceded msgspec (SDK 2.17)."""

V1_SERVER_FRAMES: list[tuple[bytes, codec.ServerMsg]] = [
  (
    b'{"id":"r","book":{"bids":[{"price":"99.5","qty":"2"}],"asks":[{"price":"100.5",'
    b'"qty":"3.25"}],"time":"2026-10-19T12:30:00.123456Z"},"tag":"depth_data"}',
    codec.DepthDataMsg(id='r', book=BOOK),
  ),
  (
    b'{"id":"r","response":{"id":"o1","details":{"tx":{"height":1}},"filled_qty":"0.5"},'
    b'"tag":"place_order"}',
    codec.PlaceOrderResp(
      id='r',
      response=OrderResponse(
        id='o1', details={'tx': {'height': 1}}, filled_qty=D('0.5')
      ),
    ),
  ),
  (
    b'{"id":"r","error":"boom","exc":"OrderRejected","tag":"err"}',
    codec.ErrMsg(id='r', error='boom', exc='OrderRejected'),
  ),
  (b'{"id":"r","exc":null,"error":null,"tag":"end"}', codec.EndMsg(id='r')),
  (
    b'{"id":"r","collateral":{"equity":"1000.5","free_collateral":"800","initial_margin":"150",'
    b'"maintenance_margin":"75","leverage":"3.5","margin_mode":"cross"},"tag":"collateral"}',
    codec.CollateralResp(id='r', collateral=PERP_COLLATERAL),
  ),
  (
    b'{"id":"r","collateral":{"equity":"10","free_collateral":"9"},"tag":"collateral"}',
    codec.CollateralResp(
      id='r', collateral=Collateral(equity=D('10'), free_collateral=D('9'))
    ),
  ),
  (
    b'{"id":"r","rate":{"rate":"0.0001","time":"2026-10-19T12:30:00.123456Z","premium":null,'
    b'"interval":"PT8H"},"tag":"next_funding"}',
    codec.NextFundingResp(
      id='r', rate=NextFunding(rate=D('0.0001'), time=T, interval=timedelta(hours=8))
    ),
  ),
]
"""Frames written by the pydantic codec that preceded msgspec (SDK 2.17)."""


@pytest.mark.parametrize(('frame', 'msg'), V1_CLIENT_FRAMES)
def test_v1_client_frames_are_unchanged(frame: bytes, msg: codec.ClientMsg):
  """Pre-msgspec client frames decode, and the codec writes the same JSON object."""
  assert codec.decode_client(frame) == msg
  assert json.loads(codec.encode_client(msg)) == json.loads(frame)


@pytest.mark.parametrize(('frame', 'msg'), V1_SERVER_FRAMES)
def test_v1_server_frames_decode(frame: bytes, msg: codec.ServerMsg):
  """Pre-msgspec server frames decode; only durations are now written in seconds."""
  assert codec.decode_server(frame) == msg


@pytest.mark.parametrize(
  'frame',
  [
    b'{"tag": "nope", "id": "r"}',
    b'{"id": "r"}',
    b'{"tag": "depth", "id": "r"}',
    b'{"tag": "place_order", "id": "r", "market_id": "m", "order": {"qty": "x"}}',
    b'not json',
  ],
)
def test_invalid_client_frames_are_rejected(frame: bytes):
  """Unknown kinds, missing fields and malformed values fail decoding."""
  with pytest.raises((msgspec.ValidationError, msgspec.DecodeError)):
    codec.decode_client(frame)


def test_unknown_fields_are_ignored():
  """A newer peer's optional field does not break an older decoder."""
  frame = b'{"tag": "venues", "id": "r", "added_later": 1}'
  assert codec.decode_client(frame) == codec.VenuesReq(id='r')


def test_checked_in_schema_is_current():
  """`docs/gateway-protocol.schema.json` matches the codec.

  Regenerate with `python -c "import json; from tribulnation.sdk.gateway.codec import
  protocol_schema; print(json.dumps(protocol_schema(), indent=2))" >
  docs/gateway-protocol.schema.json`.
  """
  assert json.loads(SCHEMA.read_text()) == codec.protocol_schema()


def test_schema_accepts_every_message_kind():
  """Every encoded sample validates against the published schema."""
  jsonschema = pytest.importorskip('jsonschema')
  validator = jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text()))
  messages: list[codec.Msg] = [*CLIENT_MESSAGES, *SERVER_MESSAGES]
  for msg in messages:
    validator.validate(json.loads(codec.encoder.encode(msg)))


# ── Handshake ────────────────────────────────────────────────────────────────


@dataclass
class VenuesSDK(TradingMarkets):
  """Answer only `venues`."""

  async def venues(self) -> Sequence[str]:
    """List one account."""
    return ['hl']

  async def venue(self, id: str, /) -> TradingVenue:
    """Reject venue access."""
    raise NotImplementedError


async def serve(app: web.Application, path: Path) -> web.AppRunner:
  """Serve an application on a Unix socket."""
  runner = web.AppRunner(app, shutdown_timeout=1.0)
  await runner.setup()
  await web.UnixSite(runner, str(path)).start()
  return runner


@pytest_asyncio.fixture
async def gateway_socket(tmp_path: Path) -> AsyncIterator[Path]:
  """A gateway serving `VenuesSDK`."""
  path = tmp_path / 'gateway.sock'
  app = web.Application()
  app.router.add_get('/', Gateway(VenuesSDK()).handler)
  runner = await serve(app, path)
  try:
    yield path
  finally:
    await runner.cleanup()
    if path.exists():
      os.unlink(path)


async def test_proxy_negotiates_the_protocol(gateway_socket: Path):
  """The proxy and the gateway agree on `codec.PROTOCOL` in the upgrade."""
  async with ProxySDK.at(f'unix://{gateway_socket}') as sdk:
    assert await sdk.venues() == ['hl']
    ctx = await sdk._conn.ctx
    assert ctx.ws.protocol == codec.PROTOCOL


async def test_gateway_refuses_another_protocol(gateway_socket: Path):
  """A client offering only another protocol version is refused before upgrading."""
  connector = aiohttp.UnixConnector(path=str(gateway_socket))
  async with aiohttp.ClientSession(connector=connector) as session:
    with pytest.raises(aiohttp.WSServerHandshakeError) as raised:
      await session.ws_connect(
        'http://localhost/', protocols=('tribulnation-gateway.v1',)
      )
  assert raised.value.status == 400


async def test_gateway_refuses_clients_predating_negotiation(gateway_socket: Path):
  """A client offering no subprotocol (SDK 2.17 and earlier) speaks v1: refused."""
  connector = aiohttp.UnixConnector(path=str(gateway_socket))
  async with aiohttp.ClientSession(connector=connector) as session:
    with pytest.raises(aiohttp.WSServerHandshakeError) as raised:
      await session.ws_connect('http://localhost/')
  assert raised.value.status == 400


async def test_proxy_fails_loudly_when_the_gateway_refuses(tmp_path: Path):
  """A gateway refusing the handshake surfaces as a `GatewayError`, not a hang."""
  path = tmp_path / 'refusing.sock'

  async def refuse(request: web.Request) -> web.Response:
    """Refuse every upgrade, like a gateway on another protocol version."""
    return web.Response(status=400, text='gateway speaks tribulnation-gateway.v1')

  app = web.Application()
  app.router.add_get('/', refuse)
  runner = await serve(app, path)
  try:
    with pytest.raises(
      GatewayError, match='refused the tribulnation-gateway.v2 handshake'
    ):
      async with ProxySDK.at(f'unix://{path}') as sdk:
        await sdk.venues()
  finally:
    await runner.cleanup()


async def test_proxy_refuses_gateways_predating_negotiation(tmp_path: Path):
  """A gateway answering without a subprotocol (SDK 2.17 and earlier) speaks v1."""
  path = tmp_path / 'legacy.sock'

  async def legacy(request: web.Request) -> web.WebSocketResponse:
    """Upgrade without a subprotocol, the way the pydantic gateway did."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    async for _ in ws:
      pass
    return ws

  app = web.Application()
  app.router.add_get('/', legacy)
  runner = await serve(app, path)
  try:
    with pytest.raises(GatewayError, match='none \\(v1\\)'):
      async with ProxySDK.at(f'unix://{path}') as sdk:
        await sdk.venues()
  finally:
    await runner.cleanup()
