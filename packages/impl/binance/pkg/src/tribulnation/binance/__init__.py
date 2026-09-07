"""Binance implementation of the Tribulnation SDK."""

from typing_extensions import Sequence
from dataclasses import dataclass as _dataclass, field as _field

from typed_binance import Binance as _Client

from .core import SdkMixin
from .earn import Earn
from .wallet import Wallet
from .reporting import Reporting
from .market import BinanceMarket


@_dataclass
class Binance(SdkMixin):
  """Every Binance SDK surface, sharing one client."""

  spot_markets: Sequence[str] = ()
  """Spot symbols `reporting.history` sweeps for fills. See `Reporting`."""
  usdm_markets: Sequence[str] = ()
  """USD-M perpetual symbols `reporting.history` sweeps for fills. See `Reporting`."""

  earn: Earn = _field(init=False)
  wallet: Wallet = _field(init=False)
  reporting: Reporting = _field(init=False)

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
    """Create every Binance surface over a new client.

    Args:
      api_key: Binance API key. Defaults to `BINANCE_API_KEY`.
      secret_key: Binance API secret. Defaults to `BINANCE_SECRET_KEY`.
      validate: Validate responses against the typed client's schemas.
      spot_markets: Spot symbols `reporting.history` sweeps for fills.
      usdm_markets: USD-M perpetual symbols `reporting.history` sweeps for fills.
    """
    client = _Client.new(api_key=api_key, secret_key=secret_key, validate=validate)
    return cls(
      client=client,
      validate=validate,
      spot_markets=spot_markets,
      usdm_markets=usdm_markets,
    )

  def __post_init__(self):
    self.earn = Earn(self.client, validate=self.validate)
    self.wallet = Wallet(self.client, validate=self.validate)
    self.reporting = Reporting(
      self.client,
      validate=self.validate,
      spot_markets=self.spot_markets,
      usdm_markets=self.usdm_markets,
    )
