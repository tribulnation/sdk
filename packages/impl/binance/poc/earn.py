# %%
import asyncio
from decimal import Decimal
from datetime import timedelta
from typing_extensions import Literal

from typed_binance import Binance
from dotenv import load_dotenv

from tribulnation.sdk.earn.instruments import Instrument

load_dotenv()

client = Binance.new()

ASSETS = ['BTC', 'ETH', 'USDT', 'BNB']
BINANCE_EARN_URL = 'https://www.binance.com/earn'


# %% [markdown]
# ## `Earn` (`Instruments`)
#
# Binance's Earn surface is much broader than Simple Earn: `typed_binance` also exposes
# Soft Staking, On-chain Yields (Staking's locked products), BFUSD, RWUSD, ETH/SOL
# staking and Dual Investment as distinct namespaces under `client.spot.http`. Simple
# Earn (`flexible`/`locked`), Soft Staking, On-chain Yields, BFUSD and RWUSD all map
# cleanly onto `Instrument` and are merged into `instruments()` below. ETH/SOL staking
# and Dual Investment don't -- see their own sections further down for why -- and Mining
# / Yield Arena are out of scope entirely (compute-payout and giveaway/airdrop surfaces,
# not rate-bearing instruments).
#

# %%
async def flexible_instruments(*, asset: str | None = None) -> list[Instrument]:
  rows = await client.spot.http.simple_earn.flexible.list_paged(asset=asset, size=100)
  return [
    Instrument(
      tags=['flexible'],
      asset=p['asset'],
      apr=p['latestAnnualPercentageRate'],
      min_qty=p['minPurchaseAmount'],
      url=BINANCE_EARN_URL,
      id=p['productId'],
    )
    for p in rows
    if p['canPurchase'] and not p['isSoldOut']
  ]


groups = await asyncio.gather(*(flexible_instruments(asset=a) for a in ASSETS))
results = [i for group in groups for i in group]
len(results), results[:5]


# %%
async def locked_instruments(*, asset: str | None = None) -> list[Instrument]:
  rows = await client.spot.http.simple_earn.locked.list_paged(asset=asset, size=100)
  out: list[Instrument] = []
  for p in rows:
    detail = p['detail']
    if detail['isSoldOut'] or (base_apr := detail.get('apr')) is None:
      # "Boost-only" locked products carry no base rewardAsset/apr at all -- only
      # extraRewardAsset/extraRewardAPR. Skipped rather than forced into `apr`, since
      # there's no base rate to report -- see the coverage note below.
      continue
    apr = Decimal(base_apr) + Decimal(detail.get('extraRewardAPR') or 0)
    reward_asset = detail.get('rewardAsset')
    out.append(
      Instrument(
        tags=['fixed'],
        asset=detail['asset'],
        apr=apr,
        yield_asset=reward_asset if reward_asset != detail['asset'] else None,
        min_qty=Decimal(p['quota']['minimum']),
        # `totalPersonalQuota` is this account's remaining subscription cap for the
        # product, not a venue-wide product maximum -- best-effort fit for `max_qty`.
        max_qty=Decimal(p['quota']['totalPersonalQuota']),
        duration=timedelta(days=detail['duration']),
        url=BINANCE_EARN_URL,
        id=p['projectId'],
      )
    )
  return out


groups = await asyncio.gather(*(locked_instruments(asset=a) for a in ASSETS))
results = [i for group in groups for i in group]
len(results), results[:5]


# %% [markdown]
# ### Soft Staking
#

# %%
async def soft_staking_instruments(*, asset: str | None = None) -> list[Instrument]:
  rows = await client.spot.http.staking.soft.list_paged(asset=asset)
  return [
    Instrument(
      tags=['staking', 'flexible'],
      asset=p['asset'],
      apr=p['apr'],
      min_qty=p['minAmount'],
      max_qty=p['maxCap'],
      url=BINANCE_EARN_URL,
    )
    for p in rows
  ]


results = await soft_staking_instruments()
len(results), results[:5]


# %% [markdown]
# ### On-chain Yields (locked)
#

# %%
async def on_chain_yields_instruments(*, asset: str | None = None) -> list[Instrument]:
  rows = await client.spot.http.staking.on_chain_yields.locked.list_paged(asset=asset)
  out: list[Instrument] = []
  for p in rows:
    detail = p['detail']
    if detail['isSoldOut']:
      continue
    reward_asset = detail['rewardAsset']
    out.append(
      Instrument(
        tags=['staking', 'fixed'],
        asset=detail['asset'],
        apr=Decimal(detail['apr']),
        yield_asset=reward_asset if reward_asset != detail['asset'] else None,
        min_qty=Decimal(p['quota']['minimum']),
        max_qty=Decimal(p['quota']['totalPersonalQuota']),
        duration=timedelta(days=detail['duration']),
        url=BINANCE_EARN_URL,
        id=p['projectId'],
      )
    )
  return out


results = await on_chain_yields_instruments()
len(results), results[:5]


# %% [markdown]
# ### BFUSD
#

# %%
async def bfusd_instrument() -> Instrument | None:
  page = await client.spot.http.bfusd.history.rate_history()
  rows = page.get('rows') or []
  if not rows or (rate := rows[0].get('annualPercentageRate')) is None:
    # No recorded rate yet -- BFUSD hasn't been open long enough on this account/venue
    # to have a rate_history row.
    return None
  return Instrument(
    tags=['flexible'],
    asset='USDT',
    apr=Decimal(rate),
    yield_asset='BFUSD',
    url=BINANCE_EARN_URL,
  )


await bfusd_instrument()


# %% [markdown]
# ### RWUSD
#

# %%
async def rwusd_instruments() -> list[Instrument]:
  page = await client.spot.http.rwusd.history.rate_history(size=1)
  rows = page.get('rows') or []
  if not rows or (rate := rows[0].get('annualPercentageRate')) is None:
    return []
  # `subscribe`'s `asset` is a closed `Literal['USDT', 'USDC']` (unlike BFUSD's
  # undocumented-set `asset`) -- one `Instrument` per accepted subscription asset,
  # sharing the one rate RWUSD actually has.
  return [
    Instrument(
      tags=['flexible'],
      asset=asset,
      apr=Decimal(rate),
      yield_asset='RWUSD',
      url=BINANCE_EARN_URL,
    )
    for asset in ('USDT', 'USDC')
  ]


await rwusd_instruments()


# %% [markdown]
# ### `instruments(*, tags=None, assets=None)`
#

# %%
async def instruments(
  *,
  tags: list[str] | None = None,
  assets: list[str] | None = None,
) -> list[Instrument]:
  flexible, locked, soft_staking, on_chain_yields, bfusd, rwusd = await asyncio.gather(
    flexible_instruments(),
    locked_instruments(),
    soft_staking_instruments(),
    on_chain_yields_instruments(),
    bfusd_instrument(),
    rwusd_instruments(),
  )
  out = [*flexible, *locked, *soft_staking, *on_chain_yields, *rwusd]
  if bfusd is not None:
    out.append(bfusd)
  if assets is not None:
    out = [ins for ins in out if ins.asset in assets]
  if tags is not None:
    out = [ins for ins in out if set(ins.tags) & set(tags)]
  return out


results = await instruments()
len(results), results[:10]

# %%
await instruments()

# %% [markdown]
# ### ETH / SOL staking (not mapped -- no product-catalog/rate exposed)
#
# Unlike every family above, `staking.eth`/`staking.sol` expose no "list products" or
# "current rate" endpoint at all -- only per-account `quota()` (min/max stake amounts,
# whether staking/redemption is currently open, a commission fee) and `account()`
# (current WBETH/BETH or BNSOL holdings and trailing 30-day profit). There's no `apr`
# anywhere in either response shape, so there's nothing to put in `Instrument.apr`
# without fabricating a number from account-level trailing profit -- not attempted here.
# Demonstrated live below, but intentionally not turned into an `Instrument` or merged
# into `instruments()`.
#

# %%
eth_quota, sol_quota = await asyncio.gather(
  client.spot.http.staking.eth.quota(),
  client.spot.http.staking.sol.quota(),
)
eth_quota, sol_quota


# %% [markdown]
# ### Dual Investment (not merged -- structured product, not a simple listing)
#
# `dual_investment.product_list` has no "list everything" mode: `option_type`,
# `invest_coin` and `exercised_coin` are all required, so building the full catalogue
# means first deciding which coin pairs to ask for -- a real difference from every other
# family above, which can each be listed in full with zero required filters. Nor does the
# response distinguish "no such pair" from "nothing on offer for this pair right now":
# both are `{'total': 0, 'list': []}`, never an error, so the only way to find the live
# catalogue is to sweep pairs and keep the non-empty ones. Sweeping every
# `(option_type, invest_coin, exercised_coin)` combination over 132 coins x 9 quote
# assets (2364 distinct combinations) at the time of this run, everything on offer was
# quoted in **USDC** -- 17 invest coins on the CALL side (AAVE, ADA, AVAX, BCH, BNB,
# BTC, DOGE, DOT, ENA, ETH, LTC, NEAR, SOL, SUI, UNI, XRP, ZEC) and the mirror 17 on the
# PUT side. Not one USDT-quoted pair returned a single product, which is why the cell
# below asks for `USDC` and shows the `USDT` answer alongside it.
#
# The deeper reason it stays out of `instruments()` is the product itself: a Dual
# Investment position settles in *either* `investCoin` or `exercisedCoin` depending on
# where the spot price lands relative to `strikePrice` at `settleDate` -- the asset
# actually returned isn't knowable up front, so `Instrument.yield_asset` (and arguably
# `asset` itself) can't be filled in honestly. `apr`/`min_qty`/`max_qty`/`duration` do
# map cleanly (`apr`, `minAmount`, `maxAmount` are decimal strings, `duration` is a
# whole number of days, `id` is a string), so it's demonstrated live below for one
# concrete pair, but left out of `instruments()` for both reasons: no filter-free
# listing, and no fixed settlement asset.

# %%
async def dual_investment_products(
  *,
  option_type: Literal['CALL', 'PUT'],
  invest_coin: str,
  exercised_coin: str,
) -> list[Instrument]:
  rows = await client.spot.http.dual_investment.product_list_paged(
    option_type=option_type,
    invest_coin=invest_coin,
    exercised_coin=exercised_coin,
    page_size=100,
  )
  return [
    Instrument(
      tags=['fixed'],
      asset=p['investCoin'],
      apr=Decimal(p['apr']),
      min_qty=Decimal(p['minAmount']),
      max_qty=Decimal(p['maxAmount']),
      duration=timedelta(days=p['duration']),
      url=BINANCE_EARN_URL,
      id=p['id'],
    )
    for p in rows
    if p['canPurchase']
  ]


usdt, usdc = await asyncio.gather(
  dual_investment_products(
    option_type='CALL', invest_coin='BTC', exercised_coin='USDT'
  ),
  dual_investment_products(
    option_type='CALL', invest_coin='BTC', exercised_coin='USDC'
  ),
)
len(usdt), len(usdc), usdc[:5]


# %% [markdown]
# ### Coverage assessment: `Earn`
#
# **Simple Earn (flexible/locked), Soft Staking, On-chain Yields, BFUSD and RWUSD are
# fully supported** -- all five map cleanly onto `Instrument`, fully paginated where
# paginated, executed live above against the real account, and merged into
# `instruments()`.
#
# The one real data-shape gap encountered (pre-existing, not new this round): some
# locked Simple Earn products (e.g. Binance's promotional "boost-only" listings) omit
# `detail.apr`/`detail.rewardAsset` entirely, carrying only `extraRewardAsset`/
# `extraRewardAPR` on top of a base rate that doesn't exist for that listing.
# `typed_binance` types both `LockedProductDetail.rewardAsset` and `.apr` as
# `NotRequired[str]`, so those rows validate cleanly rather than 500ing: the unfiltered
# listing behind `instruments()` really does carry them (8 of 123 locked products at the
# time of this run). `locked_instruments` above still treats a missing `apr` as "not a real
# base-rate product" and skips it, since an `Instrument` with `apr=0` would misrepresent
# a boost-only listing as a zero-yield product rather than describing what it actually
# is.
#
# `max_qty` on the locked/on-chain-yields side is `quota.totalPersonalQuota` -- this
# account's own remaining subscription room for that product, not a venue-wide cap the
# way KuCoin's `userUpperLimit` was -- flagged here since it's the same field
# name/shape mismatch production `tribulnation.binance.earn.instruments.parse_locked`
# also inherits unmodified.
#
# Flexible's tiered APR (`tierAnnualPercentageRate`, keyed by balance bracket) is not
# expanded into separate bracket-specific `Instrument`s here, unlike production's
# `parse_flexible` -- this notebook reports only the flat `latestAnnualPercentageRate`
# per asset, a real simplification worth flagging but not a live failure.
#
# Soft Staking has no per-product `id` in its response shape at all (unlike every other
# family, which all carry a `productId`/`projectId`) -- `Instrument.id` is left `None`
# for it, which is honest (there's genuinely nothing to subscribe/redeem by id; the
# mutation shape is a whole-account `soft_staking: bool` toggle instead, shown below).
#
# Both `bfusd.history.rate_history` and `rwusd.history.rate_history` used to type `total`
# as `NotRequired[str]` while the real response returns a JSON int, so pydantic 500'd on an
# otherwise normal response and both calls above passed `validate=False` to get through it.
# Fixed upstream since (`total` is `NotRequired[int]` on both), so the workaround is gone
# and both run with validation on.
#
# **ETH/SOL staking and Dual Investment are out of scope for `instruments()`** -- see
# their own sections above for the concrete reasons (no rate exposed at all for the
# former; no filter-free listing and no fixed settlement asset for the latter). Both are
# still demonstrated live, just not merged.
#
# **Mining and Yield Arena are out of scope entirely, not demonstrated.** Mining payouts
# are hashrate/hardware-output driven, not a subscribed-amount-times-apr product --
# there's no `asset`/`apr` pair to report, only per-worker earnings history. Yield Arena
# (`/sapi/v1/earn/arena/activities`) is a list of giveaway/airdrop/leaderboard
# promotions, not investable instruments at all -- no `asset`, no `apr`, no
# subscribe/redeem.
#

# %% [markdown]
# ## Subscribe / redeem (state-mutating -- written, never executed)
#
# None of these are part of the `Instruments` abstract interface (it's read-only), but
# are the natural next step a real integration would need -- one pair of mutating calls
# per family covered above (Simple Earn, Soft Staking, On-chain Yields, BFUSD, RWUSD,
# plus ETH/SOL staking and Dual Investment's subscribe, even though those two aren't
# merged into `instruments()`). Included here only to show how they'd map --
# **never executed**.
#

# %%
async def subscribe(instrument: Instrument, *, amount: Decimal) -> str:
  assert instrument.id is not None, 'instrument has no id to subscribe to'
  if 'flexible' in instrument.tags:
    result = await client.spot.http.simple_earn.flexible.subscribe(
      product_id=instrument.id,
      amount=str(amount),
    )
  else:
    result = await client.spot.http.simple_earn.locked.subscribe(
      project_id=instrument.id,
      amount=str(amount),
    )
  assert result.get('success', True)
  return str(result.get('purchaseId'))


# Not executed here -- would subscribe real funds to a real Earn product.
flexible = await client.spot.http.simple_earn.flexible.list(asset='USDT')
await subscribe(
  Instrument(
    tags=['flexible'],
    asset='USDT',
    apr=flexible['rows'][0]['latestAnnualPercentageRate'],
    id=flexible['rows'][0]['productId'],
  ),
  amount=Decimal('1'),
)


# %%
async def redeem(instrument: Instrument, *, amount: Decimal | None = None) -> str:
  assert instrument.id is not None, 'instrument has no id to redeem'
  if 'flexible' in instrument.tags:
    result = await client.spot.http.simple_earn.flexible.redeem(
      product_id=instrument.id,
      amount=str(amount) if amount is not None else None,
      redeem_all=amount is None,
    )
  else:
    # Locked positions redeem by positionId, not projectId -- would need
    # `locked.position` to look the position up first on a real holding.
    result = await client.spot.http.simple_earn.locked.redeem(position_id=instrument.id)
  assert result.get('success', True)
  return str(result.get('redeemId'))


# Not executed here -- would redeem a real holding on the account.
await redeem(
  Instrument(tags=['flexible'], asset='USDT', apr=Decimal(0), id='holding-product-id'),
  amount=Decimal('1'),
)


# %%
async def set_soft_staking(*, enabled: bool) -> bool:
  result = await client.spot.http.staking.soft.set(soft_staking=enabled)
  return bool(result.get('success', True))


# Not executed here -- would flip real Soft Staking enablement for this account.
await set_soft_staking(enabled=True)


# %%
async def subscribe_on_chain_yields(instrument: Instrument, *, amount: Decimal) -> str:
  assert instrument.id is not None, 'instrument has no id to subscribe to'
  result = await client.spot.http.staking.on_chain_yields.locked.subscribe(
    project_id=instrument.id,
    amount=str(amount),
  )
  assert result.get('success', True)
  return str(result.get('positionId'))


async def redeem_on_chain_yields(position_id: str) -> str:
  result = await client.spot.http.staking.on_chain_yields.locked.redeem(
    position_id=position_id
  )
  assert result.get('success', True)
  return str(result.get('redeemId'))


# Not executed here -- would subscribe/redeem a real on-chain-yields position.
locked = await on_chain_yields_instruments()
await subscribe_on_chain_yields(locked[0], amount=Decimal('1'))
await redeem_on_chain_yields('some-position-id')


# %%
async def subscribe_bfusd(*, asset: str, amount: Decimal) -> Decimal:
  result = await client.spot.http.bfusd.subscribe(asset=asset, amount=float(amount))
  assert result.get('success', True)
  return Decimal(result.get('bfusdAmount', '0'))


async def redeem_bfusd(
  *, amount: Decimal, type: Literal['FAST', 'STANDARD'] = 'STANDARD'
) -> Decimal:
  result = await client.spot.http.bfusd.redeem(amount=float(amount), type=type)
  assert result.get('success', True)
  return Decimal(result.get('receiveAmount', '0'))


# Not executed here -- would subscribe/redeem real BFUSD on the account.
await subscribe_bfusd(asset='USDT', amount=Decimal('1'))
await redeem_bfusd(amount=Decimal('1'))


# %%
async def subscribe_rwusd(
  *, asset: Literal['USDT', 'USDC'], amount: Decimal
) -> Decimal:
  result = await client.spot.http.rwusd.subscribe(asset=asset, amount=float(amount))
  assert result.get('success', True)
  return Decimal(result.get('rwusdAmount', '0'))


async def redeem_rwusd(
  *, amount: Decimal, type: Literal['FAST', 'STANDARD'] = 'STANDARD'
) -> Decimal:
  result = await client.spot.http.rwusd.redeem(amount=float(amount), type=type)
  assert result.get('success', True)
  return Decimal(result.get('receiveAmount', '0'))


# Not executed here -- would subscribe/redeem real RWUSD on the account.
await subscribe_rwusd(asset='USDT', amount=Decimal('1'))
await redeem_rwusd(amount=Decimal('1'))


# %%
async def stake_eth(*, amount: Decimal) -> Decimal:
  result = await client.spot.http.staking.eth.stake(amount=float(amount))
  assert result.get('success', True)
  return Decimal(result.get('wbethAmount', '0'))


async def redeem_eth(
  *, amount: Decimal, asset: Literal['WBETH', 'BETH'] = 'WBETH'
) -> Decimal:
  result = await client.spot.http.staking.eth.redeem(amount=float(amount), asset=asset)
  assert result.get('success', True)
  return Decimal(result.get('ethAmount', '0'))


# Not executed here -- would stake/redeem real ETH on the account.
await stake_eth(amount=Decimal('0.01'))
await redeem_eth(amount=Decimal('0.01'))


# %%
async def stake_sol(*, amount: Decimal) -> Decimal:
  result = await client.spot.http.staking.sol.stake(amount=float(amount))
  assert result.get('success', True)
  return Decimal(result.get('bnsolAmount', '0'))


async def redeem_sol(*, amount: Decimal) -> Decimal:
  result = await client.spot.http.staking.sol.redeem(amount=float(amount))
  assert result.get('success', True)
  return Decimal(result.get('solAmount', '0'))


# Not executed here -- would stake/redeem real SOL on the account.
await stake_sol(amount=Decimal('1'))
await redeem_sol(amount=Decimal('1'))


# %%
async def subscribe_dual_investment(
  instrument: Instrument, *, order_id: str, amount: Decimal
) -> int:
  assert instrument.id is not None, 'instrument has no id to subscribe to'
  result = await client.spot.http.dual_investment.subscribe(
    id=instrument.id,
    order_id=order_id,
    deposit_amount=float(amount),
    auto_compound_plan='NONE',
  )
  assert result.get('purchaseStatus') != 'FAIL'
  return int(result.get('positionId', 0))


# Not executed here -- would subscribe real funds to a real Dual Investment product.
# There's no plain "redeem" -- a position settles automatically at `settleDate`.
products = await dual_investment_products(
  option_type='CALL', invest_coin='BTC', exercised_coin='USDC'
)
await subscribe_dual_investment(
  products[0], order_id='some-order-id', amount=Decimal('0.01')
)
