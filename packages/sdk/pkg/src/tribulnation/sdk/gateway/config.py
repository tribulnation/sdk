"""Read gateway socket configuration without importing engine configuration."""

from pathlib import Path
import sys

if sys.version_info >= (3, 11):
  import tomllib
else:
  import tomli as tomllib


def gateway_socket(path: Path) -> str:
  """Prefer gateway.socket, accepting legacy engine daemon.socket."""
  with path.open('rb') as stream:
    data = tomllib.load(stream)
  gateway = data.get('gateway', {})
  daemon = data.get('daemon', {})
  socket = gateway.get('socket', daemon.get('socket', '/tmp/engine-gateway.sock'))
  if not isinstance(socket, str) or not socket:
    raise ValueError('Gateway socket must be a non-empty string')
  return socket
