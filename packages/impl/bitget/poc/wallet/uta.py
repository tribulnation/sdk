# %%
import os
from decimal import Decimal
from datetime import datetime, timedelta, timezone

from typed_bitget import Bitget
from dotenv import load_dotenv

from tribulnation.sdk.wallet.deposit_methods import DepositMethod
from tribulnation.sdk.wallet.withdrawal_methods import WithdrawalMethod

load_dotenv()

client = await Bitget.new(
  access_key=os.environ['BITGET_UTA_ACCESS_KEY'],
  secret_key=os.environ['BITGET_UTA_SECRET_KEY'],
  passphrase=os.environ['BITGET_UTA_PASSPHRASE'],
).__aenter__()

ASSETS = ['BTC', 'ETH', 'USDT', 'SOL']


# %% [markdown]
# ## `DepositMethods` / `WithdrawalMethods`
#
# Investigated whether `uta/` has its own coin/network config listing (per-network enabled
# flags, contract address, min confirmations, withdrawal fee) analogous to Classic's
# `spot.coins()`: it does not. `uta/market/*` is market data and `instruments.py`
# (symbol/trading-pair rules, unrelated); `uta/account/*` carries account config, with the
# nearest thing being `account/collateral/custom_coins.py` (collateral-eligibility, no
# network data); and `uta/transfers/*` only ever takes a `chain` as a *request* parameter
# (deposit address, withdraw submit, records) -- it never lists the chains available for a
# coin.
#
# However, `classic.spot.coins()` (see `wallet/classic.ipynb`) is **public and
# unauthenticated**, so it doesn't require Classic-mode credentials -- just any valid
# `Bitget` client, because `typed_bitget.Bitget` composes *both* `.classic` and `.uta` on
# one shared HTTP client regardless of which credential set built it (the `Bitget` class
# docstring's "One credential set is shared by both... call the methods matching your
# account" is about *authenticated* calls -- this one needs no auth at all). So a
# UTA-credentialed client can call it too, and this notebook does exactly that: reuses the
# same public per-network listing rather than treating UTA as unsupported. Production
# `tribulnation.bitget`'s blanket `NotImplementedError` for UTA mode wallet methods looks
# overly conservative in light of this -- the underlying data isn't account-mode-scoped.

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

await withdrawal_methods(assets=['USDT', 'BTC'], networks=['TRC20'])


# %% [markdown]
# ### Coverage assessment: `Wallet`
#
# **Fully supported**, by reusing the public `classic.spot.coins()` listing -- see the note
# above. The mapping itself is identical to `wallet/classic.ipynb`; the only UTA-specific
# part is *account-scoped* reads/writes (deposit address, withdrawal submission/history),
# covered below and in `reporting/uta.ipynb`.

# %% [markdown]
# ## Account-scoped supplementary reads (not part of the abstract interface)
#
# Unlike the coin/network listing, `uta.transfers.deposit.address` genuinely is
# UTA-specific and authenticated -- it returns an address scoped to *this* unified account.

# %%
async def deposit_address(coin: str, chain: str | None = None):
  return await client.uta.transfers.deposit.address(coin=coin, chain=chain)

await deposit_address('USDT', 'TRC20')


# %% [markdown]
# ## Withdraw (state-mutating -- written, never executed)
#
# `uta.transfers.withdraw.submit` isn't part of `WithdrawalMethods` (the abstract interface
# is read-only), but is the natural next step. Included only to show the mapping --
# **never executed**.

# %%
async def withdraw(*, asset: str, network: str, address: str, amount: Decimal) -> str:
  result = await client.uta.transfers.withdraw.submit(
    coin=asset,
    chain=network,
    transfer_type='on_chain',
    address=address,
    size=str(amount),
  )
  return result['orderId']

# Not executed here -- would send a real on-chain withdrawal from the account.
await withdraw(asset='USDT', network='trx', address='<destination-address>', amount=Decimal('10'))
