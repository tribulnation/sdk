"""dYdX chain fee arithmetic, including market holidays and staking discounts."""

from datetime import datetime
from decimal import Decimal

from typed_core.grpc import wrap_exceptions
from typed_dydx.chain.feetiers import Feetiers
from typed_dydx.protos.dydxprotocol import feetiers as proto
from tribulnation.sdk.market import Fees

PPM = 1_000_000


@wrap_exceptions
async def market_discount_params(
  client: Feetiers,
) -> list[proto.PerMarketFeeDiscountParams]:
  """Use the generated Typed RPC on the client's owned, public gRPC channel."""
  response = await proto.QueryStub(client.channel).all_market_fee_discount_params(
    proto.QueryAllMarketFeeDiscountParamsRequest()
  )
  return response.params


def market_charge(discount: proto.PerMarketFeeDiscountParams, now: datetime) -> int:
  """Evaluate the chain's inclusive-start, exclusive-end fee holiday window."""
  start, end = discount.start_time, discount.end_time
  if start is None or end is None or start.tzinfo is None or end.tzinfo is None:
    raise ValueError('dYdX market fee discount needs timezone-aware boundaries')
  if now.tzinfo is None or start >= end or not 0 <= discount.charge_ppm <= PPM:
    raise ValueError('dYdX market fee discount is malformed')
  return discount.charge_ppm if start <= now < end else PPM


def truncated_ppm(value: int, multiplier: int) -> int:
  """Match Go signed integer division, truncating rebates toward zero."""
  product = value * multiplier
  return product // PPM if product >= 0 else -((-product) // PPM)


def combined_fees(
  tier: proto.PerpetualFeeTier,
  *,
  charge_ppm: int,
  staking_discount_ppm: int = 0,
) -> Fees:
  """Apply market scaling first, then staking only to positive resulting fees.

  References:
    - [Protocol implementation](https://github.com/dydxprotocol/v4-chain/blob/main/protocol/x/feetiers/keeper/keeper.go)
  """
  if not 0 <= charge_ppm <= PPM or not 0 <= staking_discount_ppm <= PPM:
    raise ValueError('dYdX fee multipliers must be in [0, 1000000]')

  def rate(value: int) -> Decimal:
    """Retain both chain integer-rounding steps before converting to a fraction."""
    value = truncated_ppm(value, charge_ppm)
    if value > 0:
      value = truncated_ppm(value, PPM - staking_discount_ppm)
    return Decimal(value) / PPM

  return Fees.symmetric(maker=rate(tier.maker_fee_ppm), taker=rate(tier.taker_fee_ppm))
