from typing_extensions import Sequence
from dataclasses import dataclass

from trading_sdk.market import Exchange as _Exchange

from .impl import SpotMixin
from .spot_market import SpotMarket


def _market_id(base: str, quote: str, asset_idx: int) -> str:
  return f'{base}/{quote}:{asset_idx}'


def parse_market_id(market_id: str) -> tuple[str, str, int]:
  """Parse canonical spot `market_id` format: `BASE/QUOTE:ASSET_IDX`."""
  ticker, idx_str = market_id.rsplit(':', 1)
  base, quote = ticker.split('/', 1)
  return base, quote, int(idx_str)


@dataclass(frozen=True, kw_only=True)
class SpotExchange(SpotMixin, _Exchange):

  @property
  def venue_id(self) -> str:
    return 'hyperliquid'

  @property
  def exchange_id(self) -> str:
    return 'spot'

  async def markets(self) -> Sequence[str]:
    meta = await self.shared.load_spot_meta()
    out: list[str] = []
    for asset in meta['universe']:
      spot_index = asset['index']
      m = await self.shared.spot_meta_of(spot_index)
      out.append(_market_id(m['base_meta']['name'], m['quote_meta']['name'], spot_index))
    return out

  async def market(self, market_id: str, /):
    base, quote, spot_index = parse_market_id(market_id)
    meta = await self.shared.spot_meta_of(spot_index)
    if meta['base_meta']['name'] != base or meta['quote_meta']['name'] != quote:
      raise ValueError(
        f"Spot market_id mismatch for idx={spot_index}: expected {base}/{quote}, got {meta['base_meta']['name']}/{meta['quote_meta']['name']}"
      )
    return SpotMarket(shared=self.shared, meta=meta)

