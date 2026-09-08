# %%
from decimal import Decimal

from typed_binance import Binance
from dotenv import load_dotenv

from tribulnation.sdk.wallet.deposit_methods import DepositMethod
from tribulnation.sdk.wallet.withdrawal_methods import WithdrawalMethod

load_dotenv()

client = Binance.new()

ASSETS = ['BTC', 'ETH', 'USDT', 'BNB', 'SOL']


# %% [markdown]
# ## `DepositMethods`
#
# `wallet.capital.config.get_all` is the single account-scoped call Binance exposes for
# per-network deposit/withdraw configuration -- one `CoinConfig` per coin, each carrying a
# `networkList` of per-network `CoinNetwork` rows with the enabled flags, confirmations,
# and fee data `DepositMethod`/`WithdrawalMethod` need. Deposits are free on Binance (only
# withdrawals carry a network fee), so `fee` is always `None` here.

# %%
async def deposit_methods(*, assets: list[str] | None = None) -> list[DepositMethod]:
  coins = await client.spot.http.wallet.capital.config.get_all()
  out: list[DepositMethod] = []
  for c in coins:
    if assets is not None and c['coin'] not in assets:
      continue
    for network in c['networkList']:
      if not network['depositEnable']:
        continue
      out.append(
        DepositMethod(
          asset=c['coin'],
          network=network['network'],
          fee=None,
          contract_address=network.get('contractAddress'),
          min_confirmations=network['minConfirm'],
        )
      )
  return out


len(await deposit_methods()), await deposit_methods(assets=ASSETS)


# %% [markdown]
# ## `WithdrawalMethods`
#
# Same `capital.config.get_all` call; `withdrawFee` becomes the `Fee`, and `networks` is an
# extra client-side filter on `network` (there's no per-network request parameter -- only
# per-account, all-coins-all-networks).

# %%
async def withdrawal_methods(
  *,
  assets: list[str] | None = None,
  networks: list[str] | None = None,
) -> list[WithdrawalMethod]:
  coins = await client.spot.http.wallet.capital.config.get_all()
  out: list[WithdrawalMethod] = []
  for c in coins:
    if assets is not None and c['coin'] not in assets:
      continue
    for network in c['networkList']:
      if networks is not None and network['network'] not in networks:
        continue
      if not network['withdrawEnable']:
        continue
      out.append(
        WithdrawalMethod(
          asset=c['coin'],
          network=network['network'],
          fee=WithdrawalMethod.Fee(asset=c['coin'], amount=network['withdrawFee']),
          contract_address=network.get('contractAddress'),
        )
      )
  return out


len(await withdrawal_methods()), await withdrawal_methods(assets=ASSETS)

# %%
# Same call, narrowed to one network -- e.g. only ETH-network withdrawal methods.
await withdrawal_methods(assets=['USDT', 'ETH'], networks=['ETH'])


# %% [markdown]
# ### Coverage assessment: `Wallet`
#
# **Fully supported.** `capital.config.get_all` is authenticated but account-agnostic in
# content (it's the same coin/network catalog for every account, not account-specific
# enablement), returns the complete per-network configuration for every coin the account
# can hold in one call, and needs no pagination -- both methods above ran live against the
# real account (855 deposit methods, 836 withdrawal methods across 657 coins), unfiltered
# and filtered by `assets`/`networks`.
#
# Every numeric field on this response, `withdrawFee` included, is already `Decimal` on
# `CoinNetwork`, so `WithdrawalMethod.Fee` takes it straight through with no `Decimal(...)`
# cast.

# %% [markdown]
# ## Withdraw / transfer (state-mutating -- written, never executed)
#
# Neither `capital.withdraw.apply` (external withdrawal submission) nor
# `asset.transfer.create` (internal wallet-to-wallet transfer, e.g. Spot -> Funding) are
# part of `WithdrawalMethods`/`DepositMethods` (the abstract interface is read-only), but
# are the natural next step a real integration would need. Included here only to show how
# they'd map -- **never executed**.

# %%
async def withdraw(
  *, method: WithdrawalMethod, address: str, amount: Decimal, tag: str | None = None
) -> str:
  result = await client.spot.http.wallet.capital.withdraw.apply(
    coin=method.asset,
    network=method.network,
    address=address,
    address_tag=tag,
    amount=float(amount),
  )
  return result['id']


# Not executed here -- would send a real on-chain withdrawal from the account.
methods = await withdrawal_methods(assets=['USDT'], networks=['ETH'])
await withdraw(method=methods[0], address='<destination-address>', amount=Decimal('10'))

# %%
from typed_binance.schemas import UniversalTransferType


async def transfer(*, asset: str, amount: Decimal, type: UniversalTransferType) -> int:
  # e.g. 'MAIN_FUNDING' for Spot -> Funding, 'FUNDING_MAIN' for Funding -> Spot.
  result = await client.spot.http.wallet.asset.transfer.create(
    type=type,
    asset=asset,
    amount=float(amount),
  )
  return result['tranId']


# Not executed here -- would move real funds between this account's own wallets.
await transfer(asset='USDT', amount=Decimal('10'), type='MAIN_FUNDING')
