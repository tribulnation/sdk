# %%
from decimal import Decimal
from datetime import timedelta

from typing_extensions import Literal

from typed_bybit import Bybit
from typed_bybit.finance.fixed_saving.place_order import FixedSavingOrderResult
from typed_bybit.finance.fixed_saving.redeem import FixedSavingRedeemResult
from dotenv import load_dotenv

from tribulnation.sdk.earn.instruments import Instrument

load_dotenv()

client = await Bybit.new().__aenter__()


# %% [markdown]
# ## `Instruments.instruments` — fixed-term saving products

# %%
def _parse_duration(raw: str) -> timedelta | None:
  """Parse Bybit's `duration` strings, e.g. "7d", "8h". The client also documents a
  "2m" form, which is left unparsed: "m" is ambiguous between months and minutes, and
  no product in the live catalogue uses it -- every one of the 15 currently listed is
  a whole number of days, from "2d" to "180d"."""
  unit = raw[-1]
  value = int(raw[:-1])
  if unit == 'd':
    return timedelta(days=value)
  if unit == 'h':
    return timedelta(hours=value)
  return None


async def fixed_saving_instruments(
  *, assets: list[str] | None = None
) -> list[Instrument]:
  raw = await client.finance.fixed_saving.product()
  out: list[Instrument] = []
  for p in raw['list']:
    if assets is not None and p['coin'] not in assets:
      continue
    # All 15 products in the live catalogue carry their APR via `interestCoinApyList`
    # (a percent-formatted string, e.g. "10.00%"); `tieredApyList` is present but empty
    # on every one of them. Prefer whichever is populated. `interestCoinApyList`'s coin
    # can differ from the staked coin -- that's `Instrument.yield_asset`. `tieredApyList`
    # entries carry `apy` in the same percent-formatted shape, so it needs the same
    # `rstrip('%') / 100` treatment to land as a fraction of 1.
    tiers = p.get('tieredApyList')
    interest_coins = p.get('interestCoinApyList')
    if tiers:
      apr = Decimal(tiers[0]['apy'].rstrip('%')) / 100
      yield_asset = None
    elif interest_coins:
      best = interest_coins[0]
      apr = Decimal(best['apy'].rstrip('%')) / 100
      yield_asset = best['coin'] if best['coin'] != p['coin'] else None
    else:
      apr = Decimal(0)
      yield_asset = None
    out.append(
      Instrument(
        # `specialUserGroupRequired` products are exactly the SDK's 'new-users' tag.
        tags=['new-users'] if p.get('specialUserGroupRequired') else ['fixed'],
        asset=p['coin'],
        apr=apr,
        yield_asset=yield_asset,
        min_qty=p['minStakeAmount'],
        # `maxStakeAmount` arrives as a parsed `Decimal`. `-1` is Bybit's "no cap"
        # sentinel -- documented for a tier's `max`, and mapped here defensively; no
        # product in the live catalogue actually returns it.
        max_qty=p['maxStakeAmount'] if p['maxStakeAmount'] != -1 else None,
        duration=_parse_duration(p['duration']),
        id=p['productId'],
      )
    )
  return out


await fixed_saving_instruments(assets=['USDT', 'USDC', 'BTC', 'ETH'])

# %% [markdown]
# ## `Instruments.instruments` — flexible savings and on-chain staking
#
# `finance.easy_onchain.product_info` serves two more catalogues off one endpoint,
# discriminated by `category`: `'FlexibleSaving'` (open-ended savings, the SDK's
# `'flexible'` tag) and `'OnChain'` (liquid staking, the SDK's `'staking'` tag).
# Both are public -- no auth, no "Earn" key permission -- and carry APR, min/max
# stake and a `productId` to act against, so both map onto `Instrument`.

# %%
EASY_ONCHAIN_TAGS: dict[Literal['FlexibleSaving', 'OnChain'], Instrument.Tag] = {
  'FlexibleSaving': 'flexible',
  'OnChain': 'staking',
}


async def easy_onchain_instruments(
  category: Literal['FlexibleSaving', 'OnChain'],
  *,
  assets: list[str] | None = None,
) -> list[Instrument]:
  raw = await client.finance.easy_onchain.product_info(category)
  out: list[Instrument] = []
  for p in raw['list']:
    if p['status'] != 'Available':
      continue
    if assets is not None and p['coin'] not in assets:
      continue
    # `term` is the term length in days, `0` (or absent) on an open-ended product.
    # Most of both catalogues is open-ended -- all 246 available `FlexibleSaving`
    # products and 18 of the 19 available `OnChain` ones -- but not all of it: the
    # `OnChain` BTC product carries `duration='Fixed'` and `term=45`, so it gets a
    # real `duration` and the SDK's 'fixed' tag on top of its category's own.
    term = p.get('term') or 0
    tags: list[Instrument.Tag] = [EASY_ONCHAIN_TAGS[category]]
    if term:
      tags.append('fixed')
    out.append(
      Instrument(
        tags=tags,
        asset=p['coin'],
        # `estimateApr` is percent-formatted, e.g. "2.12%", like the fixed-saving APYs.
        apr=Decimal(p['estimateApr'].rstrip('%')) / 100,
        min_qty=Decimal(p['minStakeAmount']),
        max_qty=Decimal(p['maxStakeAmount']),
        duration=timedelta(days=term) if term else None,
        id=p['productId'],
      )
    )
  return out


{
  category: await easy_onchain_instruments(
    category, assets=['USDT', 'USDC', 'BTC', 'ETH']
  )
  for category in ('FlexibleSaving', 'OnChain')
}


# %% [markdown]
# `Instruments.instruments(*, tags=None, assets=None)` — the full abstract signature is
# a filter over the three catalogues above concatenated. Within the fixed-saving
# catalogue, `tags` maps onto Bybit's own `specialUserGroupRequired` flag:
# `'new-users'` for a restricted promotional product, `'fixed'` otherwise -- both were
# observed live in the same response.

# %%
async def instruments(
  *,
  tags: list[Instrument.Tag] | None = None,
  assets: list[str] | None = None,
) -> list[Instrument]:
  out = await fixed_saving_instruments(assets=assets)
  out += await easy_onchain_instruments('FlexibleSaving', assets=assets)
  out += await easy_onchain_instruments('OnChain', assets=assets)
  if tags is not None:
    out = [i for i in out if any(t in tags for t in i.tags)]
  return out


await instruments(tags=['fixed'], assets=['USDT', 'USDC'])

# %% [markdown]
# ### Hold-to-Earn (airdrop) products — out of scope for `Instrument`
#
# Bybit also runs a `finance.hold_to_earn` airdrop program: holding a coin earns a
# yield in a possibly different coin, with the APR varying daily and per-caller
# (`personalApy`). It doesn't fit `Instrument` -- no subscription step, no min/max
# stake, no `id` to act against -- so it's shown here for reference only, not mapped.

# %%
await client.finance.hold_to_earn.product()


# %% [markdown]
# ### `place_order` / `redeem` — written, not executed

# %%
async def subscribe(
  product_id: str, coin: str, amount: Decimal
) -> FixedSavingOrderResult:
  """Stake into a Bybit fixed-term saving product. Requires the API key's
  dedicated "Earn" permission."""
  return await client.finance.fixed_saving.place_order(
    product_id=product_id,
    category='FixedTermSaving',
    coin=coin,
    amount=str(amount),
    account_type='UNIFIED',
    order_link_id='poc-not-executed',
  )


# Not executed here -- would stake real funds into a fixed saving product.
await subscribe('some-product-id', 'USDT', Decimal('10'))


# %%
async def redeem(product_id: str, position_id: str) -> FixedSavingRedeemResult:
  """Redeem a FundPool fixed-term saving position early. Requires the API key's
  dedicated "Earn" permission."""
  return await client.finance.fixed_saving.redeem(
    product_id=product_id,
    category='FundPool',
    position_id=position_id,
  )


# Not executed here -- would redeem a real position early.
await redeem('some-product-id', 'some-position-id')

# %% [markdown]
# ### Coverage assessment
#
# **Mostly supported.** Bybit's `finance.fixed_saving` product line (public, no
# auth) maps cleanly onto `Instrument`: coin, APR, min/max stake, duration and a
# redeemable `id` are all present in one call, and the live catalogue actually spans
# two of the SDK's tags -- ordinary `'fixed'` products alongside `specialUserGroupRequired`
# promotional ones that map onto `'new-users'` (4 of the 15 listed, in the same
# response). A minority of those products pay their APR in a *different* coin than the
# one staked -- 3 of 15 right now, e.g. stake `USDT`, earn `SOL` or `USDE` -- which is
# what `Instrument.yield_asset` is for; the other 12 carry an `interestCoinApyList`
# entry naming the staked coin itself.
#
# `finance.easy_onchain.product_info` covers two more of the SDK's tags off a single
# public endpoint: `category='FlexibleSaving'` for open-ended savings (`'flexible'`,
# 246 of 249 products currently `Available`) and `category='OnChain'` for liquid
# staking (`'staking'`, 19 of 21). Both carry APR, min/max stake and a `productId`, so
# they map onto `Instrument` the same way. Neither catalogue is *entirely* open-ended:
# one `OnChain` product (BTC) is a 45-day fixed term, so `duration` is read from `term`
# and that product carries `'fixed'` alongside `'staking'`.
#
# What's still missing relative to the SDK's `InstrumentTag` union: `'one-time'`.
# Bybit's analogue is `finance.advanced_earn.dual_asset` -- a public catalogue of 175
# structured products live, the same dual-investment shape other venues map onto that
# tag. It is left unmapped here because APR does not come with the catalogue:
# `dual_asset.product_info` carries `productId`, `duration` and minimum amounts but no
# yield, and the yield lives in `dual_asset.product_quote` as a per-price-tier
# `apyE8`, one call per product. Bybit's other `finance.*` lines (`advanced_earn`'s
# discount-buy/liquidity-mining/smart-leverage, `hold_to_earn` airdrops, `byusdt`,
# `rwa`, `spot_x` launchpools) are yield-bearing in a broad sense but don't carry a
# subscribable `Instrument` shape (no APR + min/max qty + id together), so they're
# left unmapped rather than force-fit.
#
# `place_order`/`redeem` (subscribe / early-redeem) both exist and are written above,
# but require the API key's dedicated "Earn" permission and are never executed here.
#
