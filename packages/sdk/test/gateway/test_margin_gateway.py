"""Margin exchanges cross the gateway as their own kind (ADR 0073)."""

from datetime import datetime, timezone
from decimal import Decimal
from typing_extensions import Any, cast

import pytest

from tribulnation.sdk.gateway import codec
from tribulnation.sdk.gateway.proxy import (
  ProxyMarginExchange,
  ProxyMarginMarket,
  ProxyPerpExchange,
  ProxySpotExchange,
  resolve_exchange,
)
from tribulnation.sdk.gateway.server import wire_kind
from tribulnation.sdk.market import (
  MarginExchange,
  PerpExchange,
  Position,
  SpotExchange,
  is_margin,
)

T = datetime(2026, 11, 21, tzinfo=timezone.utc)


class FakeConnection:
  """Answers each request from a table, keeping what was sent."""

  def __init__(self, *replies: Any):
    self.replies = list(replies)
    self.sent: list[codec.CallReq] = []

  async def call(self, req: codec.CallReq) -> Any:
    """Record the request and answer the next reply."""
    self.sent.append(req)
    return self.replies.pop(0)


@pytest.mark.parametrize(
  ('kind', 'cls'),
  [
    ('spot', ProxySpotExchange),
    ('margin', ProxyMarginExchange),
    ('perp', ProxyPerpExchange),
  ],
)
async def test_resolution_builds_the_reported_kind(kind: Any, cls: type):
  """`ExchangeResp.type` picks the proxy class, so a margin exchange is not spot."""
  conn = FakeConnection(codec.ExchangeResp(id='e', type=kind, venue_id='bitget'))
  exchange = await resolve_exchange(
    cast(Any, conn), {}, account_id='bitget', exchange_id='x'
  )
  assert type(exchange) is cls
  assert exchange.kind == kind


def test_server_reports_kind_by_class():
  """The gateway tells kinds apart by class, perpetual before margin."""
  margin = object.__new__(ProxyMarginExchange)
  perp = object.__new__(ProxyPerpExchange)
  spot = object.__new__(ProxySpotExchange)
  assert isinstance(margin, MarginExchange) and isinstance(perp, PerpExchange)
  assert isinstance(spot, SpotExchange)
  assert (wire_kind(spot), wire_kind(margin), wire_kind(perp)) == (
    'spot',
    'margin',
    'perp',
  )


async def test_margin_market_reads_position_through_the_gateway():
  """A margin market proxies the margin reads a perpetual has, by market ID."""
  conn = FakeConnection(codec.PositionResp(id='p', position=Position(size=Decimal(-5))))
  exchange = ProxyMarginExchange(cast(Any, conn), 'bitget', 'margin', 'bitget')
  market = await exchange.market('LITUSDT')
  assert isinstance(market, ProxyMarginMarket) and is_margin(market)
  assert market.kind == 'margin'
  assert (await market.position()).size == Decimal(-5)
  req = conn.sent[0]
  assert isinstance(req, codec.PositionReq) and req.market_id == 'bitget:margin:LITUSDT'


def test_interest_is_not_carried_by_protocol_v2():
  """Interest needs a direct SDK until the protocol carries it."""
  market = ProxyMarginMarket(
    cast(Any, FakeConnection()), 'bitget', 'margin', 'LITUSDT', 'bitget'
  )
  with pytest.raises(NotImplementedError, match='not carried'):
    market.interest_payments(T, T)
