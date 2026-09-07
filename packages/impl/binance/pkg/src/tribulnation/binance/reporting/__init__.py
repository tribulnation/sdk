"""Binance reporting: transaction history and balance/position snapshots."""

from typing_extensions import Sequence
from dataclasses import dataclass

from tribulnation.sdk.reporting import Report as _Report
from typed_binance import Binance as _Client

from .history import History
from .snapshots import Snapshots


@dataclass
class Reporting(_Report, History, Snapshots):
  """Reporting surface for one Binance account."""

  @classmethod
  def new(
    cls,
    api_key: str | None = None,
    secret_key: str | None = None,
    *,
    validate: bool = True,
    spot_markets: Sequence[str] = (),
    usdm_markets: Sequence[str] = (),
  ):
    """Create a reporting surface over a new Binance client.

    Args:
      api_key: Binance API key. Defaults to `BINANCE_API_KEY`.
      secret_key: Binance API secret. Defaults to `BINANCE_SECRET_KEY`.
      validate: Validate responses against the typed client's schemas.
      spot_markets: Spot symbols `history` sweeps for fills.
      usdm_markets: USD-M perpetual symbols `history` sweeps for fills.
    """
    client = _Client.new(api_key=api_key, secret_key=secret_key, validate=validate)
    return cls(
      client=client,
      validate=validate,
      spot_markets=spot_markets,
      usdm_markets=usdm_markets,
    )
