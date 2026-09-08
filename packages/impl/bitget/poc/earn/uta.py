# %%
import os
from decimal import Decimal

from typed_bitget import Bitget
from dotenv import load_dotenv

from tribulnation.sdk.earn.instruments import Instrument

load_dotenv()

client = await Bitget.new(
  access_key=os.environ['BITGET_UTA_ACCESS_KEY'],
  secret_key=os.environ['BITGET_UTA_SECRET_KEY'],
  passphrase=os.environ['BITGET_UTA_PASSPHRASE'],
).__aenter__()

ASSETS = ['USDT', 'BTC', 'ETH']


# %% [markdown]
# ## `Earn` (`Instruments`)
#
# Confirmed from the module layout (`uta/earn/__init__.py` only composes `elite` --
# no `savings`/`staking`/`loan` sibling exists anywhere under `uta/earn/`): **UTA's Earn
# surface is Elite-only.** Elite is a structured/subscription lending product, declared
# with an APR *pair* (`minApr`..`maxApr`) rather than one fixed rate, and settled per
# *subscription coin* (`subscriptionCoinList`) rather than per underlying product -- one
# product can be paid into with several different coins, each with its own fee rate and
# exchange rate. This notebook yields one `Instrument` per (product, subscription coin)
# pair.

# %%
async def elite_instruments(*, assets: list[str] | None = None) -> list[Instrument]:
  raw = await client.uta.earn.elite.products()
  out: list[Instrument] = []
  for prod in raw:
    if prod['sellOut'] == 'YES':
      continue
    for sub in prod['subscriptionCoinList']:
      asset = sub['subscriptionCoin']
      if assets is not None and asset not in assets:
        continue
      min_amount = sub.get('minAmount')
      out.append(Instrument(
        tags=['fixed'],
        asset=asset,
        # `minApr` is used as a conservative estimate -- see coverage note below for why
        # this is declared as a range. Values are percentages (confirmed live: the three
        # products listed today report '3.00' (BGUSD), '4.45' (BGSOL) and '1.85' (BGBTC),
        # not '0.03'/'0.0445'/'0.0185'), so divide by 100 to match `Instrument.apr`'s
        # fraction-of-1.
        apr=prod['minApr'] / 100,
        yield_asset=prod['coin'] if prod['coin'] != asset else None,
        min_qty=Decimal(min_amount) if min_amount else None,
        id=prod['productId'],
      ))
  return out

await elite_instruments(assets=ASSETS)


# %% [markdown]
# ### `instruments(*, tags=None, assets=None)`

# %%
async def instruments(
  *,
  tags: list[str] | None = None,
  assets: list[str] | None = None,
) -> list[Instrument]:
  out = await elite_instruments(assets=assets)
  if tags is not None:
    out = [ins for ins in out if set(ins.tags) & set(tags)]
  return out

await instruments(tags=['fixed'])


# %% [markdown]
# ### Coverage assessment: `Earn`
#
# **Partially supported, with a shape mismatch on paper.** `Instrument.apr` is a single
# `Decimal`, while Elite's rate is declared as a `minApr`..`maxApr` pair (the realized rate
# depends on subscribed volume and isn't known at listing time) -- this notebook reports
# `minApr` as a conservative floor. In practice the gap is currently theoretical: all three
# products listed live report `minApr == maxApr` (BGUSD 3.00, BGSOL 4.45, BGBTC 1.85), so
# the floor is the rate. A caller cannot rely on that, since nothing in the shape
# guarantees it.
#
# `Instrument.min_qty` is `None` for every live row: `EliteSubscriptionCoinItem.minAmount`
# is declared `NotRequired` and no live `subscriptionCoinList` entry carries it -- they
# send only `subscriptionCoin`, `precision`, `feeRate` and `exchangeRate`.
# `Instrument.duration` is left `None` too: no duration/lock-up field exists on
# `EliteProduct` or its nested entries (`subscribe_info()`'s richer per-coin shape does
# carry `interestTime`/`settleTime`, but those are absolute settlement timestamps for one
# specific subscription window, not a reusable "duration" for the product in general).
#
# BGBTC is filtered out by the `sellOut == 'YES'` check, so `ASSETS`'s BTC yields nothing
# and only BGUSD's USDT leg survives the asset filter.

# %% [markdown]
# ## Subscribe / redeem (state-mutating -- written, never executed)
#
# `earn.elite.subscribe`/`.redeem` aren't part of the `Instruments` abstract interface
# (it's read-only), but are the natural next step. Included only to show the mapping --
# **never executed**.

# %%
async def subscribe(instrument: Instrument, *, amount: Decimal) -> str:
  assert instrument.id is not None, 'instrument has no id to subscribe to'
  result = await client.uta.earn.elite.subscribe(
    product_sub_id=instrument.id,
    amount=float(amount),
    coin=instrument.asset,
    payment_accounts='unified',
  )
  return result['orderId']

# Not executed here -- would subscribe real funds to a real Earn product.
products = await client.uta.earn.elite.products()
await subscribe(
  Instrument(tags=['fixed'], asset=products[0]['subscriptionCoinList'][0]['subscriptionCoin'],
             apr=products[0]['minApr'], id=products[0]['productId']),
  amount=Decimal('1'),
)


# %%
async def redeem(instrument: Instrument, *, amount: Decimal) -> str:
  assert instrument.id is not None, 'instrument has no id to redeem'
  result = await client.uta.earn.elite.redeem(
    product_id=instrument.id,
    product_sub_id=instrument.id,
    redeem_type='standard',
    amount=float(amount),
    receive_account='unified',
    coin=instrument.asset,
  )
  return result['orderId']

# Not executed here -- would redeem a real holding on the account.
await redeem(
  Instrument(tags=['fixed'], asset='USDT', apr=Decimal('0'), id='some-product-id'),
  amount=Decimal('1'),
)
