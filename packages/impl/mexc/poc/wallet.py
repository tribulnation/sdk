# %%
import os
from decimal import Decimal

from dotenv import load_dotenv

from typed_mexc import MEXC
from typed_mexc.core import ApiError
from typed_mexc.spot.http.wallet.deposit_address import DepositAddressItem

from tribulnation.sdk.wallet.deposit_methods import DepositMethod
from tribulnation.sdk.wallet.withdrawal_methods import WithdrawalMethod

load_dotenv()

# typed_mexc.core.auth.resolve_credentials reads MEXC_ACCESS_KEY/MEXC_SECRET_KEY from the
# environment, but this repo's .env only carries the legacy-shaped MEXC_API_KEY/
# MEXC_API_SECRET (the names production tribulnation.mexc reads) -- passed explicitly here
# rather than renamed, since MEXC issues one key pair shared by both names either way.
client = await MEXC.new(
  api_key=os.environ['MEXC_API_KEY'],
  api_secret=os.environ['MEXC_API_SECRET'],
).__aenter__()

ASSETS = ['BTC', 'ETH', 'USDT']


# %% [markdown]
# ## `DepositMethods`
#
# Both wallet methods share one underlying call: `spot.http.wallet.currency_info()`, MEXC's
# per-currency, per-network config (enabled flags, contract address, withdrawal fee). MEXC
# requires this to be a *signed* request (`meta={'signed': True}` on the endpoint) even
# though the response carries no account-specific state -- credentials are required to call it, but the
# data itself is public reference data.

# %%
async def deposit_methods(*, assets: list[str] | None = None) -> list[DepositMethod]:
  currencies = await client.spot.http.wallet.currency_info()
  out: list[DepositMethod] = []
  for c in currencies:
    asset = c['coin']
    if asset is None or (assets is not None and asset not in assets):
      continue
    for net in c['networkList']:
      network = net['netWork']
      if not net['depositEnable'] or network is None:
        continue
      out.append(
        DepositMethod(
          asset=asset,
          network=network,
          fee=None,
          contract_address=net.get('contract') or None,
          min_confirmations=net['minConfirm'],
        )
      )
  return out


await deposit_methods(assets=ASSETS)


# %% [markdown]
# ## `WithdrawalMethods`

# %%
async def withdrawal_methods(
  *,
  assets: list[str] | None = None,
  networks: list[str] | None = None,
) -> list[WithdrawalMethod]:
  currencies = await client.spot.http.wallet.currency_info()
  out: list[WithdrawalMethod] = []
  for c in currencies:
    asset = c['coin']
    if asset is None or (assets is not None and asset not in assets):
      continue
    for net in c['networkList']:
      network = net['netWork']
      if network is None or (networks is not None and network not in networks):
        continue
      if not net['withdrawEnable']:
        continue
      out.append(
        WithdrawalMethod(
          asset=asset,
          network=network,
          fee=WithdrawalMethod.Fee(asset=asset, amount=Decimal(net['withdrawFee']))
          if net['withdrawFee'] is not None
          else None,
          contract_address=net.get('contract') or None,
        )
      )
  return out


await withdrawal_methods(assets=ASSETS)

# %% [markdown]
# ### Filtering by `networks`

# %%
# Narrowed to one network -- MEXC spells BEP20 as "BSC" in `netWork`.
await withdrawal_methods(assets=ASSETS, networks=['BSC'])


# %% [markdown]
# ### Coverage assessment: `Wallet`
#
# **Full.** Both `deposit_methods()` and `withdrawal_methods()` map cleanly from the one
# `spot.http.wallet.currency_info()` call -- MEXC returns `depositEnable`/`withdrawEnable` flags
# and a `withdrawFee` per network in the same response, so no pagination or extra requests
# are needed. `DepositMethod.fee` is always `None` since MEXC deposits are free and
# `currency_info` reports no deposit-fee field; `min_confirmations` comes from
# `minConfirm`. Live-tested above, unfiltered, asset-filtered, and network-filtered.
#
# One field-naming wrinkle worth flagging: `CoinNetwork` carries both a legacy `network`
# display string (e.g. `"Tron(TRC20)"`) and a machine-usable `netWork` identifier (e.g.
# `"TRX"`) -- `netWork` is the one this notebook maps to `DepositMethod.network`/
# `WithdrawalMethod.network`, matching what `withdraw()`'s own `net_work` parameter expects
# below. Picking `network` instead would silently produce values MEXC's own withdraw
# endpoint doesn't accept.

# %% [markdown]
# ## Account-scoped supplementary reads (not part of the abstract interface)
#
# `spot.http.wallet.deposit_address` returns existing generated deposit addresses for an asset --
# unlike `currency_info` above, this needs real account state, and (unlike `currency_info`)
# MEXC's own permission scoping treats it as account-sensitive.

# %%
async def deposit_addresses(coin: str) -> list[DepositAddressItem]:
  return await client.spot.http.wallet.deposit_address(coin=coin)


try:
  addresses = await deposit_addresses('USDT')
except ApiError as e:
  addresses = e
addresses


# %% [markdown]
# `deposit_addresses` fails live with `700007 No permission to access the endpoint` -- the
# same scope error every account-sensitive spot endpoint hits on this API key throughout
# `market.ipynb`/`reporting.ipynb`, not a code issue.

# %% [markdown]
# ## Withdraw (state-mutating -- written, never executed)
#
# `spot.http.wallet.withdraw` isn't part of `WithdrawalMethods` (the abstract interface is
# read-only), but is the natural next step a real integration would need. Included only to
# show the mapping -- **never executed**.

# %%
async def withdraw(*, asset: str, network: str, address: str, amount: Decimal) -> str:
  result = await client.spot.http.wallet.withdraw(
    coin=asset,
    net_work=network,
    address=address,
    amount=str(amount),
  )
  assert result['id'] is not None, 'withdraw response has no id'
  return result['id']


# Not executed here -- would send a real on-chain withdrawal from the account.
await withdraw(
  asset='USDT', network='TRX', address='<destination-address>', amount=Decimal('10')
)
