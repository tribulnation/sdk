"""Binance spot-side history and balance snapshots; futures are excluded."""

from dataclasses import dataclass

from tribulnation.sdk.reporting import Report as _Report
from typed_binance import Binance as _Client

from .history import History
from .snapshots import Snapshots


@dataclass
class Reporting(_Report, History, Snapshots):
  """Spot, Funding and Simple Earn reporting for one Binance account."""

  @classmethod
  def new(
    cls,
    api_key: str | None = None,
    secret_key: str | None = None,
    *,
    validate: bool = True,
  ):
    """Create a reporting surface over a new Binance client.

    Args:
      api_key: Binance API key. Defaults to `BINANCE_API_KEY`.
      secret_key: Binance API secret. Defaults to `BINANCE_SECRET_KEY`.
      validate: Validate responses against the typed client's schemas.
    """
    client = _Client.new(api_key=api_key, secret_key=secret_key, validate=validate)
    return cls(
      client=client,
      validate=validate,
    )
