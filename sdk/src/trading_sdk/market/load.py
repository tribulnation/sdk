from dataclasses import dataclass, field
from typing_extensions import Literal

from mexc_sdk import MEXC
from dydx_sdk import DYDX
from hyperliquid_sdk import Hyperliquid

from trading_sdk.core import UserError

from . import Market

MarketType = Literal['spot', 'perp']

@dataclass
class Markets:
  """Market loader with manual, in-memory caching."""

  _mexc: MEXC | None = field(default=None, init=False, repr=False)
  _dydx: DYDX | None = field(default=None, init=False, repr=False)
  _hyperliquid: Hyperliquid | None = field(default=None, init=False, repr=False)
  _hyperliquid_spot: Hyperliquid.Spot | None = field(default=None, init=False, repr=False)
  _hyperliquid_perp: dict[str | None, Hyperliquid.Perp] = field(default_factory=dict, init=False, repr=False)

  _spot_cache: dict[tuple[str, str], Market] = field(default_factory=dict, init=False, repr=False)
  _perp_cache: dict[tuple[str, str], Market] = field(default_factory=dict, init=False, repr=False)

  async def market(self, spec: str) -> Market:
    """Load a market from a specification string.

    Format: `<venue>:<spot|perp>:<instrument_id>`

    Examples:
    - `mexc:spot:BTCUSDT`
    - `mexc:perp:BTC_USDT`
    - `dydx:perp:BTC-USD`
    - `hyperliquid:perp:BTC`
    - `hyperliquid:perp:xyz:BTC`
    """
    venue, market_type, instrument_id = spec.split(':', 2)
    if market_type == 'spot':
      return await self.spot(venue, instrument_id)
    elif market_type == 'perp':
      return await self.perpetual(venue, instrument_id)
    else:
      raise UserError(f'Unsupported market type: {market_type!r}')

  async def spot(self, platfrom: str, instrument: str) -> Market:
    """Load a spot market.

    Formats:
    - mexc: ``BTCUSDT``
    - hyperliquid: ``BASE/QUOTE`` or ``BASE/QUOTE:INDEX`` (e.g. ``UBTC/USDC:142``)
    - dydx: not supported (raises)
    """
    cache_key = (platfrom, instrument)
    cached = self._spot_cache.get(cache_key)
    if cached is not None:
      return cached

    if platfrom == 'mexc':
      mexc = self._mexc_sdk()
      market = await mexc.spot(instrument)
    elif platfrom == 'hyperliquid':
      base, quote, index = self._parse_hyperliquid_spot_instrument(instrument)
      market = await self._hyperliquid_spot_market(base, quote, index)
    elif platfrom == 'dydx':
      raise UserError('dYdX does not support spot markets.')
    else:
      raise UserError(f'Unsupported platform for spot: {platfrom!r}')

    self._spot_cache[cache_key] = market
    return market

  async def perpetual(self, platfrom: str, instrument: str) -> Market:
    """Load a perpetual market.

    Formats:
    - mexc: ``BTC_USDT``
    - dydx: ``SUBACCOUNT:MARKET`` or ``MARKET`` (e.g. ``128:BTC-USD``)
    - hyperliquid: ``DEX:BASE`` or ``BASE`` (e.g. ``xyz:BTC`` or ``BTC``)
    """
    cache_key = (platfrom, instrument)
    cached = self._perp_cache.get(cache_key)
    if cached is not None:
      return cached

    if platfrom == 'mexc':
      mexc = self._mexc_sdk()
      market = await mexc.perp(instrument)
    elif platfrom == 'dydx':
      subaccount, market_id = self._parse_dydx_perp_instrument(instrument)
      market = await self._dydx_market(market_id, subaccount=subaccount)
    elif platfrom == 'hyperliquid':
      dex, base = self._parse_hyperliquid_perp_instrument(instrument)
      market = await self._hyperliquid_perp_market(base=base, dex=dex)
    else:
      raise UserError(f'Unsupported platform for perpetual: {platfrom!r}')

    self._perp_cache[cache_key] = market
    return market

  def _mexc_sdk(self) -> MEXC:
    if self._mexc is None:
      self._mexc = MEXC.new(None, None)
    return self._mexc

  async def _dydx_sdk(self) -> DYDX:
    if self._dydx is None:
      self._dydx = await DYDX.connect(mnemonic=None)
    return self._dydx

  async def _dydx_market(self, market: str, *, subaccount: int = 0) -> Market:
    dydx_client = await self._dydx_sdk()
    return await dydx_client.market(market, subaccount=subaccount)

  def _hyperliquid_sdk(self) -> Hyperliquid:
    if self._hyperliquid is None:
      self._hyperliquid = Hyperliquid.new(
        address=None,
        wallet=None,
      )
    return self._hyperliquid

  async def _hyperliquid_spot_client(self):
    if self._hyperliquid_spot is None:
      self._hyperliquid_spot = await self._hyperliquid_sdk().spot()
    return self._hyperliquid_spot

  async def _hyperliquid_perp_client(self, dex: str | None):
    if dex not in self._hyperliquid_perp:
      self._hyperliquid_perp[dex] = await self._hyperliquid_sdk().perp(dex)
    return self._hyperliquid_perp[dex]

  async def _hyperliquid_spot_market(
    self,
    base: str,
    quote: str,
    index: int | None,
  ) -> Market:
    spot = await self._hyperliquid_spot_client()
    market = spot.find(base, quote)
    if index is not None and market.asset_idx != index:
      raise ValueError(
        f"Expected market {base}/{quote} at index {index}, got {market.base_name}/{market.quote_name}",
      )
    return market

  async def _hyperliquid_perp_market(self, *, base: str, dex: str | None) -> Market:
    perp = await self._hyperliquid_perp_client(dex)
    if dex:
      base = f'{dex}:{base}'
    return perp.find(base)

  @staticmethod
  def _parse_hyperliquid_spot_instrument(instrument: str) -> tuple[str, str, int | None]:
    if ':' in instrument:
      ticker, index_str = instrument.split(':', 1)
      index = int(index_str)
    else:
      ticker, index = instrument, None
    base, quote = ticker.split('/', 1)
    return base, quote, index

  @staticmethod
  def _parse_hyperliquid_perp_instrument(instrument: str) -> tuple[str | None, str]:
    if ':' in instrument:
      dex, base = instrument.split(':', 1)
      dex = dex or None
      return dex, base
    return None, instrument

  @staticmethod
  def _parse_dydx_perp_instrument(instrument: str) -> tuple[int, str]:
    if ':' in instrument:
      subaccount_str, market = instrument.split(':', 1)
      return int(subaccount_str), market
    return 0, instrument
