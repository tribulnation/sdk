# %%
import os
from decimal import Decimal
from datetime import timedelta

from typed_bitget import Bitget
from dotenv import load_dotenv

from tribulnation.sdk.earn.instruments import Instrument

load_dotenv()

client = await Bitget.new(
  access_key=os.environ['BITGET_CLASSIC_ACCESS_KEY'],
  secret_key=os.environ['BITGET_CLASSIC_SECRET_KEY'],
  passphrase=os.environ['BITGET_CLASSIC_PASSPHRASE'],
).__aenter__()

ASSETS = ['USDT', 'BTC', 'ETH']


# %% [markdown]
# ## `Earn` (`Instruments`)
#
# Classic exposes four Earn product families (`client.classic.earn.{savings,elite,sharkfin,loan}`).
# This notebook covers **savings** only -- Bitget's plain APR-bearing subscription
# product, the same family production's `tribulnation.bitget.Earn` targets. `elite` (structured/subscription lending, also the *only* family UTA exposes --
# see `earn/uta.ipynb`), `sharkfin` (option-like structured yield) and `loan` (crypto-backed
# lending, not itself a yield instrument) are omitted here to keep the demo tractable; see
# the coverage note below.

# %%
async def savings_instruments(*, asset: str | None = None) -> list[Instrument]:
  raw = await client.classic.earn.savings.products(coin=asset)
  out: list[Instrument] = []
  for prod in raw:
    if prod['status'] != 'in_progress':
      continue
    duration = (
      timedelta(days=int(prod['period']))
      if prod['periodType'] == 'fixed' and prod.get('period')
      else None
    )
    for tier in prod['apyList']:
      out.append(Instrument(
        tags=[prod['periodType']],
        asset=prod['coin'],
        apr=tier['currentApy'] / 100,
        min_qty=tier['minStepVal'],
        max_qty=tier['maxStepVal'],
        duration=duration,
        id=prod['productId'],
      ))
  return out

{asset: await savings_instruments(asset=asset) for asset in ASSETS}


# %% [markdown]
# ### `instruments(*, tags=None, assets=None)`

# %%
async def instruments(
  *,
  tags: list[str] | None = None,
  assets: list[str] | None = None,
) -> list[Instrument]:
  out = await savings_instruments()
  if assets is not None:
    out = [ins for ins in out if ins.asset in assets]
  if tags is not None:
    out = [ins for ins in out if set(ins.tags) & set(tags)]
  return out

await instruments(assets=['USDT', 'BTC'], tags=['flexible'])


# %% [markdown]
# ### Coverage assessment: `Earn`
#
# **Fully supported** for the `savings` family: `classic.earn.savings.products()` maps
# cleanly onto `Instrument` -- one row per APY tier (`apyList`), with `periodType` (already
# `'flexible' | 'fixed'`) matching `Instrument.Tag` verbatim, no translation needed. Only
# `in_progress` products are surfaced, matching the abstract interface's implicit
# "currently available" contract; the unfiltered listing returns 412 products, of which 405
# are `in_progress`, 4 `off_line` and 3 `completed` (the declared status enum also allows
# `not_started`, `paused` and `sold_out`, none of which appeared live). 402 of them are
# `flexible` and 10 `fixed`, and every `fixed` one carries a non-empty `period`, so the
# `duration` mapping below never falls back.
#
# **Not covered here, but present on the venue** (all under `client.classic.earn`):
# - **`elite`** -- structured/subscription lending, keyed by `productId` with a
#   `minApr`..`maxApr` pair rather than one fixed rate, and per-payment-coin
#   `subscriptionCoinList` entries. See `earn/uta.ipynb` for a worked mapping of this same
#   family (it's the only one UTA exposes).
# - **`sharkfin`** -- option-like structured product, same category of "not a plain APR"
#   product as `elite`/dual-investment on other venues; omitted for the same reason KuCoin's
#   dual investment was flagged rather than force-fit.
# - **`loan`** -- crypto-backed lending (borrow against collateral); not itself a yield
#   instrument, so out of scope for `Instruments`.
#
# `classic.earn.account_assets()` (aggregate Earn balance across all four families) is used
# in `reporting/classic.ipynb`'s `Snapshots` section, not here.

# %% [markdown]
# ## Subscribe / redeem (state-mutating -- written, never executed)
#
# `earn.subscribe`/`earn.redeem` aren't part of the `Instruments` abstract interface (it's
# read-only), but are the natural next step. Included only to show the mapping --
# **never executed**.

# %%
async def subscribe(instrument: Instrument, *, amount: Decimal) -> str:
  assert instrument.id is not None, 'instrument has no id to subscribe to'
  result = await client.classic.earn.savings.subscribe(
    instrument.id,
    period_type='flexible' if 'flexible' in instrument.tags else 'fixed',
    amount=amount,
  )
  return result['orderId']

# Not executed here -- would subscribe real funds to a real Earn product.
products = await client.classic.earn.savings.products(coin='USDT')
await subscribe(
  Instrument(tags=['flexible'], asset='USDT', apr=Decimal('0'), id=products[0]['productId']),
  amount=Decimal('1'),
)


# %%
async def redeem(instrument: Instrument, *, amount: Decimal) -> str:
  assert instrument.id is not None, 'instrument has no id to redeem'
  result = await client.classic.earn.savings.redeem(
    product_id=instrument.id,
    period_type='flexible' if 'flexible' in instrument.tags else 'fixed',
    amount=amount,
  )
  return result['orderId']

# Not executed here -- would redeem a real holding on the account.
await redeem(
  Instrument(tags=['flexible'], asset='USDT', apr=Decimal('0'), id='some-product-id'),
  amount=Decimal('1'),
)
