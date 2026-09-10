from decimal import Decimal

from tribulnation.sdk.market import Fees, Rules

from typed_dydx.indexer.schemas import PerpetualMarket


def parse_rules(market: PerpetualMarket, fees: Fees) -> Rules:
  """Convert dYdX market and fee-tier metadata into SDK trading rules."""
  return Rules(
    fee_asset='USDC',
    tick_size=Decimal(market['tickSize']),
    step_size=Decimal(market['stepSize']),
    fees=fees,
    api=market['status'] == 'ACTIVE',
    details={
      'perpetual_market': market,
      'standard_fees': fees,
    },
  )
