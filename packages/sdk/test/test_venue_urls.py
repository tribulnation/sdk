"""Venue URL fields in `[accounts.<id>]` reach the typed clients' transports; unset
fields keep each venue's default."""

from pathlib import Path

import pytest

from tribulnation.sdk import MarketSDK

MISSING = '$SDK_TEST_MISSING'
"""An unset variable: a public account without credentials."""
FAKE = 'http://127.0.0.1:18080'
FAKE_WS = 'ws://127.0.0.1:18080'

CONFIG = f"""
[accounts.aster]
venue = "aster"
public = true
rest_url = "{FAKE}/fapi/v3"
ws_url = "{FAKE_WS}/stream"
user_stream_url = "$SDK_TEST_ASTER_USER_STREAM"

[accounts.hl]
venue = "hyperliquid"
public = true
address = "$SDK_TEST_MISSING"
private_key = "$SDK_TEST_MISSING"
rest_url = "{FAKE}"
ws_url = "{FAKE_WS}/ws"

[accounts.lighter]
venue = "lighter_testnet"
public = true
rest_url = "{FAKE}"
ws_url = "{FAKE_WS}/stream"

[accounts.binance]
venue = "binance"
public = true
api_key = "$SDK_TEST_MISSING"
secret_key = "$SDK_TEST_MISSING"
rest_url = "{FAKE}"
ws_url = "{FAKE_WS}/market/stream"
public_ws_url = "{FAKE_WS}/public/stream"
user_stream_url = "{FAKE_WS}/private/ws"
ws_api_url = "{FAKE_WS}/ws-fapi/v1"

[accounts.dydx]
venue = "dydx"
public = true
address = "$SDK_TEST_MISSING"
indexer_rest_url = "{FAKE}"
indexer_ws_url = "{FAKE_WS}/v4/ws"
validator_grpc = "127.0.0.1:19090"
validator_rpc = "{FAKE}"
"""


@pytest.fixture
def sdk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> MarketSDK:
  """A `MarketSDK` loaded from `CONFIG`."""
  monkeypatch.delenv('SDK_TEST_MISSING', raising=False)
  monkeypatch.setenv('SDK_TEST_ASTER_USER_STREAM', f'{FAKE_WS}/ws')
  path = tmp_path / 'sdk.toml'
  path.write_text(CONFIG)
  return MarketSDK.load(path)


async def test_aster_urls(sdk: MarketSDK):
  """Futures REST, market stream and user stream (from an env var) use the config."""
  from tribulnation.aster import AsterMarket
  from typed_aster.core.urls import rest_url

  venue = await sdk.venue('aster')
  assert isinstance(venue, AsterMarket)
  futures = venue.client.futures_clients
  assert futures.client.base_url == f'{FAKE}/fapi/v3'
  assert futures.streams_client.conn.url == f'{FAKE_WS}/stream'
  assert futures.user_stream_client.base_url == f'{FAKE_WS}/ws'
  assert venue.client.spot_clients.client.base_url == rest_url('spot', mainnet=True)


async def test_hyperliquid_urls(sdk: MarketSDK):
  """Info/exchange HTTP and the shared WebSocket use the config."""
  from tribulnation.hyperliquid import HyperliquidMarket

  venue = await sdk.venue('hl')
  assert isinstance(venue, HyperliquidMarket)
  client = venue.shared.client
  assert client.info_client.base_url == FAKE
  assert client.exchange_client.base_url == FAKE
  assert client.streams_client.url == f'{FAKE_WS}/ws'


async def test_lighter_urls(sdk: MarketSDK):
  """REST and stream use the config; the chain id stays testnet's."""
  from tribulnation.lighter import LighterMarket
  from typed_lighter.core.networks import NETWORKS

  venue = await sdk.venue('lighter')
  assert isinstance(venue, LighterMarket)
  client = venue.shared.client
  assert client.http.base_url == FAKE
  assert client.ws.conn.url == f'{FAKE_WS}/stream'
  assert client.network.chain_id == NETWORKS['testnet'].chain_id


async def test_binance_urls(sdk: MarketSDK):
  """Every USDⓈ-M futures transport uses the config; spot keeps its default."""
  from tribulnation.binance import BinanceMarket
  from typed_binance.core.urls import SPOT_URL

  venue = await sdk.venue('binance')
  assert isinstance(venue, BinanceMarket)
  usdm = venue.shared.client.usdm_futures_clients
  assert usdm.http_client.base_url == FAKE
  assert usdm.streams_client.conn.url == f'{FAKE_WS}/market/stream'
  assert usdm.public_streams_client.conn.url == f'{FAKE_WS}/public/stream'
  assert usdm.private_streams_client.base_url == f'{FAKE_WS}/private/ws'
  assert usdm.ws_client.conn.url == f'{FAKE_WS}/ws-fapi/v1'
  assert venue.shared.client.spot_clients.http_client.base_url == SPOT_URL


async def test_dydx_urls(sdk: MarketSDK):
  """Indexer HTTP/WS, chain gRPC (order broadcast included) and Comet use the config."""
  from tribulnation.dydx import DydxMarket

  venue = await sdk.venue('dydx')
  assert isinstance(venue, DydxMarket)
  client = venue.client
  assert client.indexer_http_client.url == FAKE
  assert client.indexer_ws_client.url == f'{FAKE_WS}/v4/ws'
  grpc = client.chain_grpc_client
  assert (grpc.host, grpc.port, grpc.ssl) == ('127.0.0.1', 19090, False)
  assert client.chain_comet_client.base_url == FAKE
  assert client.node.chain.grpc_client is grpc


async def test_unset_urls_keep_defaults(monkeypatch: pytest.MonkeyPatch):
  """Accounts without URL fields build today's default transports."""
  monkeypatch.delenv('SDK_TEST_MISSING', raising=False)
  from tribulnation.aster import AsterMarket
  from tribulnation.binance import BinanceMarket
  from tribulnation.dydx import DydxMarket
  from tribulnation.hyperliquid import HyperliquidMarket
  from tribulnation.sdk.impl import accounts
  from typed_aster.core.urls import rest_url
  from typed_binance.core.urls import USDM_FUTURES_STREAM_URL, USDM_FUTURES_URL
  from typed_dydx.chain.core import DYDX_GRPC_OEGS_HOST
  from typed_dydx.indexer.data.core import INDEXER_HTTP_URL
  from typed_hyperliquid.core.urls import http_base_url

  sdk = MarketSDK(
    accounts={
      'aster': accounts.Aster(public=True),
      'binance': accounts.Binance(public=True, api_key=MISSING, secret_key=MISSING),
      'dydx': accounts.Dydx(public=True, address=MISSING),
      'hl': accounts.Hyperliquid(public=True, address=MISSING, private_key=MISSING),
    }
  )
  aster = await sdk.venue('aster')
  assert isinstance(aster, AsterMarket)
  assert aster.client.futures_clients.client.base_url == rest_url(
    'futures', mainnet=True
  )
  binance = await sdk.venue('binance')
  assert isinstance(binance, BinanceMarket)
  usdm = binance.shared.client.usdm_futures_clients
  assert usdm.http_client.base_url == USDM_FUTURES_URL
  assert usdm.streams_client.conn.url == USDM_FUTURES_STREAM_URL
  dydx = await sdk.venue('dydx')
  assert isinstance(dydx, DydxMarket)
  assert dydx.client.indexer_http_client.url == INDEXER_HTTP_URL
  assert dydx.client.chain_grpc_client.host == DYDX_GRPC_OEGS_HOST
  hl = await sdk.venue('hl')
  assert isinstance(hl, HyperliquidMarket)
  assert hl.shared.client.info_client.base_url == http_base_url(True)


def test_dydx_validator_needs_both_endpoints():
  """A gRPC host without its RPC URL is rejected rather than half-applied."""
  from tribulnation.dydx import DydxMarket

  with pytest.raises(ValueError, match='validator_grpc'):
    DydxMarket.new(public=True, address='dydx1x', validator_grpc='127.0.0.1:9090')
