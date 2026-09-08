# %%
from decimal import Decimal

from typed_kucoin import KuCoin
from typed_kucoin.account.deposit.address import DepositAddressV3Row
from dotenv import load_dotenv

from tribulnation.sdk.wallet.deposit_methods import DepositMethod
from tribulnation.sdk.wallet.withdrawal_methods import WithdrawalMethod

load_dotenv()

client = await KuCoin.new().__aenter__()

ASSETS = ['BTC', 'ETH', 'USDT', 'KCS', 'SOL']


# %% [markdown]
# ## `DepositMethods`
#
# `spot.all_currencies()` is public (no credentials needed) and lists every currency
# KuCoin supports along with its `chains`, one entry per blockchain network -- exactly the
# per-network deposit/withdrawal parameters `DepositMethod`/`WithdrawalMethod` need.
# Deposits are free on KuCoin (only withdrawals carry a fee), so `fee` is always `None`
# here.

# %%
async def deposit_methods(*, assets: list[str] | None = None) -> list[DepositMethod]:
  currencies = await client.spot.all_currencies()
  out: list[DepositMethod] = []
  for c in currencies:
    if assets is not None and c['currency'] not in assets:
      continue
    for chain in c['chains'] or []:
      if not chain['isDepositEnabled']:
        continue
      out.append(
        DepositMethod(
          asset=c['currency'],
          network=chain['chainId'],
          fee=None,
          contract_address=chain['contractAddress'] or None,
          min_confirmations=chain['confirms'],
        )
      )
  return out


await deposit_methods(assets=ASSETS)


# %% [markdown]
# ## `WithdrawalMethods`
#
# Same `all_currencies()` call; `withdrawalMinFee` becomes the `Fee`, and `networks` is an
# extra client-side filter on `chainId` (KuCoin doesn't take it as a request parameter --
# there's no per-network lookup, only per-currency).

# %%
async def withdrawal_methods(
  *,
  assets: list[str] | None = None,
  networks: list[str] | None = None,
) -> list[WithdrawalMethod]:
  currencies = await client.spot.all_currencies()
  out: list[WithdrawalMethod] = []
  for c in currencies:
    if assets is not None and c['currency'] not in assets:
      continue
    for chain in c['chains'] or []:
      if networks is not None and chain['chainId'] not in networks:
        continue
      if not chain['isWithdrawEnabled']:
        continue
      out.append(
        WithdrawalMethod(
          asset=c['currency'],
          network=chain['chainId'],
          fee=WithdrawalMethod.Fee(
            asset=c['currency'], amount=Decimal(chain['withdrawalMinFee'])
          ),
          contract_address=chain['contractAddress'] or None,
        )
      )
  return out


await withdrawal_methods(assets=ASSETS)

# %%
# Same call, narrowed to one network -- e.g. only TRC20 USDT/USDT-adjacent withdrawal methods.
await withdrawal_methods(assets=['USDT', 'BTC'], networks=['trx'])


# %% [markdown]
# ### Coverage assessment: `Wallet`
#
# **Fully supported.** `spot.all_currencies()` is public, unauthenticated, and returns the
# complete per-network deposit/withdrawal configuration (enabled flags, min confirmations,
# contract address, withdrawal fee) for every currency in one call -- no account-specific
# state is needed to answer either `deposit_methods()` or `withdrawal_methods()`, and no
# pagination or chunking is required. The one caveat: KuCoin reports a flat
# `withdrawalMinFee` per network rather than a fee schedule, so `WithdrawalMethod.fee` is
# the *minimum* fee, not necessarily the fee a specific withdrawal will actually be charged
# (`account.withdrawals.quotas` returns the same `withdrawMinFee` figure, confirming this
# is the number KuCoin itself treats as authoritative, not just a floor).

# %% [markdown]
# ## Account-scoped supplementary reads (not part of the abstract interface)
#
# `account.deposit.address` is authenticated and account-scoped (existing generated
# addresses only), unlike the public per-network data above -- included here as a
# real-data supplement, not because the SDK interface asks for it.

# %%
async def deposit_addresses(currency: str) -> list[DepositAddressV3Row]:
  return await client.account.deposit.address(currency=currency)


await deposit_addresses('USDT')


# %% [markdown]
# ## Withdraw (state-mutating -- written, never executed)
#
# `account.withdrawals.withdraw` isn't part of `WithdrawalMethods` (the abstract interface
# is read-only), but is the natural next step. Included only to show the mapping --
# **never executed**.

# %%
async def withdraw(*, asset: str, network: str, address: str, amount: Decimal) -> str:
  result = await client.account.withdrawals.withdraw(
    currency=asset,
    to_address=address,
    amount=amount,
    withdraw_type='ADDRESS',
    chain=network,
  )
  return result['withdrawalId']


# Not executed here -- would send a real on-chain withdrawal from the account.
await withdraw(
  asset='USDT', network='trx', address='<destination-address>', amount=Decimal('10')
)
