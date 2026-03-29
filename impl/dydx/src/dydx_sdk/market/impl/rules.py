from decimal import Decimal

from trading_sdk.market import Rules

from dydx.indexer.types import PerpetualMarket
from dydx.node.public.get_user_fee_tier import FeeTier

def parse_rules(market: PerpetualMarket, fees: FeeTier) -> Rules:
  base, quote = market['ticker'].split('-')
  return Rules(
    base=base,
    quote=quote,
    fee_asset=quote,
    tick_size=Decimal(market['tickSize']),
    step_size=Decimal(market['stepSize']),
    maker_fee=fees.maker,
    taker_fee=fees.taker,
    api=market['status'] == 'ACTIVE',
    details={
      'perpetual_market': market,
      'user_fees': fees,
    },
  )