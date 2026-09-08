# %%
from datetime import datetime, timezone
from decimal import Decimal

from typed_bybit import Bybit
from typed_bybit.asset.withdraw.create import WithdrawCreateResult
from dotenv import load_dotenv

from tribulnation.sdk.wallet.deposit_methods import DepositMethod
from tribulnation.sdk.wallet.withdrawal_methods import WithdrawalMethod

load_dotenv()

client = await Bybit.new().__aenter__()

ASSETS = ['BTC', 'ETH', 'USDT', 'USDC']


# %% [markdown]
# ## `DepositMethods.deposit_methods`

# %%
async def deposit_methods(*, assets: list[str] | None = None) -> list[DepositMethod]:
  raw = await client.asset.coin_info()
  out: list[DepositMethod] = []
  for row in raw['rows']:
    if assets is not None and row['coin'] not in assets:
      continue
    for chain in row['chains']:
      if chain['chainDeposit'] != '1':
        continue
      out.append(
        DepositMethod(
          asset=row['coin'],
          network=chain['chain'],
          # Bybit deposits are free; coin_info carries no deposit fee field.
          contract_address=chain['contractAddress'] or None,
          min_confirmations=int(chain['confirmation'])
          if chain.get('confirmation')
          else None,
        )
      )
  return out


await deposit_methods(assets=ASSETS)

# %% [markdown]
# ### Deposit address — read-only exploration

# %%
await client.asset.deposit.master_address(coin='USDT')


# %% [markdown]
# ## `WithdrawalMethods.withdrawal_methods`

# %%
async def withdrawal_methods(
  *,
  assets: list[str] | None = None,
  networks: list[str] | None = None,
) -> list[WithdrawalMethod]:
  raw = await client.asset.coin_info()
  out: list[WithdrawalMethod] = []
  for row in raw['rows']:
    if assets is not None and row['coin'] not in assets:
      continue
    for chain in row['chains']:
      if chain['chainWithdraw'] != '1':
        continue
      if networks is not None and chain['chain'] not in networks:
        continue
      # `withdrawFee` is required, and already a parsed `Decimal` -- but declared
      # `Literal[''] | Decimal`, since it is `''` on the 16 chains that support no
      # withdrawal at all (none of which get past the `chainWithdraw` filter above).
      # Compare against `''` rather than testing truthiness: 8 of the withdraw-enabled
      # chains for these four assets charge exactly `0`, and a free withdrawal is not
      # the same thing as an unknown fee.
      raw_fee = chain['withdrawFee']
      fee = (
        None
        if raw_fee == ''
        else WithdrawalMethod.Fee(asset=row['coin'], amount=raw_fee)
      )
      out.append(
        WithdrawalMethod(
          asset=row['coin'],
          network=chain['chain'],
          fee=fee,
          contract_address=chain['contractAddress'] or None,
        )
      )
  return out


await withdrawal_methods(assets=ASSETS)


# %% [markdown]
# ### `withdraw.create` — written, not executed

# %%
async def withdraw(
  coin: str, chain: str, address: str, amount: Decimal
) -> WithdrawCreateResult:
  """Submit a withdrawal request. Requires the API key's Withdraw permission and,
  typically, an allowlisted destination address."""
  return await client.asset.withdraw.create(
    coin=coin,
    chain=chain,
    address=address,
    amount=str(amount),
    # `timestamp` is declared as `TimestampMillis` (`Annotated[datetime, ...]`), and
    # the client now serializes request bodies through the request type's validator,
    # so a real `datetime` is both what type-checks and what reaches the wire as
    # Bybit's documented millisecond epoch.
    timestamp=datetime.now(timezone.utc),
    # `accountType` here is the withdrawal-source wallet enum (`FUND`/`UTA`/`EARN`),
    # a different vocabulary from `account.wallet_balance`'s `accountType`
    # (`UNIFIED`/`CONTRACT`/`SPOT`) used elsewhere in this notebook -- `'UNIFIED'`
    # isn't even a member of this endpoint's enum. `'UTA'` (Unified Trading Account)
    # is the correct value for withdrawing from the same unified account balance
    # queried throughout the rest of this notebook.
    account_type='UTA',
  )


# Not executed here -- would submit a real withdrawal off the account.
await withdraw('USDT', 'TRX', 'Txxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', Decimal('10'))

# %% [markdown]
# ### Coverage assessment
#
# **Fully supported.** `asset.coin_info` (public, no auth) enumerates every
# coin/chain combination -- 793 coins live -- with fee, minimum, contract address and
# per-side deposit/withdraw availability flags in one call, cleanly covering both
# `DepositMethod` and `WithdrawalMethod`.
#
# Deposits are free on Bybit, so `DepositMethod.fee` is always `None` here --
# `coin_info` carries no deposit-fee field, only `withdrawFee`. One thing dropped in
# the mapping: `withdrawPercentageFee`, a second percentage-based fee component Bybit
# applies on top of the fixed `withdrawFee`. It is `"0"` on all but two coin/chain
# pairs in the live response (`LUNC` and `USTC` on `LUNA`, both `"0.005"`), but the
# SDK's `Fee` shape (`asset`, `amount`) has no field for a percentage component, so
# only the fixed fee is carried over.
#
# Deposit addresses (`asset.deposit.master_address`) work live against the account.
# `asset.withdraw.create` is written above but never executed, since it would move
# real funds off the account.
#
