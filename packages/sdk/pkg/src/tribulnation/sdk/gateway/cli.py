"""CLI command: ``tn gateway`` — start the standalone gateway process."""

from typing_extensions import Annotated
from pathlib import Path
import asyncio
import logging

import typer

app = typer.Typer()

_GATEWAY_LOGGERS = ('tribulnation.sdk.gateway.server',)

_FMT = '%(asctime)s  %(name)-40s  %(message)s'
_DATEFMT = '%H:%M:%S'


@app.command()
def gateway(
  socket: Annotated[
    str | None,
    typer.Option(
      '--socket',
      '-s',
      help='Unix socket path (overrides gateway.socket).',
    ),
  ] = None,
  config: Annotated[
    Path, typer.Option('--config', '-c', help='Path to TOML config file.')
  ] = Path('sdk.toml'),
  verbose: Annotated[
    int,
    typer.Option(
      '--verbose',
      '-v',
      count=True,
      help='Increase log verbosity. Repeat for all debug output.',
    ),
  ] = 0,
):
  """Start the WebSocket gateway on a Unix socket."""
  try:
    from dotenv import load_dotenv
    from tribulnation.sdk import MarketSDK
    from tribulnation.sdk.gateway.server import run_gateway
  except ImportError as error:
    raise typer.BadParameter(
      'Install gateway dependencies with: pip install "tribulnation-sdk[gateway]"'
    ) from error

  from .config import gateway_socket

  _configure_logging(verbose)
  load_dotenv(config.parent / '.env')
  sdk = MarketSDK.load(config)
  sock = socket or gateway_socket(config)
  asyncio.run(run_gateway(sock, sdk))


def _configure_logging(verbose: int):
  """Apply the requested gateway verbosity."""
  if verbose >= 2:
    logging.basicConfig(level=logging.DEBUG, format=_FMT, datefmt=_DATEFMT)
  elif verbose:
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(_FMT, datefmt=_DATEFMT))
    root = logging.getLogger()
    root.setLevel(logging.WARNING)
    root.addHandler(handler)
    for name in _GATEWAY_LOGGERS:
      logging.getLogger(name).setLevel(logging.DEBUG)
