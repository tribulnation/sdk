from typing_extensions import Collection, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from tribulnation.sdk.market import Exchange as _Exchange, Ticker

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

  async def tickers(
    self, markets: Collection[str] | None = None,
  ) -> Mapping[str, Ticker]:
    spot_meta, asset_ctxs = await self.shared.client.info.spot_meta_and_asset_ctxs()
    tokens_by_index = {t['index']: t for t in spot_meta['tokens']}
    wanted = None if markets is None else set(markets)

    result: dict[str, Ticker] = {}
    for asset, ctx in zip(spot_meta['universe'], asset_ctxs):
      spot_index = asset['index']
      base_idx, quote_idx = asset['tokens']
      base_name = tokens_by_index[base_idx]['name']
      quote_name = tokens_by_index[quote_idx]['name']
      mid = _market_id(base_name, quote_name, spot_index)
      if wanted is not None and mid not in wanted:
        continue
      result[mid] = Ticker(
        last=Decimal(px) if (px := ctx.get('midPx')) is not None else None,
        base_volume_24h=Decimal(ctx['dayNtlVlm']),
      )

    if wanted is not None and (missing := wanted - set(result)):
      raise ValueError(f'Spot markets not found: {", ".join(sorted(missing))}')
    return result

  async def market(self, market_id: str, /):
    base, quote, spot_index = parse_market_id(market_id)
    meta = await self.shared.spot_meta_of(spot_index)
    if meta['base_meta']['name'] != base or meta['quote_meta']['name'] != quote:
      raise ValueError(
        f"Spot market_id mismatch for idx={spot_index}: expected {base}/{quote}, got {meta['base_meta']['name']}/{meta['quote_meta']['name']}"
      )
    return SpotMarket(shared=self.shared, meta=meta)

