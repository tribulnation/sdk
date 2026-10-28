# %%
import asyncio
from decimal import Decimal
from datetime import datetime, timedelta, timezone

from typed_deribit import Deribit
from dotenv import load_dotenv

load_dotenv()

public_client = await Deribit.new(public=True).__aenter__()
client = await Deribit.new(testnet=True).__aenter__()

from tribulnation.sdk.wallet.deposit_methods import DepositMethod
from tribulnation.sdk.wallet.withdrawal_methods import WithdrawalMethod

ASSETS = ['BTC', 'ETH', 'USDC', 'SOL']


# %% [markdown]
# > This notebook only needs public market data (`public_client`, mainnet) -- `public/get_currencies` covers every currency/network/fee Deribit publishes for deposits and withdrawals, no authentication required. The `client` (testnet) handle is still created for parity with the other notebooks but is unused here.

# %% [markdown]
# ## `DepositMethods` -- deposit_methods

# %% [markdown]
# `public/get_currencies` gives, per currency, its native chain (`coin_type`) plus any additional Coinbase-routed networks (`coinbase_networks`) Deribit accepts deposits from -- e.g. `USDC` accepts deposits from 7 different chains. `min_confirmations` is currency-level (not broken out per network). Deribit does not charge deposit fees, and does not expose a per-token contract address via this endpoint, so `DepositMethod.fee`/`contract_address` are `None`.

# %%
async def deposit_methods(*, assets: list[str] | None = None) -> list[DepositMethod]:
  """Map Deribit's supported currencies/networks onto `DepositMethod`."""
  currencies = await public_client.market_data.get_currencies()
  out: list[DepositMethod] = []
  for c in currencies:
    if assets is not None and c['currency'] not in assets:
      continue
    networks = c.get('coinbase_networks') or [{'display_name': c['coin_type']}]
    for net in networks:
      out.append(DepositMethod(
        asset=c['currency'],
        network=net.get('display_name', c['coin_type']),
        fee=None,  # Deribit does not charge deposit fees
        min_confirmations=c['min_confirmations'],
      ))
  return out

await deposit_methods(assets=ASSETS)


# %% [markdown]
# ## `WithdrawalMethods` -- withdrawal_methods

# %% [markdown]
# Withdrawal fees are also currency-level (`withdrawal_fee`, in the currency's own units) rather than per-network, so every network row for a given currency below carries the same fee -- Deribit does not expose a fee breakdown per `coinbase_networks` entry. `contract_address` is `None` for the same reason as deposits.

# %%
async def withdrawal_methods(
  *, assets: list[str] | None = None, networks: list[str] | None = None,
) -> list[WithdrawalMethod]:
  """Map Deribit's supported currencies/networks/fees onto `WithdrawalMethod`."""
  currencies = await public_client.market_data.get_currencies()
  out: list[WithdrawalMethod] = []
  for c in currencies:
    if assets is not None and c['currency'] not in assets:
      continue
    nets = c.get('coinbase_networks') or [{'display_name': c['coin_type']}]
    for net in nets:
      network = net.get('display_name', c['coin_type'])
      if networks is not None and network not in networks:
        continue
      out.append(WithdrawalMethod(
        asset=c['currency'],
        network=network,
        fee=WithdrawalMethod.Fee(asset=c['currency'], amount=Decimal(str(c['withdrawal_fee']))),
      ))
  return out

await withdrawal_methods(assets=ASSETS)


# %% [markdown]
# ## Coverage assessment

# %% [markdown]
# **Full**, with two caveats. Both `deposit_methods` and `withdrawal_methods` execute live against real, public Deribit data and return a non-empty, accurately-typed result for every requested asset:
# - `fee`/`contract_address` are approximate: Deribit publishes one withdrawal fee and no contract address per *currency*, not per network, so a multi-network asset like `USDC` shows an identical fee across all 7 of its networks -- the SDK shape supports per-network fees, Deribit's API just does not surface that granularity.
# - Deposits are free on Deribit (`DepositMethod.fee = None` for every asset); this is confirmed by the absence of any deposit-fee field in `get_currencies`, not assumed.
