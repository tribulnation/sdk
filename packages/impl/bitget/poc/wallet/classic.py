# %%
import os
from decimal import Decimal

from typed_bitget import Bitget
from dotenv import load_dotenv

from tribulnation.sdk.wallet.deposit_methods import DepositMethod
from tribulnation.sdk.wallet.withdrawal_methods import WithdrawalMethod

load_dotenv()

client = await Bitget.new(
  access_key=os.environ['BITGET_CLASSIC_ACCESS_KEY'],
  secret_key=os.environ['BITGET_CLASSIC_SECRET_KEY'],
  passphrase=os.environ['BITGET_CLASSIC_PASSPHRASE'],
).__aenter__()

ASSETS = ['BTC', 'ETH', 'USDT', 'SOL']


# %% [markdown]
# ## `DepositMethods`
#
# `classic.spot.coins()` is **public**: it declares `meta={}` rather than
# `meta={'required': True}`, which is exactly what the shared REST core reads to decide
# signed-vs-unsigned, and a client built with `Bitget.new(public=True)` returns the full
# listing. It lists every coin Bitget supports along with its `chains`, one entry per
# network -- exactly the per-network deposit/withdrawal parameters
# `DepositMethod`/`WithdrawalMethod` need. `SpotCoinChain` carries `withdrawFee` and
# `extraWithdrawFee` but no deposit-fee field of any kind, so `fee` is always `None` here,
# same as KuCoin's `poc/wallet.ipynb`.

# %%
async def deposit_methods(*, assets: list[str] | None = None) -> list[DepositMethod]:
  raw = await client.classic.spot.coins()
  out: list[DepositMethod] = []
  for c in raw:
    if assets is not None and c['coin'] not in assets:
      continue
    for ch in c['chains']:
      if not ch['rechargeable']:
        continue
      out.append(DepositMethod(
        asset=c['coin'],
        network=ch['chain'],
        fee=None,
        contract_address=ch['contractAddress'],
        min_confirmations=ch['depositConfirm'],
      ))
  return out

await deposit_methods(assets=ASSETS)


# %% [markdown]
# ## `WithdrawalMethods`
#
# Same `spot.coins()` call; `withdrawFee` becomes the `Fee` (already a `Decimal`, no
# string-parsing needed), and `networks` is a client-side filter on `chain` (Bitget doesn't
# take it as a request parameter -- there's no per-network lookup, only per-coin).

# %%
async def withdrawal_methods(
  *,
  assets: list[str] | None = None,
  networks: list[str] | None = None,
) -> list[WithdrawalMethod]:
  raw = await client.classic.spot.coins()
  out: list[WithdrawalMethod] = []
  for c in raw:
    if assets is not None and c['coin'] not in assets:
      continue
    for ch in c['chains']:
      if not ch['withdrawable']:
        continue
      if networks is not None and ch['chain'] not in networks:
        continue
      out.append(WithdrawalMethod(
        asset=c['coin'],
        network=ch['chain'],
        fee=WithdrawalMethod.Fee(asset=c['coin'], amount=ch['withdrawFee']),
        contract_address=ch['contractAddress'],
      ))
  return out

await withdrawal_methods(assets=ASSETS)

# %%
# Same call, narrowed to one network -- e.g. only ERC20 USDT withdrawal methods.
await withdrawal_methods(assets=['USDT', 'BTC'], networks=['ERC20'])


# %% [markdown]
# ### Coverage assessment: `Wallet`
#
# **Fully supported.** `classic.spot.coins()` is public, unauthenticated, and returns the
# complete per-network deposit/withdrawal configuration (enabled flags, min confirmations,
# contract address, withdrawal fee) for every coin in one call -- no account-specific
# state or pagination needed for either `deposit_methods()` or `withdrawal_methods()`.

# %% [markdown]
# ## Account-scoped supplementary reads (not part of the abstract interface)
#
# `spot.deposit.address` is authenticated and account-scoped (an existing generated
# address, or a freshly generated one), unlike the public per-network data above --
# included as a real-data supplement, not because the SDK interface asks for it. Its `size`
# parameter is documented in `typed_bitget` only as "reserved for future use", so it's
# passed as `'0'`.

# %%
async def deposit_address(coin: str, chain: str | None = None):
  return await client.classic.spot.deposit.address(coin=coin, chain=chain, size='0')

await deposit_address('USDT', 'TRC20')


# %% [markdown]
# ## Withdraw (state-mutating -- written, never executed)
#
# `spot.withdrawal.create` isn't part of `WithdrawalMethods` (the abstract interface is
# read-only), but is the natural next step. Included only to show the mapping --
# **never executed**.

# %%
async def withdraw(*, asset: str, network: str, address: str, amount: Decimal) -> str:
  result = await client.classic.spot.withdrawal.create(
    coin=asset,
    transfer_type='on_chain',
    address=address,
    chain=network,
    size=str(amount),
  )
  return result['orderId']

# Not executed here -- would send a real on-chain withdrawal from the account.
await withdraw(asset='USDT', network='TRC20', address='<destination-address>', amount=Decimal('10'))
