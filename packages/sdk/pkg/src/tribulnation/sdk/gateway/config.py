"""Read SDK gateway socket configuration."""

from pathlib import Path
import sys

if sys.version_info >= (3, 11):
  import tomllib
else:
  import tomli as tomllib


DEFAULT_SOCKET = '/tmp/tribulnation-sdk.sock'


def gateway_socket(path: Path) -> str:
  """Read gateway.socket or use the SDK default."""
  with path.open('rb') as stream:
    data = tomllib.load(stream)
  gateway = data.get('gateway', {})
  socket = gateway.get('socket', DEFAULT_SOCKET)
  if not isinstance(socket, str) or not socket:
    raise ValueError('Gateway socket must be a non-empty string')
  return socket
