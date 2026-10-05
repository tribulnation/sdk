"""Gateway ownership, packaging and SDK configuration regressions."""

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import sys

from aiohttp import web
import pytest
from typer.testing import CliRunner

from tribulnation.sdk import TradingMarkets
from tribulnation.sdk.gateway import codec
from tribulnation.sdk.gateway.cli import app
from tribulnation.sdk.gateway.config import gateway_socket
from tribulnation.sdk.gateway.server import gateway_app


def test_codec_does_not_import_optional_venues():
  """Remote clients only need the gateway extra, not local venue drivers."""
  result = subprocess.run(
    [
      sys.executable,
      '-c',
      """
import sys
from tribulnation.sdk.gateway import ProxySDK, Gateway
from tribulnation.sdk.gateway import codec
for module in sys.modules:
    assert not module.startswith(('tribulnation.dydx',
                                  'tribulnation.hyperliquid', 'tribulnation.lighter'))
""",
    ],
    capture_output=True,
    text=True,
  )
  assert result.returncode == 0, result.stderr


def test_settings_preserve_wire_values_and_new_venue_keys():
  """Transport settings opaquely without dropping Lighter or future venue keys."""
  wire = {
    'tag': 'place_order',
    'id': 'request',
    'market_id': 'hl:perp:BTC',
    'order': {
      'type': 'LIMIT',
      'price': '100.5',
      'qty': '2',
      'client_order_id': 'client-id',
    },
    'settings': {
      'dydx': {'flags': 64, 'tif': 1, 'reduce_only': True},
      'hyperliquid': {'limit_tif': 'Alo'},
      'lighter': {'reduce_only': True},
      'future_venue': {'custom_flag': 3},
    },
  }
  request = codec.decode_client(json.dumps(wire))
  assert isinstance(request, codec.PlaceOrderReq)
  assert request.order['price'] == Decimal('100.5')
  assert request.settings == wire['settings']
  encoded = json.loads(codec.encode_client(request))
  assert encoded['settings'] == wire['settings']
  assert encoded['order']['client_order_id'] == 'client-id'


@pytest.mark.parametrize(
  ('contents', 'expected'),
  [
    ('', '/tmp/tribulnation-sdk.sock'),
    (
      '[gateway]\nsocket="/tmp/sdk.sock"',
      '/tmp/sdk.sock',
    ),
  ],
)
def test_socket_configuration(tmp_path: Path, contents: str, expected: str):
  """Read SDK socket configuration and its default."""
  path = tmp_path / 'sdk.toml'
  path.write_text(contents)
  assert gateway_socket(path) == expected


def test_cli_defaults_overrides_and_account_loading(tmp_path: Path, monkeypatch):
  """Keep CLI aliases, verbosity, account loading and socket override."""
  from tribulnation.sdk.gateway import server

  seen = []

  async def run_gateway(socket_path, sdk):
    """Capture startup without connecting to a venue."""
    seen.append((socket_path, sdk))

  monkeypatch.setattr(server, 'run_gateway', run_gateway)
  monkeypatch.chdir(tmp_path)
  (tmp_path / 'sdk.toml').write_text(
    '[gateway]\nsocket="/tmp/sdk.sock"\n[accounts.observer]\nvenue="hyperliquid"\npublic=true\n'
  )
  runner = CliRunner()
  result = runner.invoke(app, [])
  assert result.exit_code == 0, result.output
  assert seen[-1][0] == '/tmp/sdk.sock'
  assert seen[-1][1].accounts['observer'].public
  (tmp_path / 'custom.toml').write_text('[gateway]\nsocket="/tmp/configured.sock"\n')
  result = runner.invoke(app, ['-c', 'custom.toml', '-s', '/tmp/override.sock', '-vv'])
  assert result.exit_code == 0, result.output
  assert seen[-1][0] == '/tmp/override.sock'


@dataclass
class OwnedSDK(TradingMarkets):
  """Record the SDK's resource ownership around the server lifetime."""

  events: list[str] = field(default_factory=list)

  async def venues(self):
    """List no venues for this lifecycle fixture."""
    return []

  async def venue(self, id):
    """Reject venue access in this lifecycle fixture."""
    raise NotImplementedError

  def resources(self):
    """Expose one observable resource."""

    @asynccontextmanager
    async def resource():
      """Record acquisition and release."""
      self.events.append('enter')
      try:
        yield
      finally:
        self.events.append('exit')

    yield resource()


async def test_application_owns_injected_sdk():
  """The gateway acquires resources before serving and releases them once."""
  sdk = OwnedSDK()
  runner = web.AppRunner(gateway_app(sdk))
  await runner.setup()
  assert sdk.events == ['enter']
  await runner.cleanup()
  assert sdk.events == ['enter', 'exit']


def test_proxy_uses_sdk_socket_default():
  """Keep the remote client default aligned with CLI configuration."""
  from tribulnation.sdk.gateway import ProxySDK
  from tribulnation.sdk.gateway.config import DEFAULT_SOCKET

  assert ProxySDK.at()._conn.url == f'unix://{DEFAULT_SOCKET}'


@pytest.mark.parametrize('value', ['42', '""'])
def test_socket_rejects_invalid_values(tmp_path: Path, value: str):
  """Reject non-string or empty socket settings."""
  path = tmp_path / 'sdk.toml'
  path.write_text(f'[gateway]\nsocket={value}\n')
  with pytest.raises(ValueError, match='non-empty string'):
    gateway_socket(path)
