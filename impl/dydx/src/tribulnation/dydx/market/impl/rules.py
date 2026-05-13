from decimal import Decimal

from tribulnation.sdk.market import Rules

from dydx.indexer.types import PerpetualMarket
from dydx.protos.dydxprotocol import feetiers as feetiers_proto

def fee_ppm(value: int) -> Decimal:
  """Convert dYdX fee parts-per-million into a decimal rate."""
  return Decimal(value) / Decimal(1_000_000)

def parse_rules(market: PerpetualMarket, fees: feetiers_proto.PerpetualFeeTier) -> Rules:
  """Convert dYdX market and fee-tier metadata into SDK trading rules."""
  base, quote = market['ticker'].split('-')
  return Rules(
    base=base,
    quote=quote,
    fee_asset=quote,
    tick_size=Decimal(market['tickSize']),
    step_size=Decimal(market['stepSize']),
    maker_fee=fee_ppm(fees.maker_fee_ppm),
    taker_fee=fee_ppm(fees.taker_fee_ppm),
    api=market['status'] == 'ACTIVE',
    details={
      'perpetual_market': market,
      'user_fees': fees,
    },
  )
