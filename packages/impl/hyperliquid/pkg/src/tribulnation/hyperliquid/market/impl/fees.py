"""Complete native perpetual rates and honest boundaries for unresolved metadata."""

from decimal import Decimal

from tribulnation.sdk.market import Fees

from .mixin import PerpMarketMixin


def native_fee_supported(self: PerpMarketMixin) -> bool:
  """Restrict fee calculation to the validator-operated USDC perpetual schedule."""
  return (
    self.dex is None
    and self.collateral_meta['index'] == 0
    and not self.asset_meta.get('growthMode')
  )


async def standard_perp_fees(
  self: PerpMarketMixin,
  *,
  refetch: bool = False,
) -> Fees | None:
  """Load baseline fees without borrowing a configured user's discounts."""
  if not native_fee_supported(self):
    return None
  schedule = await self.shared.load_standard_fee_schedule(refetch=refetch)
  return Fees.symmetric(maker=schedule['add'], taker=schedule['cross'])


async def personal_perp_fees(
  self: PerpMarketMixin,
  *,
  refetch: bool = False,
) -> Fees:
  """Include the account tier, staking and active referral adjustment.

  References:
    - [Official formula](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees)
  """
  if not native_fee_supported(self):
    raise NotImplementedError(
      'Hyperliquid HIP-3/non-USDC fees require per-asset deployer and quote metadata'
    )
  rates = await self.shared.load_user_fees(refetch=refetch)
  referral = rates['activeReferralDiscount']
  if not referral.is_finite() or not 0 <= referral <= 1:
    raise ValueError('Hyperliquid referral discount must be a fraction in [0, 1]')
  # user*Rate already includes staking. The official formula separately applies
  # referrals only to positive charges, never to maker rebates.
  maker = rates['userAddRate']
  taker = rates['userCrossRate']
  if not maker.is_finite() or not taker.is_finite():
    raise ValueError('Hyperliquid account fee rates must be finite')
  discount = Decimal(1) - referral
  return Fees.symmetric(
    maker=maker * discount if maker > 0 else maker, taker=taker * discount
  )
