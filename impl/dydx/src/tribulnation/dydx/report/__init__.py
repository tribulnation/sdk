"""dYdX SDK reporting surfaces."""
from typing_extensions import TypedDict
from dataclasses import dataclass

from tribulnation.sdk.reporting import Report as _Report

from dydx import Dydx
from dydx.chain import (
  Chain,
  DYDX_COMET_KINGNODES_ARCHIVE_RPC_URL,
  DYDX_GRPC_KINGNODES_ARCHIVE_HOST,
  DYDX_TESTNET_COMET_KINGNODES_RPC_URL,
  DYDX_TESTNET_GRPC_KINGNODES_HOST,
)
from .history import History
from .snapshots import Snapshots

class Settings(TypedDict, total=False):
  validate: bool
  comet_base_url: str | None
  grpc_host: str | None
  grpc_port: int
  grpc_ssl: bool

@dataclass(frozen=True)
class Reporting(Snapshots, History, _Report):
  """dYdX reporting client with snapshots and history."""
  
  @classmethod
  def new(
    cls, address: str | None = None, *,
    validate: bool = True, mainnet: bool = True,
    comet_base_url: str | None = None,
    grpc_host: str | None = None,
    grpc_port: int = 443,
    grpc_ssl: bool = True,
  ):
    """Create a dYdX reporting snapshot client."""
    import os
    if address is None:
      address = os.environ['DYDX_ADDRESS']
    
    if mainnet:
      comet_base_url = comet_base_url or os.environ.get('DYDX_COMET_RPC_URL') or DYDX_COMET_KINGNODES_ARCHIVE_RPC_URL
      grpc_host = grpc_host or os.environ.get('DYDX_GRPC_HOST') or DYDX_GRPC_KINGNODES_ARCHIVE_HOST
    else:
      comet_base_url = comet_base_url or os.environ.get('DYDX_TESTNET_COMET_RPC_URL') or DYDX_TESTNET_COMET_KINGNODES_RPC_URL
      grpc_host = grpc_host or os.environ.get('DYDX_TESTNET_GRPC_HOST') or DYDX_TESTNET_GRPC_KINGNODES_HOST

    chain = Chain.new(
      comet_base_url=comet_base_url,
      grpc_host=grpc_host,
      grpc_port=grpc_port,
      grpc_ssl=grpc_ssl,
      validate=validate,
    )
    client = Dydx.new(chain=chain, public=True)
    return cls(address=address, client=client)
