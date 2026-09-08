# %%
import asyncio
from decimal import Decimal
from datetime import timedelta
from typing_extensions import Literal

from typed_kucoin import KuCoin
from dotenv import load_dotenv

from tribulnation.sdk.earn.instruments import Instrument

load_dotenv()

client = await KuCoin.new().__aenter__()

ASSETS = ['USDT', 'BTC', 'ETH', 'KCS']


# %% [markdown]
# ## `Earn` (`Instruments`)
#
# KuCoin's Earn surface hangs entirely off `client.earn`, split into product-family
# listing calls (savings, staking, KCS staking, ETH staking, promotions, dual investment)
# that each return their own item shape. `Instruments.instruments()` needs to flatten all
# of these into one `Sequence[Instrument]`.

# %%
async def savings_instruments(*, currency: str | None = None) -> list[Instrument]:
  raw = await client.earn.savings_products(currency=currency)
  return [
    Instrument(
      tags=['flexible'] if p['type'] == 'DEMAND' else ['fixed'],
      asset=p['currency'],
      apr=Decimal(p['returnRate']),
      yield_asset=p['incomeCurrency'] if p['incomeCurrency'] != p['currency'] else None,
      min_qty=Decimal(p['userLowerLimit']),
      max_qty=Decimal(p['userUpperLimit']),
      duration=timedelta(days=p['duration']) if p['type'] == 'TIME' else None,
      id=p['id'],
    )
    for p in raw
  ]


{asset: await savings_instruments(currency=asset) for asset in ASSETS}


# %%
async def staking_instruments(*, currency: str | None = None) -> list[Instrument]:
  raw = await client.earn.staking_products(currency=currency)
  return [
    Instrument(
      tags=['staking', 'flexible' if p['type'] == 'DEMAND' else 'fixed'],
      asset=p['currency'],
      apr=Decimal(p['returnRate']),
      yield_asset=p['incomeCurrency'] if p['incomeCurrency'] != p['currency'] else None,
      min_qty=Decimal(p['userLowerLimit']),
      max_qty=Decimal(p['userUpperLimit']),
      duration=timedelta(days=p['duration']) if p['type'] == 'TIME' else None,
      id=p['id'],
    )
    for p in raw
  ]


await staking_instruments()


# %%
async def kcs_staking_instruments() -> list[Instrument]:
  raw = await client.earn.kcs_staking_products(currency='KCS')
  return [
    Instrument(
      tags=['staking', 'flexible' if p['type'] == 'DEMAND' else 'fixed'],
      asset=p['currency'],
      apr=Decimal(p['returnRate']),
      yield_asset=p['incomeCurrency'] if p['incomeCurrency'] != p['currency'] else None,
      min_qty=Decimal(p['userLowerLimit']),
      max_qty=Decimal(p['userUpperLimit']),
      duration=timedelta(days=p['duration']) if p['type'] == 'TIME' else None,
      id=p['id'],
    )
    for p in raw
  ]


await kcs_staking_instruments()


# %%
async def eth_staking_instruments() -> list[Instrument]:
  raw = await client.earn.eth_staking_products(currency='ETH')
  return [
    Instrument(
      tags=['staking', 'flexible' if p['type'] == 'DEMAND' else 'fixed'],
      asset=p['currency'],
      apr=Decimal(p['returnRate']),
      yield_asset=p['incomeCurrency'] if p['incomeCurrency'] != p['currency'] else None,
      min_qty=Decimal(p['userLowerLimit']),
      max_qty=Decimal(p['userUpperLimit']),
      duration=timedelta(days=p['duration']) if p['type'] == 'TIME' else None,
      id=p['id'],
    )
    for p in raw
  ]


await eth_staking_instruments()


# %%
async def promotion_instruments(*, currency: str | None = None) -> list[Instrument]:
  raw = await client.earn.promotion_products(currency=currency)
  return [
    Instrument(
      tags=['new-users', 'fixed'] if p['newUserOnly'] else ['fixed'],
      asset=p['currency'],
      apr=Decimal(p['returnRate']),
      yield_asset=p['incomeCurrency'] if p['incomeCurrency'] != p['currency'] else None,
      min_qty=Decimal(p['userLowerLimit']),
      max_qty=Decimal(p['userUpperLimit']),
      duration=timedelta(days=p['duration']),
      id=p['id'],
    )
    for p in raw
  ]


await promotion_instruments()


# %%
async def dual_investment_instruments(
  *,
  category: Literal['DUAL_CLASSIC', 'DUAL_BOOSTER', 'DUAL_EXTRA'] = 'DUAL_CLASSIC',
) -> list[Instrument]:
  # Dual investment is a structured (option-like) product settled at expiry in one of
  # two assets depending on the strike -- tagged 'one-time' since it's a single bet, not
  # a recurring subscription program the way savings/staking are.
  raw = await client.earn.dual_investment_products(category=category)
  return [
    Instrument(
      tags=['one-time'],
      asset=p['investCurrency'],
      apr=Decimal(p['annualRate']),
      yield_asset=p['strikeCurrency']
      if p['strikeCurrency'] != p['investCurrency']
      else None,
      min_qty=Decimal(p['lowerLimit']),
      max_qty=Decimal(p['upperLimit']),
      duration=None,
      id=p['productId'],
    )
    for p in raw
  ]


results = await dual_investment_instruments()
# KuCoin runs many strike/expiry combinations per pair (thousands of live rows) --
# showing the first 5 of the real, unfiltered result to keep this readable.
len(results), results[:5]


# %% [markdown]
# ### `instruments(*, tags=None, assets=None)`
#
# Combine every product family behind the one SDK method, then apply the `tags`/`assets`
# filters client-side (KuCoin has no single endpoint spanning all families).

# %%
async def instruments(
  *,
  tags: list[str] | None = None,
  assets: list[str] | None = None,
) -> list[Instrument]:
  results = await asyncio.gather(
    savings_instruments(),
    staking_instruments(),
    kcs_staking_instruments(),
    eth_staking_instruments(),
    promotion_instruments(),
    dual_investment_instruments(),
  )
  out = [ins for group in results for ins in group]
  if assets is not None:
    out = [ins for ins in out if ins.asset in assets]
  if tags is not None:
    out = [ins for ins in out if set(ins.tags) & set(tags)]
  return out


results = await instruments(assets=['USDT', 'KCS', 'ETH'])
# Same truncation as above -- dual investment dominates the count for a common asset
# like USDT. Showing the first 10 of the real, filtered result.
len(results), results[:10]


# %% [markdown]
# ### Coverage assessment: `Earn`
#
# **Fully supported**, mapping cleanly onto `Instrument` for five of KuCoin's six product
# families (savings, general staking, KCS staking, ETH staking, promotions) -- each is a
# simple APR-bearing subscription with a currency, min/max size, and (for `TIME` products)
# a fixed duration.
#
# Dual investment is the one family that doesn't fit the shape well: it's a structured,
# option-like product priced by strike/side rather than a plain APR, and its "yield" is
# conditional on where the underlying settles relative to the strike -- `apr`/`yield_asset`
# above are best-effort approximations (the headline `annualRate`, and the settlement
# currency), not a guaranteed return the way a savings product's `returnRate` is. It's
# included since `InstrumentTag` has a `'one-time'` tag that fits it, but a stricter
# implementation might exclude it, or add a KuCoin-specific field to `Instrument.details`-
# style raw data instead (the abstract `Instrument` dataclass has no `details` escape
# hatch, unlike `Rules`/`OrderResponse` elsewhere in the SDK).
#
# `instruments(tags=..., assets=...)` is implemented as a client-side fan-out + filter over
# the six listing calls, since KuCoin exposes no single cross-family endpoint.

# %% [markdown]
# ## Subscribe / redeem (state-mutating -- written, never executed)
#
# `earn.purchase` and `earn.redeem` aren't part of the `Instruments` abstract interface
# (it's read-only), but are the natural next step a real integration would need. Included
# here only to show how they'd map -- **never executed**.

# %%
async def purchase(instrument: Instrument, *, amount: Decimal) -> str:
  assert instrument.id is not None, 'instrument has no id to purchase'
  result = await client.earn.purchase(
    instrument.id, amount=amount, account_type='TRADE'
  )
  return result['orderId']


# Not executed here -- would subscribe real funds to a real Earn product.
savings = await client.earn.savings_products(currency='USDT')
await purchase(
  Instrument(
    tags=['flexible'],
    asset='USDT',
    apr=Decimal(savings[0]['returnRate']),
    id=savings[0]['id'],
  ),
  amount=Decimal('1'),
)


# %%
async def redeem(order_id: str, *, amount: Decimal) -> str:
  preview = await client.earn.redeem_preview(order_id=order_id)
  result = await client.earn.redeem(order_id=order_id, amount=amount)
  return result['status']


# Not executed here -- would redeem a real holding on the account.
await redeem('holding-order-id', amount=Decimal('1'))
