"""Hyperliquid's official fee formula, applied to perpetual and spot markets.

References:
  - [Fee formula for developers](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees)
"""

from decimal import Decimal

from typing_extensions import Literal, TypedDict

from tribulnation.sdk.market import Fees

from .mixin import PerpMarketMixin, SpotMarketMixin

USDC_INDEX = 0
"""USDC's spot token index, on mainnet and testnet alike."""
SUPPORTED_SPOT_QUOTES = frozenset({'USDC', 'USDE'})
"""Spot quote tokens whose fees were verified against live fills without an aligned
quote token adjustment. Other quotes (USDH, USDT0, ...) are declined."""
STABLE_PAIR_SCALE = Decimal('0.2')
GROWTH_MODE_SCALE = Decimal('0.1')


class PerpArgs(TypedDict):
  """Per-asset inputs of a perpetual market."""

  type: Literal['perp']
  deployer_fee_scale: Decimal
  """HIP-3 `deployerFeeScale`; 0 on the default dex, which scales fees by 1."""
  growth_mode: bool
  """Whether the asset is in HIP-3 growth mode."""


class SpotArgs(TypedDict):
  """Per-pair inputs of a spot market."""

  type: Literal['spot']
  stable_pair: bool
  """Whether both base and quote are spot quote tokens."""


def fee_rates(
  *,
  maker_rate: Decimal,
  taker_rate: Decimal,
  referral: Decimal,
  args: PerpArgs | SpotArgs,
) -> Fees:
  """Port of the official `feeRates` formula, for a quote token that is not aligned.

  Only AQAv1 aligned quote tokens change fees, and callers decline every quote or
  collateral token whose alignment is unverified, so the aligned branches are omitted.

  Args:
    maker_rate: The schedule's maker rate (`userAddRate`, `spotAdd`, ...), staking included.
    taker_rate: The schedule's taker rate (`userCrossRate`, `spotCross`, ...).
    referral: The active referral discount, a fraction in [0, 1].
    args: The market's per-asset inputs.

  References:
    - [Fee formula for developers](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees)
  """
  if not maker_rate.is_finite() or not taker_rate.is_finite():
    raise ValueError('Hyperliquid fee rates must be finite')
  if not referral.is_finite() or not 0 <= referral <= 1:
    raise ValueError('Hyperliquid referral discount must be a fraction in [0, 1]')
  stable_scale = Decimal(1)
  hip3_scale = Decimal(1)
  growth_scale = Decimal(1)
  if args['type'] == 'spot':
    if args['stable_pair']:
      stable_scale = STABLE_PAIR_SCALE
  else:
    scale = args['deployer_fee_scale']
    if not scale.is_finite() or scale < 0:
      raise ValueError('Hyperliquid deployerFeeScale must be finite and non-negative')
    hip3_scale = scale + 1 if scale < 1 else scale * 2
    if args['growth_mode']:
      growth_scale = GROWTH_MODE_SCALE
  discount = 1 - referral
  maker = maker_rate * stable_scale * growth_scale
  # Referral and HIP-3 scaling apply to charges only, never to maker rebates.
  if maker > 0:
    maker *= hip3_scale * discount
  taker = taker_rate * stable_scale * hip3_scale * growth_scale * discount
  return Fees.symmetric(maker=maker, taker=taker)


def perp_args(self: PerpMarketMixin) -> PerpArgs:
  """The asset's fee inputs, declining markets whose fees are unverified.

  Raises:
    NotImplementedError: The collateral token is not USDC, or a HIP-3 asset lacks
      its per-asset `deployerFeeScale`.
  """
  collateral = self.collateral_meta
  if collateral['index'] != USDC_INDEX:
    raise NotImplementedError(
      f'Hyperliquid fees for {collateral["name"]} (token {collateral["index"]}) '
      'collateral perpetuals are unverified: aligned quote token status is not '
      'readable from the API'
    )
  scale = self.asset_meta.get('deployerFeeScale')
  if scale is None:
    if self.dex is not None:
      raise NotImplementedError(
        f'Hyperliquid HIP-3 asset {self.asset_meta["name"]} has no deployerFeeScale'
      )
    scale = Decimal(0)
  return {
    'type': 'perp',
    'deployer_fee_scale': scale,
    'growth_mode': self.asset_meta.get('growthMode') == 'enabled',
  }


async def spot_args(self: SpotMarketMixin, *, refetch: bool = False) -> SpotArgs:
  """The pair's fee inputs, declining quote tokens whose fees are unverified.

  Raises:
    NotImplementedError: The quote token is not USDC or USDE.
  """
  quote = self.quote_meta
  if quote['name'] not in SUPPORTED_SPOT_QUOTES:
    raise NotImplementedError(
      f'Hyperliquid spot fees for {quote["name"]} (token {quote["index"]}) quoted '
      'pairs are unverified: aligned quote token status is not readable from the API'
    )
  quotes = await self.shared.load_spot_quote_tokens(refetch=refetch)
  return {'type': 'spot', 'stable_pair': self.base_meta['index'] in quotes}


async def standard_perp_fees(
  self: PerpMarketMixin,
  *,
  refetch: bool = False,
) -> Fees | None:
  """The standard schedule with the asset's adjustments, or None when unverified."""
  try:
    args = perp_args(self)
  except NotImplementedError:
    return None
  schedule = await self.shared.load_standard_fee_schedule(refetch=refetch)
  return fee_rates(
    maker_rate=schedule['add'],
    taker_rate=schedule['cross'],
    referral=Decimal(0),
    args=args,
  )


async def personal_perp_fees(
  self: PerpMarketMixin,
  *,
  refetch: bool = False,
) -> Fees:
  """The account's rates (tier and staking included) with referral and asset adjustments."""
  args = perp_args(self)
  rates = await self.shared.load_user_fees(refetch=refetch)
  return fee_rates(
    maker_rate=rates['userAddRate'],
    taker_rate=rates['userCrossRate'],
    referral=rates['activeReferralDiscount'],
    args=args,
  )


async def standard_spot_fees(
  self: SpotMarketMixin,
  *,
  refetch: bool = False,
) -> Fees | None:
  """The standard spot schedule with the pair's adjustments, or None when unverified."""
  try:
    args = await spot_args(self, refetch=refetch)
  except NotImplementedError:
    return None
  schedule = await self.shared.load_standard_fee_schedule(refetch=refetch)
  return fee_rates(
    maker_rate=schedule['spotAdd'],
    taker_rate=schedule['spotCross'],
    referral=Decimal(0),
    args=args,
  )


async def personal_spot_fees(
  self: SpotMarketMixin,
  *,
  refetch: bool = False,
) -> Fees:
  """The account's spot rates with referral and stable-pair adjustments."""
  args = await spot_args(self, refetch=refetch)
  rates = await self.shared.load_user_fees(refetch=refetch)
  return fee_rates(
    maker_rate=rates['userSpotAddRate'],
    taker_rate=rates['userSpotCrossRate'],
    referral=rates['activeReferralDiscount'],
    args=args,
  )
