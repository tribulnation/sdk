"""Market rules, from `AssetPairs`."""

from typing_extensions import TYPE_CHECKING
from decimal import Decimal

from tribulnation.sdk.market import Fees, Rules

from typed_kraken.spot.market_data.asset_pairs import AssetPair

if TYPE_CHECKING:
  from .mixin import MarketMixin


def first_tier(schedule: list[tuple[float, float]] | None) -> Decimal | None:
  """The lowest-volume tier's rate of a `[volume, percent]` fee schedule, as a
  fraction of 1. `None` when the pair carries no schedule."""
  if not schedule:
    return None
  return Decimal(str(min(schedule, key=lambda tier: tier[0])[1])) / 100


def parse_rules(info: AssetPair) -> Rules:
  """Map one `AssetPairs` row onto `Rules`.

  Fees are the base (lowest 30-day volume) tier of the pair's own schedule, in
  percent on the wire and a fraction here; a pair on a flat schedule reports it under
  `fees` only, and the maker rate then equals the taker rate. `fee_asset` is the
  quote asset: that is where `TradesHistory` denominates `fee`. Kraken publishes no
  price bounds for a pair, only a minimum volume (`ordermin`) and a minimum cost
  (`costmin`), so every price bound is left unset.
  """
  fees = info.get('fees')
  fees_maker = info.get('fees_maker') or fees
  maker = first_tier(fees_maker)
  taker = first_tier(fees)
  tick_size = info.get('tick_size')
  quote = info.get('quote', '')
  return Rules(
    fee_asset=quote,
    tick_size=tick_size
    if tick_size is not None
    else Decimal(1).scaleb(-info.get('pair_decimals', 0)),
    step_size=Decimal(1).scaleb(-info.get('lot_decimals', 0)),
    fixed_min_qty=info.get('ordermin'),
    min_value=info.get('costmin'),
    fees=Fees.symmetric(maker=maker, taker=taker)
    if maker is not None and taker is not None
    else None,
    api=info.get('status') == 'online',
    details=info,
  )


async def rules(self: 'MarketMixin', *, refetch: bool = False) -> Rules:
  """Fetch the market rules."""
  if not refetch:
    return parse_rules(self.info)
  pairs = await self.shared.load_pairs(refetch=True)
  return parse_rules(pairs[self.altname]['info'])
