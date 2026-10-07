"""Gateway codec: value serialization and wire protocol message types."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing_extensions import Literal, Annotated, Any, Sequence
import pydantic
from pydantic_core import core_schema

from tribulnation.sdk.core import OverflowPolicy
from tribulnation.sdk import (
  Error,
  NetworkError,
  ValidationError,
  ApiError,
  BadRequest,
  AuthError,
  RateLimited,
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


def settings_schema(_source: Any, _handler: Any) -> core_schema.CoreSchema:
  """Transport venue settings without importing optional venue implementations."""
  return core_schema.dict_schema(
    keys_schema=core_schema.str_schema(),
    values_schema=core_schema.dict_schema(keys_schema=core_schema.str_schema()),
  )


WireSettings = Annotated[Settings, pydantic.GetPydanticSchema(settings_schema)]

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
  'LogicError': LogicError,
}


def encode_exception(exc: Exception) -> str:
  """Record the exception class name for wire transport."""
  return type(exc).__name__


def decode_exception(exc_type: str) -> type[Exception]:
  """Resolve a supported remote exception class."""
  return EXCEPTIONS.get(exc_type, Exception)


# ── Market-level call requests ───────────────────────────────────────────────


@dataclass(kw_only=True)
class DepthReq:
  """Wire message for depth req."""

  id: str
  market_id: str
  levels: int | None = None
  settings: WireSettings = field(default_factory=Settings)
  tag: Literal['depth'] = 'depth'


@dataclass(kw_only=True)
class RulesReq:
  """Wire message for rules req."""

  id: str
  market_id: str
  refetch: bool = False
  tag: Literal['rules'] = 'rules'


@dataclass(kw_only=True)
class OpenOrdersReq:
  """Wire message for open orders req."""

  id: str
  market_id: str
  tag: Literal['open_orders'] = 'open_orders'


@dataclass(kw_only=True)
class QueryOrderReq:
  """Wire message for query order req."""

  id: str
  market_id: str
  order_id: str
  tag: Literal['query_order'] = 'query_order'


@dataclass(kw_only=True)
class TradesHistoryReq:
  """Wire message for trades history req."""

  id: str
  market_id: str
  start: datetime
  end: datetime
  tag: Literal['trades_history'] = 'trades_history'


@dataclass(kw_only=True)
class PositionReq:
  """Wire message for position req."""

  id: str
  market_id: str
  tag: Literal['position'] = 'position'


@dataclass(kw_only=True)
class AvailableNotionalReq:
  """Wire message for available notional req."""

  id: str
  market_id: str
  tag: Literal['available_notional'] = 'available_notional'


@dataclass(kw_only=True)
class PlaceOrderReq:
  """Wire message for place order req."""

  id: str
  market_id: str
  order: Order
  settings: WireSettings = field(default_factory=Settings)
  tag: Literal['place_order'] = 'place_order'


@dataclass(kw_only=True)
class CancelOrderReq:
  """Wire message for cancel order req."""

  id: str
  market_id: str
  order_id: str
  settings: WireSettings = field(default_factory=Settings)
  tag: Literal['cancel_order'] = 'cancel_order'


@dataclass(kw_only=True)
class CancelOpenOrdersReq:
  """Wire message for cancel open orders req."""

  id: str
  market_id: str
  settings: WireSettings = field(default_factory=Settings)
  tag: Literal['cancel_open_orders'] = 'cancel_open_orders'


@dataclass(kw_only=True)
class IndexReq:
  """Wire message for index req."""

  id: str
  market_id: str
  settings: WireSettings = field(default_factory=Settings)
  tag: Literal['index'] = 'index'


@dataclass(kw_only=True)
class NextFundingReq:
  """Wire message for next funding req."""

  id: str
  market_id: str
  tag: Literal['next_funding'] = 'next_funding'


@dataclass(kw_only=True)
class FundingRatesReq:
  """Wire message for funding rates req."""

  id: str
  market_id: str
  start: datetime | None = None
  end: datetime | None = None
  tag: Literal['funding_rates'] = 'funding_rates'


@dataclass(kw_only=True)
class FundingPaymentsReq:
  """Wire message for funding payments req."""

  id: str
  market_id: str
  start: datetime
  end: datetime
  tag: Literal['funding_payments'] = 'funding_payments'


@dataclass(kw_only=True)
class PerpPositionReq:
  """Wire message for perp position req."""

  id: str
  market_id: str
  tag: Literal['perp_position'] = 'perp_position'


@dataclass(kw_only=True)
class CollateralReq:
  """Wire message for collateral req."""

  id: str
  market_id: str
  tag: Literal['collateral'] = 'collateral'


@dataclass(kw_only=True)
class PerpCollateralReq:
  """Wire message for perp collateral req."""

  id: str
  market_id: str
  tag: Literal['perp_collateral'] = 'perp_collateral'


# ── Exchange-level call requests ─────────────────────────────────────────────


@dataclass(kw_only=True)
class ExchangePerpCollateralReq:
  """Wire message for exchange perp collateral req."""

  id: str
  venue_id: str
  exchange_id: str
  tag: Literal['exchange_perp_collateral'] = 'exchange_perp_collateral'


@dataclass(kw_only=True)
class MarketsReq:
  """Wire message for markets req."""

  id: str
  venue_id: str
  exchange_id: str
  tag: Literal['markets'] = 'markets'


# ── Venue-level call requests ────────────────────────────────────────────────


@dataclass(kw_only=True)
class ExchangesReq:
  """Wire message for exchanges req."""

  id: str
  venue_id: str
  tag: Literal['exchanges'] = 'exchanges'


# ── SDK-level call requests ──────────────────────────────────────────────────


@dataclass(kw_only=True)
class VenuesReq:
  """Wire message for venues req."""

  id: str
  tag: Literal['venues'] = 'venues'


# ── Market-level stream requests ─────────────────────────────────────────────


@dataclass(kw_only=True)
class DepthStreamReq:
  """Wire message for depth stream req."""

  id: str
  market_id: str
  levels: int | None = None
  queue_size: int = 1
  overflow: OverflowPolicy = 'latest'
  settings: WireSettings = field(default_factory=Settings)
  tag: Literal['depth_stream'] = 'depth_stream'


@dataclass(kw_only=True)
class TradesStreamReq:
  """Wire message for trades stream req."""

  id: str
  market_id: str
  queue_size: int = 1000
  overflow: OverflowPolicy = 'fail'
  tag: Literal['trades_stream'] = 'trades_stream'


# ── Control ──────────────────────────────────────────────────────────────────


@dataclass(kw_only=True)
class UnsubMsg:
  """Wire message for unsub msg."""

  id: str
  tag: Literal['unsub'] = 'unsub'


@dataclass(kw_only=True)
class FeesReq:
  """Fetch account-specific trading fees."""

  id: str
  market_id: str
  refetch: bool = False
  tag: Literal['fees'] = 'fees'


@dataclass(kw_only=True)
class CandlesReq:
  """Fetch candles in a half-open time window."""

  id: str
  market_id: str
  interval: CandleInterval
  start: datetime
  end: datetime
  tag: Literal['candles'] = 'candles'


@dataclass(kw_only=True)
class ExchangeReq:
  """Resolve an exchange's actual product type, including qualified IDs."""

  id: str
  venue_id: str
  exchange_id: str
  tag: Literal['exchange'] = 'exchange'


@dataclass(kw_only=True)
class TickersReq:
  """Fetch bulk tickers from an exchange."""

  id: str
  venue_id: str
  exchange_id: str
  markets: list[str] | None = None
  settings: WireSettings = field(default_factory=Settings)
  tag: Literal['tickers'] = 'tickers'


@dataclass(kw_only=True)
class PerpStatsReq:
  """Fetch bulk perpetual statistics."""

  id: str
  venue_id: str
  exchange_id: str
  markets: list[str] | None = None
  settings: WireSettings = field(default_factory=Settings)
  tag: Literal['perp_stats'] = 'perp_stats'


@dataclass(kw_only=True)
class ExchangeCollateralReq:
  """Fetch a spot or perpetual exchange's collateral bucket."""

  id: str
  venue_id: str
  exchange_id: str
  tag: Literal['exchange_collateral'] = 'exchange_collateral'


# ── Discriminated unions ─────────────────────────────────────────────────────

# Type aliases for annotations — not used as pydantic unions themselves
CallReq = (
  DepthReq
  | FeesReq
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
  | VenuesReq
)

StreamReq = DepthStreamReq | TradesStreamReq

ClientMsg = Annotated[
  DepthReq
  | FeesReq
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
  | VenuesReq
  | DepthStreamReq
  | TradesStreamReq
  | UnsubMsg,
  pydantic.Discriminator('tag'),
]

client_adapter: pydantic.TypeAdapter[ClientMsg] = pydantic.TypeAdapter(ClientMsg)


def encode_client(msg: ClientMsg) -> bytes:
  """Serialize a client request into a JSON frame."""
  return client_adapter.dump_json(msg)


def decode_client(data: str | bytes) -> ClientMsg:
  """Validate and decode a client JSON frame."""
  return client_adapter.validate_json(data)


# ── Call responses ───────────────────────────────────────────────────────────


@dataclass(kw_only=True)
class DepthResp:
  """Wire message for depth resp."""

  id: str
  book: Book
  tag: Literal['depth'] = 'depth'


@dataclass(kw_only=True)
class RulesResp:
  """Wire message for rules resp."""

  id: str
  rules: Rules
  tag: Literal['rules'] = 'rules'


@dataclass(kw_only=True)
class OpenOrdersResp:
  """Wire message for open orders resp."""

  id: str
  orders: Sequence[OrderState]
  tag: Literal['open_orders'] = 'open_orders'


@dataclass(kw_only=True)
class QueryOrderResp:
  """Wire message for query order resp."""

  id: str
  order: OrderState | None
  tag: Literal['query_order'] = 'query_order'


@dataclass(kw_only=True)
class TradesHistoryResp:
  """Wire message for trades history resp."""

  id: str
  trades: Sequence[Trade]
  tag: Literal['trades_history'] = 'trades_history'


@dataclass(kw_only=True)
class PositionResp:
  """Wire message for position resp."""

  id: str
  position: Position
  tag: Literal['position'] = 'position'


@dataclass(kw_only=True)
class AvailableNotionalResp:
  """Wire message for available notional resp."""

  id: str
  value: Decimal
  tag: Literal['available_notional'] = 'available_notional'


@dataclass(kw_only=True)
class PlaceOrderResp:
  """Wire message for place order resp."""

  id: str
  response: OrderResponse
  tag: Literal['place_order'] = 'place_order'


@dataclass(kw_only=True)
class CancelOrderResp:
  """Wire message for cancel order resp."""

  id: str
  result: Any
  tag: Literal['cancel_order'] = 'cancel_order'


@dataclass(kw_only=True)
class CancelOpenOrdersResp:
  """Wire message for cancel open orders resp."""

  id: str
  result: Any
  tag: Literal['cancel_open_orders'] = 'cancel_open_orders'


@dataclass(kw_only=True)
class IndexResp:
  """Wire message for index resp."""

  id: str
  value: Decimal
  tag: Literal['index'] = 'index'


@dataclass(kw_only=True)
class NextFundingResp:
  """Wire message for next funding resp."""

  id: str
  rate: NextFunding
  tag: Literal['next_funding'] = 'next_funding'


@dataclass(kw_only=True)
class FundingRatesResp:
  """Wire message for funding rates resp."""

  id: str
  rates: Sequence[FundingRate]
  tag: Literal['funding_rates'] = 'funding_rates'


@dataclass(kw_only=True)
class FundingPaymentsResp:
  """Wire message for funding payments resp."""

  id: str
  payments: Sequence[FundingPayment]
  tag: Literal['funding_payments'] = 'funding_payments'


@dataclass(kw_only=True)
class PerpPositionResp:
  """Wire message for perp position resp."""

  id: str
  position: PerpPosition
  tag: Literal['perp_position'] = 'perp_position'


@dataclass(kw_only=True)
class CollateralResp:
  """Wire message for collateral resp."""

  id: str
  collateral: PerpCollateral | Collateral
  tag: Literal['collateral'] = 'collateral'


@dataclass(kw_only=True)
class PerpCollateralResp:
  """Wire message for perp collateral resp."""

  id: str
  collateral: PerpCollateral
  tag: Literal['perp_collateral'] = 'perp_collateral'


@dataclass(kw_only=True)
class MarketsResp:
  """Wire message for markets resp."""

  id: str
  markets: Sequence[str]
  tag: Literal['markets'] = 'markets'


@dataclass(kw_only=True)
class ExchangesResp:
  """Wire message for exchanges resp."""

  id: str
  exchanges: Sequence[ExchangeDescription]
  tag: Literal['exchanges'] = 'exchanges'


@dataclass(kw_only=True)
class VenuesResp:
  """Wire message for venues resp."""

  id: str
  venues: Sequence[str]
  tag: Literal['venues'] = 'venues'


# ── Stream data messages ──────────────────────────────────────────────────────


@dataclass(kw_only=True)
class DepthDataMsg:
  """Wire message for depth data msg."""

  id: str
  book: Book
  tag: Literal['depth_data'] = 'depth_data'


@dataclass(kw_only=True)
class TradesDataMsg:
  """Wire message for trades data msg."""

  id: str
  trade: Trade
  tag: Literal['trades_data'] = 'trades_data'


# ── Control ───────────────────────────────────────────────────────────────────


@dataclass(kw_only=True)
class ErrMsg:
  """Wire message for err msg."""

  id: str
  error: str
  exc: str | None = None
  tag: Literal['err'] = 'err'


@dataclass(kw_only=True)
class EndMsg:
  """Wire message for end msg."""

  id: str
  exc: str | None = None
  error: str | None = None
  tag: Literal['end'] = 'end'


@dataclass(kw_only=True)
class FeesResp:
  """Account fee schedule."""

  id: str
  fees: Fees
  tag: Literal['fees'] = 'fees'


@dataclass(kw_only=True)
class CandlesResp:
  """Historical candles, preserving the SDK's value types."""

  id: str
  candles: Sequence[Candle]
  tag: Literal['candles'] = 'candles'


@dataclass(kw_only=True)
class ExchangeResp:
  """Resolved exchange product type."""

  id: str
  type: Literal['spot', 'perp']
  tag: Literal['exchange'] = 'exchange'


@dataclass(kw_only=True)
class TickersResp:
  """Tickers keyed by native market ID."""

  id: str
  tickers: dict[str, Ticker]
  tag: Literal['tickers'] = 'tickers'


@dataclass(kw_only=True)
class PerpStatsResp:
  """Perpetual statistics keyed by native market ID."""

  id: str
  stats: dict[str, PerpStats]
  tag: Literal['perp_stats'] = 'perp_stats'


ServerMsg = Annotated[
  DepthResp
  | FeesResp
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
  | VenuesResp
  | DepthDataMsg
  | TradesDataMsg
  | ErrMsg
  | EndMsg,
  pydantic.Discriminator('tag'),
]

server_adapter: pydantic.TypeAdapter[ServerMsg] = pydantic.TypeAdapter(ServerMsg)


def encode_server(msg: ServerMsg) -> bytes:
  """Serialize a server response into a JSON frame."""
  return server_adapter.dump_json(msg)


def decode_server(data: str | bytes) -> ServerMsg:
  """Validate and decode a server JSON frame."""
  return server_adapter.validate_json(data)
