"""Gateway wire protocol: message types, framing codec and protocol version.

Messages are tagged `msgspec.Struct`s; domain payloads (`Book`, `Trade`, ...) are the
SDK's own dataclasses, which msgspec encodes and decodes natively. The wire format is
documented in `docs/gateway-protocol.md`, with its JSON Schema beside it.
"""

from typing_extensions import (
  TYPE_CHECKING,
  Any,
  Literal,
  NotRequired,
  Sequence,
  TypedDict,
  Callable,
  cast,
)
from abc import ABC
from datetime import datetime
from decimal import Decimal

import msgspec

from tribulnation.sdk.core import OverflowPolicy
from tribulnation.sdk import (
  Error,
  NetworkError,
  ValidationError,
  ApiError,
  BadRequest,
  AuthError,
  RateLimited,
  OrderRejected,
  LogicError,
)
from tribulnation.sdk.market import (
  Book,
  Candle,
  CandleInterval,
  Fees,
  NextFunding,
  Ticker,
  PerpStats,
  Trade,
  Rules,
  Settings,
  Order,
  OrderResponse,
  OrderState,
  Position,
  PerpPosition,
  Collateral,
  PerpCollateral,
  FundingRate,
  FundingPayment,
)
from tribulnation.sdk.market.venue import ExchangeDescription
from tribulnation.sdk.impl.accounts import VenueId

PROTOCOL = 'tribulnation-gateway.v1'
"""WebSocket subprotocol naming this wire format and its version.

Clients offer it in the upgrade and the gateway selects it, so peers on different
versions fail to connect instead of misreading each other's frames. A peer naming no
subprotocol predates negotiation (SDK 2.17 and earlier) and speaks the same v1 frames.
"""


def offered_protocols(header: str | None) -> list[str]:
  """Split a `Sec-WebSocket-Protocol` request header into the offered names."""
  return [name.strip() for name in (header or '').split(',') if name.strip()]


class WireOrderShape(TypedDict):
  """Order as it crosses the wire: prices and quantities decode as `Decimal`."""

  qty: Decimal
  price: Decimal
  type: Literal['MARKET', 'LIMIT', 'POST_ONLY']
  client_order_id: NotRequired[str | None]


class AnyCollateral(ABC):
  """Decode marker for a `PerpCollateral` or a plain `Collateral` payload.

  The two are untagged dataclasses, which msgspec cannot tell apart in a union, so
  `dec_hook` picks `PerpCollateral` when the margin fields are present.
  """


AnyCollateral.register(Collateral)


# Type checkers see the SDK's own types; msgspec, at runtime, sees shapes it can decode
# without importing optional venue packages (`Settings` names their TypedDicts) or
# guessing between `Order`'s `str | Decimal | float | int` prices.
if TYPE_CHECKING:
  WireSettings = Settings
  WireOrder = Order
  WireCollateral = PerpCollateral | Collateral
else:
  WireSettings = dict[str, dict[str, Any]]
  """Venue settings, carried opaquely: each venue's adapter validates its own entry."""
  WireOrder = WireOrderShape
  WireCollateral = AnyCollateral


no_settings = cast(Callable[[], WireSettings], dict)
"""Default empty settings; the plain `dict` lets the schema record the `{}` default."""


class Msg(msgspec.Struct, tag_field='tag', gc=False):
  """A wire message: its kind in `tag`, its correlation ID in `id`.

  Messages hold no reference cycles, so they skip garbage-collector tracking.
  """

  id: str
  """Correlates a reply, stream item or end with its request."""


# ── Exceptions ───────────────────────────────────────────────────────────────

EXCEPTIONS: dict[str, type[Exception]] = {
  'NotImplementedError': NotImplementedError,
  'ValueError': ValueError,
  'Error': Error,
  'NetworkError': NetworkError,
  'ValidationError': ValidationError,
  'ApiError': ApiError,
  'BadRequest': BadRequest,
  'AuthError': AuthError,
  'RateLimited': RateLimited,
  'OrderRejected': OrderRejected,
  'LogicError': LogicError,
}


def encode_exception(exc: Exception) -> str:
  """Record the exception class name for wire transport."""
  return type(exc).__name__


def decode_exception(exc_type: str) -> type[Exception]:
  """Resolve a supported remote exception class."""
  return EXCEPTIONS.get(exc_type, Exception)


# ── Market-level call requests ───────────────────────────────────────────────


class DepthReq(Msg, kw_only=True, tag='depth'):
  """Fetch one order book snapshot (`Market.depth`)."""

  market_id: str
  levels: int | None = None
  settings: WireSettings = msgspec.field(default_factory=no_settings)


class RulesReq(Msg, kw_only=True, tag='rules'):
  """Fetch a market's trading rules (`Market.rules`)."""

  market_id: str
  refetch: bool = False


class OpenOrdersReq(Msg, kw_only=True, tag='open_orders'):
  """List the account's open orders on a market."""

  market_id: str


class QueryOrderReq(Msg, kw_only=True, tag='query_order'):
  """Look up one order by its venue order ID."""

  market_id: str
  order_id: str


class TradesHistoryReq(Msg, kw_only=True, tag='trades_history'):
  """Fetch the account's fills in a time window."""

  market_id: str
  start: datetime
  end: datetime


class PositionReq(Msg, kw_only=True, tag='position'):
  """Fetch the account's spot position on a market."""

  market_id: str


class AvailableNotionalReq(Msg, kw_only=True, tag='available_notional'):
  """Fetch the notional the account can still open on a market."""

  market_id: str


class PlaceOrderReq(Msg, kw_only=True, tag='place_order'):
  """Place one order."""

  market_id: str
  order: WireOrder
  settings: WireSettings = msgspec.field(default_factory=no_settings)


class CancelOrderReq(Msg, kw_only=True, tag='cancel_order'):
  """Cancel one order by its venue order ID."""

  market_id: str
  order_id: str
  settings: WireSettings = msgspec.field(default_factory=no_settings)


class CancelOpenOrdersReq(Msg, kw_only=True, tag='cancel_open_orders'):
  """Cancel every open order of the account on a market."""

  market_id: str
  settings: WireSettings = msgspec.field(default_factory=no_settings)


class IndexReq(Msg, kw_only=True, tag='index'):
  """Fetch a perpetual market's index price."""

  market_id: str
  settings: WireSettings = msgspec.field(default_factory=no_settings)


class NextFundingReq(Msg, kw_only=True, tag='next_funding'):
  """Fetch a perpetual market's upcoming funding rate."""

  market_id: str


class FundingRatesReq(Msg, kw_only=True, tag='funding_rates'):
  """Fetch a perpetual market's historical funding rates."""

  market_id: str
  start: datetime | None = None
  end: datetime | None = None


class FundingPaymentsReq(Msg, kw_only=True, tag='funding_payments'):
  """Fetch the account's funding payments in a time window."""

  market_id: str
  start: datetime
  end: datetime


class PerpPositionReq(Msg, kw_only=True, tag='perp_position'):
  """Fetch the account's perpetual position on a market."""

  market_id: str


class CollateralReq(Msg, kw_only=True, tag='collateral'):
  """Fetch the collateral bucket backing a market."""

  market_id: str


class PerpCollateralReq(Msg, kw_only=True, tag='perp_collateral'):
  """Fetch the perpetual margin bucket backing a market."""

  market_id: str


# ── Exchange-level call requests ─────────────────────────────────────────────


class ExchangePerpCollateralReq(Msg, kw_only=True, tag='exchange_perp_collateral'):
  """Fetch a perpetual exchange's margin bucket."""

  account_id: str
  """Account key addressing the venue, e.g. `\'hl\'`."""
  exchange_id: str


class MarketsReq(Msg, kw_only=True, tag='markets'):
  """List an exchange's market IDs."""

  account_id: str
  """Account key addressing the venue, e.g. `\'hl\'`."""
  exchange_id: str


# ── Venue-level call requests ────────────────────────────────────────────────


class ExchangesReq(Msg, kw_only=True, tag='exchanges'):
  """List a venue's exchanges."""

  account_id: str
  """Account key addressing the venue, e.g. `\'hl\'`."""


# ── SDK-level call requests ──────────────────────────────────────────────────


class VenueReq(Msg, kw_only=True, tag='venue'):
  """Resolve the venue behind an account key."""

  account_id: str
  """Account key addressing the venue, e.g. `'hl'`."""


class VenuesReq(Msg, kw_only=True, tag='venues'):
  """List the gateway's account keys."""


# ── Market-level stream requests ─────────────────────────────────────────────


class DepthStreamReq(Msg, kw_only=True, tag='depth_stream'):
  """Subscribe to order book updates; items arrive as `depth_data`."""

  market_id: str
  levels: int | None = None
  queue_size: int = 1
  overflow: OverflowPolicy = 'latest'
  settings: WireSettings = msgspec.field(default_factory=no_settings)


class TradesStreamReq(Msg, kw_only=True, tag='trades_stream'):
  """Subscribe to the account's fills; items arrive as `trades_data`."""

  market_id: str
  queue_size: int = 1000
  overflow: OverflowPolicy = 'fail'
  settings: WireSettings = msgspec.field(default_factory=no_settings)


# ── Control ──────────────────────────────────────────────────────────────────


class UnsubMsg(Msg, kw_only=True, tag='unsub'):
  """Cancel the stream opened by the request with this `id`."""


class FeesReq(Msg, kw_only=True, tag='fees'):
  """Fetch account-specific trading fees."""

  market_id: str
  refetch: bool = False


class LeverageReq(Msg, kw_only=True, tag='leverage'):
  """Fetch the leverage the account can open at on a perpetual market."""

  market_id: str
  refetch: bool = False


class CandlesReq(Msg, kw_only=True, tag='candles'):
  """Fetch candles in a half-open time window."""

  market_id: str
  interval: CandleInterval
  start: datetime
  end: datetime


class ExchangeReq(Msg, kw_only=True, tag='exchange'):
  """Resolve an exchange's actual product type, including qualified IDs."""

  account_id: str
  """Account key addressing the venue, e.g. `\'hl\'`."""
  exchange_id: str


class TickersReq(Msg, kw_only=True, tag='tickers'):
  """Fetch bulk tickers from an exchange."""

  account_id: str
  """Account key addressing the venue, e.g. `\'hl\'`."""
  exchange_id: str
  markets: list[str] | None = None
  settings: WireSettings = msgspec.field(default_factory=no_settings)


class PerpStatsReq(Msg, kw_only=True, tag='perp_stats'):
  """Fetch bulk perpetual statistics."""

  account_id: str
  """Account key addressing the venue, e.g. `\'hl\'`."""
  exchange_id: str
  markets: list[str] | None = None
  settings: WireSettings = msgspec.field(default_factory=no_settings)


class ExchangeCollateralReq(Msg, kw_only=True, tag='exchange_collateral'):
  """Fetch a spot or perpetual exchange's collateral bucket."""

  account_id: str
  """Account key addressing the venue, e.g. `\'hl\'`."""
  exchange_id: str


# ── Message unions ───────────────────────────────────────────────────────────

CallReq = (
  DepthReq
  | FeesReq
  | LeverageReq
  | CandlesReq
  | ExchangeReq
  | TickersReq
  | PerpStatsReq
  | ExchangeCollateralReq
  | RulesReq
  | OpenOrdersReq
  | QueryOrderReq
  | TradesHistoryReq
  | PositionReq
  | AvailableNotionalReq
  | PlaceOrderReq
  | CancelOrderReq
  | CancelOpenOrdersReq
  | IndexReq
  | NextFundingReq
  | FundingRatesReq
  | FundingPaymentsReq
  | PerpPositionReq
  | CollateralReq
  | PerpCollateralReq
  | ExchangePerpCollateralReq
  | MarketsReq
  | ExchangesReq
  | VenueReq
  | VenuesReq
)

StreamReq = DepthStreamReq | TradesStreamReq

ClientMsg = CallReq | StreamReq | UnsubMsg


# ── Call responses ───────────────────────────────────────────────────────────


class DepthResp(Msg, kw_only=True, tag='depth'):
  """Order book snapshot."""

  book: Book


class RulesResp(Msg, kw_only=True, tag='rules'):
  """Market trading rules."""

  rules: Rules


class OpenOrdersResp(Msg, kw_only=True, tag='open_orders'):
  """Open orders of the account on a market."""

  orders: Sequence[OrderState]


class QueryOrderResp(Msg, kw_only=True, tag='query_order'):
  """The order, or null when the venue does not know it."""

  order: OrderState | None


class TradesHistoryResp(Msg, kw_only=True, tag='trades_history'):
  """Fills of the account in the requested window."""

  trades: Sequence[Trade]


class PositionResp(Msg, kw_only=True, tag='position'):
  """Spot position."""

  position: Position


class AvailableNotionalResp(Msg, kw_only=True, tag='available_notional'):
  """Notional the account can still open."""

  value: Decimal


class PlaceOrderResp(Msg, kw_only=True, tag='place_order'):
  """Acknowledgement of a placed order."""

  response: OrderResponse


class CancelOrderResp(Msg, kw_only=True, tag='cancel_order'):
  """Venue-specific cancellation result."""

  result: Any


class CancelOpenOrdersResp(Msg, kw_only=True, tag='cancel_open_orders'):
  """Venue-specific cancellation result."""

  result: Any


class IndexResp(Msg, kw_only=True, tag='index'):
  """Index price."""

  value: Decimal


class NextFundingResp(Msg, kw_only=True, tag='next_funding'):
  """Upcoming funding rate."""

  rate: NextFunding


class FundingRatesResp(Msg, kw_only=True, tag='funding_rates'):
  """Historical funding rates."""

  rates: Sequence[FundingRate]


class FundingPaymentsResp(Msg, kw_only=True, tag='funding_payments'):
  """Funding payments of the account."""

  payments: Sequence[FundingPayment]


class PerpPositionResp(Msg, kw_only=True, tag='perp_position'):
  """Perpetual position."""

  position: PerpPosition


class CollateralResp(Msg, kw_only=True, tag='collateral'):
  """Collateral bucket: perpetual margin fields are present when the bucket has them."""

  collateral: WireCollateral


class PerpCollateralResp(Msg, kw_only=True, tag='perp_collateral'):
  """Perpetual margin bucket."""

  collateral: PerpCollateral


class MarketsResp(Msg, kw_only=True, tag='markets'):
  """Market IDs of an exchange."""

  markets: Sequence[str]


class ExchangesResp(Msg, kw_only=True, tag='exchanges'):
  """Exchanges of a venue."""

  exchanges: Sequence[ExchangeDescription]


class VenuesResp(Msg, kw_only=True, tag='venues'):
  """Account keys configured on the gateway."""

  venues: Sequence[str]


# ── Stream data messages ──────────────────────────────────────────────────────


class DepthDataMsg(Msg, kw_only=True, tag='depth_data'):
  """One order book update of a `depth_stream` subscription."""

  book: Book


class TradesDataMsg(Msg, kw_only=True, tag='trades_data'):
  """One fill of a `trades_stream` subscription."""

  trade: Trade


# ── Control ───────────────────────────────────────────────────────────────────


class ErrMsg(Msg, kw_only=True, tag='err'):
  """A call failed; `exc` names the SDK exception class when known."""

  error: str
  exc: str | None = None


class EndMsg(Msg, kw_only=True, tag='end'):
  """A stream ended: cleanly when `error` is null, else with that error."""

  exc: str | None = None
  error: str | None = None


class FeesResp(Msg, kw_only=True, tag='fees'):
  """Account fee schedule."""

  fees: Fees


class LeverageResp(Msg, kw_only=True, tag='leverage'):
  """Account leverage on a perpetual market."""

  value: Decimal


class CandlesResp(Msg, kw_only=True, tag='candles'):
  """Historical candles, preserving the SDK's value types."""

  candles: Sequence[Candle]


class ExchangeResp(Msg, kw_only=True, tag='exchange'):
  """Resolved exchange product type and venue."""

  type: Literal['spot', 'perp']
  venue_id: VenueId
  """Venue the gateway-side exchange reports, e.g. `'hyperliquid'`."""


class VenueResp(Msg, kw_only=True, tag='venue'):
  """Resolved venue of an account."""

  venue_id: VenueId
  """Venue the gateway-side venue reports, e.g. `'hyperliquid'`."""


class TickersResp(Msg, kw_only=True, tag='tickers'):
  """Tickers keyed by native market ID."""

  tickers: dict[str, Ticker]


class PerpStatsResp(Msg, kw_only=True, tag='perp_stats'):
  """Perpetual statistics keyed by native market ID."""

  stats: dict[str, PerpStats]


ServerMsg = (
  DepthResp
  | FeesResp
  | LeverageResp
  | CandlesResp
  | ExchangeResp
  | TickersResp
  | PerpStatsResp
  | RulesResp
  | OpenOrdersResp
  | QueryOrderResp
  | TradesHistoryResp
  | PositionResp
  | AvailableNotionalResp
  | PlaceOrderResp
  | CancelOrderResp
  | CancelOpenOrdersResp
  | IndexResp
  | NextFundingResp
  | FundingRatesResp
  | FundingPaymentsResp
  | PerpPositionResp
  | CollateralResp
  | PerpCollateralResp
  | MarketsResp
  | ExchangesResp
  | VenueResp
  | VenuesResp
  | DepthDataMsg
  | TradesDataMsg
  | ErrMsg
  | EndMsg
)


# ── Framing ──────────────────────────────────────────────────────────────────


def dec_hook(type: type, obj: Any) -> Any:
  """Decode the wire types msgspec does not handle natively."""
  if type is AnyCollateral:
    perp = isinstance(obj, dict) and 'initial_margin' in obj
    return msgspec.convert(obj, PerpCollateral if perp else Collateral)
  raise NotImplementedError(f'Unsupported wire type {type}')


encoder = msgspec.json.Encoder()
client_decoder = msgspec.json.Decoder(ClientMsg, dec_hook=dec_hook)
server_decoder = msgspec.json.Decoder(ServerMsg, dec_hook=dec_hook)


def encode_client(msg: ClientMsg) -> bytes:
  """Serialize a client request into a JSON frame."""
  return encoder.encode(msg)


def decode_client(data: str | bytes) -> ClientMsg:
  """Validate and decode a client JSON frame.

  Raises:
    msgspec.ValidationError: if the frame does not match any client message.
  """
  return client_decoder.decode(data)


def encode_server(msg: ServerMsg) -> bytes:
  """Serialize a server reply or stream message into a JSON frame."""
  return encoder.encode(msg)


def decode_server(data: str | bytes) -> ServerMsg:
  """Validate and decode a server JSON frame.

  Raises:
    msgspec.ValidationError: if the frame does not match any server message.
  """
  return server_decoder.decode(data)


def tag(msg: Msg) -> str:
  """Read a message's wire kind."""
  return str(type(msg).__struct_config__.tag)


def schema_hook(type: type) -> dict[str, Any]:
  """Describe the wire types msgspec cannot describe natively."""
  if type is AnyCollateral:
    return {
      'anyOf': [{'$ref': '#/$defs/PerpCollateral'}, {'$ref': '#/$defs/Collateral'}]
    }
  raise NotImplementedError(f'Unsupported wire type {type}')


def protocol_schema() -> dict[str, Any]:
  """Build the JSON Schema of every frame, checked in as `docs/gateway-protocol.schema.json`.

  `$defs.ClientMsg` is any frame a client sends, `$defs.ServerMsg` any frame the
  gateway sends.
  """
  (client, server, *_), defs = msgspec.json.schema_components(
    (ClientMsg, ServerMsg, PerpCollateral, Collateral), schema_hook=schema_hook
  )
  return {
    '$schema': 'https://json-schema.org/draft/2020-12/schema',
    'title': 'Tribulnation SDK gateway protocol',
    'description': (
      f'WebSocket subprotocol {PROTOCOL}: one JSON object per binary frame. '
      'Generated by tribulnation.sdk.gateway.codec.protocol_schema; '
      'see docs/gateway-protocol.md.'
    ),
    'anyOf': [{'$ref': '#/$defs/ClientMsg'}, {'$ref': '#/$defs/ServerMsg'}],
    '$defs': {'ClientMsg': client, 'ServerMsg': server, **defs},
  }
