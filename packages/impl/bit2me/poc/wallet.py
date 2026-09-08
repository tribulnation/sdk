# %%
from decimal import Decimal
from typing_extensions import Literal

from typed_bit2me import Bit2Me
from typed_bit2me.v1.wallet.currency.network import CurrencyNetwork
from typed_bit2me.v1.wallet.transactions.preview import Network
from typed_core.exceptions import ApiError, AuthError
from dotenv import load_dotenv

from tribulnation.sdk.wallet.deposit_methods import DepositMethod
from tribulnation.sdk.wallet.withdrawal_methods import WithdrawalMethod

load_dotenv()

client = await Bit2Me.new().__aenter__()

ASSETS = ['BTC', 'ETH', 'USDT', 'SOL']


# %% [markdown]
# ## `DepositMethods`
#
# Two sources, and only one of them sees more than one chain. `v2.currency.assets.list()`
# is public and lists every asset Bit2Me supports (503 today) with an `enabled` flag and an
# `addressRegex`, but its `network` field is a scalar display string -- `'BITCOIN'`,
# `'ETHEREUM (ERC20)'` -- so read on its own it collapses every multi-chain asset into one
# row and hides the rest.
#
# `v1.wallet.currency.network()` is the real per-asset chain list, and it is where the
# multi-network truth lives: BTC on 1 network, SOL on 1, ETH on 7 (Ethereum, Polygon, BSC,
# Optimism, Base, World Chain, Arbitrum) and USDT on 10 -- including the Tron and Polygon
# USDT the catalogue's single row cannot express. It's signed, and it's one call per asset.
#
# Its sibling `v1.wallet.network()` answers in a single call with all 144 networks, but it
# describes networks rather than assets: a row is `{id, name, nativeCurrencyCode,
# feeCurrencyCode, hasTag, isCaseSensitive, isMainnet}`, with no coin field anywhere. It
# can't say which chains carry USDT, so it can't stand in for the per-coin call here. Its
# two extra fields don't pay for a join either: `isMainnet` flags 9 test networks
# (`bitcoinTest`, `ethereumTestSepolia`, ...) that never show up in a per-coin list -- every
# network returned for 30 sampled assets was mainnet already -- and `isCaseSensitive`
# contradicts itself across identical address formats, true for `polygon` but false for
# `ethereum`, `base`, `arbitrum` and `optimism`. Neither has a home in `DepositMethod` or
# `WithdrawalMethod` in any case.
#
# Its `id` is a machine slug (`bitcoin`, `binanceSmartChain`) -- the same vocabulary
# `preview()` expects, which is what makes it usable as `DepositMethod.network` where the
# catalogue's display string isn't (see the withdrawal section). Fiat has no chains at all:
# `EUR`/`USD` answer 404 rather than `[]`, and a few listed crypto assets (`CFX`, `STABLE`)
# return an empty list.
#
# Neither source carries a deposit fee, a minimum-confirmations count, or a deposit-specific
# enabled flag -- the catalogue's `enabled` gates the whole asset, trading included. The
# per-network `hasTag` does say whether an address on that chain needs a memo (true for TON,
# XRP, XLM and Cosmos), but `DepositMethod` has no field to put it in.

# %%
async def coin_networks(coin: str) -> list[CurrencyNetwork]:
  """Every network Bit2Me supports for one asset, or `[]` when it has none (fiat 404s)."""
  try:
    return await client.v1.wallet.currency.network(coin)
  except ApiError as e:
    if e.args[0] != 404:
      raise
    return []


async def deposit_methods(*, assets: list[str] | None = None) -> list[DepositMethod]:
  catalogue = await client.v2.currency.assets.list()
  out: list[DepositMethod] = []
  for symbol, entry in catalogue.items():
    if assets is not None and symbol not in assets:
      continue
    if not entry.get('enabled'):
      continue
    # One signed call per asset -- unfiltered, that's 503 of them.
    for network in await coin_networks(symbol):
      out.append(
        DepositMethod(
          asset=symbol,
          network=network['id'],
          fee=None,
          contract_address=None,
          min_confirmations=None,
        )
      )
  return out


await deposit_methods(assets=ASSETS)

# %% [markdown]
# ## `WithdrawalMethods`
#
# Bit2Me exposes no static per-asset/network withdrawal fee schedule anywhere in
# `typed_bit2me` -- no `Currency`/`Asset` field carries one, and there's no dedicated
# "fee schedule" endpoint (searched the whole package for `fee`-adjacent field names on the
# currency/asset surfaces; nothing). The only place a real withdrawal fee shows up is
# `v1.wallet.transactions.preview()`, which builds a proforma withdrawal quote for a real
# amount + destination and returns the actual network fee that would be charged. Even when
# the account can't cover the requested amount, the resulting `not-enough-funds` error body
# still carries the computed `fee` (confirmed live below), so it's usable as a fee quote
# without needing a funded account for every asset.
#
# `preview()` speaks the network `id` from the per-coin list above -- verified live: all 19
# asset/network pairs quoted below are accepted, while the catalogue's display string is
# still rejected (`invalid network BITCOIN`). So the slug never has to be guessed at or
# curated by hand: `assets.list()` is simply the wrong side of the join, and the per-coin
# endpoint is the right one, for every asset rather than a handpicked few.
#
# What stays hand-curated is the destination address: `preview()` needs a syntactically
# valid one on the target network and nothing in the API vends a sample. It's now keyed by
# network rather than by asset, though, so one EVM address serves nine of the thirteen
# chains the demo assets span.
#
# Quoting a fee needs an API key holding the wallet-withdrawal permission; one without it
# reads both catalogues fine but gets `403 invalid credentials` from `preview()`. So
# `withdrawal_fee()` has three outcomes: a fee (the `not-enough-funds` body carries it),
# `'no-permission'` (403, folded to `fee=None` and named in a printed diagnostic), and
# anything else, which still raises. A missing permission costs the fees, not the method
# list -- all 19 rows enumerate either way. The run below holds the permission, so every
# row carries a real fee.
#
# `feeCurrencyCode` looks like it should fill `WithdrawalMethod.Fee.asset`, and doesn't: it
# names the chain's gas token, not what Bit2Me bills. A successful ETH-on-Polygon proforma
# quotes `{'amount': 0.0001, 'currency': 'ETH'}` while Polygon's `feeCurrencyCode` is
# `POL`, and USDT-on-BSC quotes 0.3 -- USDT, not 0.3 BNB. The fee is charged in the asset
# being withdrawn, which is what the `not-enough-funds` path below assumes.

# %%
# `preview()` needs a real, syntactically-valid address on the destination network, and
# nothing in the API vends one -- so this stays hand-curated. Keyed by the network `id`
# from `coin_networks()` rather than by asset, one EVM address covers nine chains.
EVM_ADDRESS = '0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045'
EVM_NETWORKS = [
  'ethereum',
  'polygon',
  'binanceSmartChain',
  'optimism',
  'base',
  'worldChain',
  'arbitrum',
  'celo',
  'plasma',
]
DEMO_ADDRESSES = {
  'bitcoin': '3FZbgi29cpjq2GjdwV8eyHuJJnkLtktZc5',
  'solana': 'GJRs4FwHtemZ5ZE9x3FNvJ8TMwitKF9yv9Y6Xfnrgok',
  'tron': 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t',
  'ton': 'EQCD39VS5jcptHL8vMjEXrzGaRcCVYto7HUn4bpAOg8xqB2N',
  **{network: EVM_ADDRESS for network in EVM_NETWORKS},
}
DEMO_AMOUNTS = {'BTC': '0.001', 'ETH': '0.01', 'USDT': '5', 'SOL': '0.01'}


async def withdrawal_fee(
  asset: str,
  *,
  network: str,
) -> WithdrawalMethod.Fee | Literal['no-permission'] | None:
  """
  Quote one asset/network withdrawal fee with a proforma.

  Returns:
    The fee; `'no-permission'` when the key may read the catalogues but not quote a
    proforma; `None` when no demo address or amount is on file for the pair.
  """
  address = DEMO_ADDRESSES.get(network)
  amount = DEMO_AMOUNTS.get(asset)
  if address is None or amount is None:
    return None
  net_fee: Network | None
  try:
    preview = await client.v1.wallet.transactions.preview(
      amount=amount,
      currency=asset,
      destination={'address': address, 'network': network},
    )
    net_fee = (preview.get('fee') or {}).get('network')
  except AuthError:
    # 403 `invalid credentials`. This key reads `assets.list()` and
    # `wallet.currency.network()` fine but lacks the wallet-withdrawal permission
    # `preview()` needs, so the fee is unknown here rather than absent from Bit2Me.
    # Reported by the caller instead of quietly becoming an indistinguishable `None`.
    return 'no-permission'
  except ApiError as e:
    # Even a `not-enough-funds` failure still reports the computed fee -- usable as a
    # quote without needing the account funded for every demo asset. Bit2Me's error
    # bodies vary by endpoint, so `raise_http_status` passes them through untyped;
    # anything without the nested `data.data` envelope is re-raised.
    if len(e.args) < 2:
      raise
    data = e.args[1].get('data', {}).get('data', {})
    if data.get('code') != 'not-enough-funds':
      raise
    net_fee = {'amount': data['fee'], 'currency': asset}
  if net_fee is None:
    return None
  return WithdrawalMethod.Fee(
    asset=net_fee['currency'], amount=Decimal(str(net_fee['amount']))
  )


async def withdrawal_methods(
  *,
  assets: list[str] | None = None,
  networks: list[str] | None = None,
) -> list[WithdrawalMethod]:
  catalogue = await client.v2.currency.assets.list()
  out: list[WithdrawalMethod] = []
  unquoted: list[str] = []
  for symbol, entry in catalogue.items():
    if assets is not None and symbol not in assets:
      continue
    if not entry.get('enabled'):
      continue
    for network in await coin_networks(symbol):
      if networks is not None and network['id'] not in networks:
        continue
      fee = await withdrawal_fee(symbol, network=network['id'])
      if fee == 'no-permission':
        unquoted.append(f'{symbol}/{network["id"]}')
        fee = None
      out.append(
        WithdrawalMethod(
          asset=symbol,
          network=network['id'],
          fee=fee,
          contract_address=None,
        )
      )
  if unquoted:
    print(
      f'! fee=None on {len(unquoted)}/{len(out)} methods: preview() answered 403 '
      'invalid credentials -- this API key lacks the wallet-withdrawal permission it '
      f'needs to quote a fee. Unquoted: {", ".join(unquoted)}'
    )
  return out


await withdrawal_methods(assets=ASSETS)

# %%
# Same call, narrowed to two networks. USDT on Tron is exactly the row `assets.list()`'s
# single `'ETHEREUM (ERC20)'` entry couldn't express, and Polygon carries both demo
# assets -- so this shows the filter cutting across assets and chains at once.
await withdrawal_methods(assets=ASSETS, networks=['polygon', 'tron'])


# %% [markdown]
# ## Account-scoped deposit address (not part of the abstract interface)
#
# `v2.wallet.pockets(pocket_id, network)` returns (creating one first if none exists yet)
# the deposit address for one of the account's own Wallet pockets on one network --
# authenticated and account-scoped, unlike the public per-asset catalogue above. Included as
# a real-data supplement, the way `kucoin/poc/wallet.ipynb`'s `deposit_addresses()` is:
# not because the abstract `Wallet` interface asks for it (it doesn't have an
# address-fetching method at all), but because it's the natural next read after
# `deposit_methods()`.

# %%
async def deposit_address(asset: str, *, network: str):
  pockets = await client.v1.wallet.pockets.get()
  pocket = next((p for p in pockets if p['currency'] == asset), None)
  if pocket is None:
    return None
  return await client.v2.wallet.pockets(pocket_id=pocket['id'], network=network)


await deposit_address('ETH', network='ethereum')


# %% [markdown]
# ## Withdraw (state-mutating -- written, never executed)
#
# Neither `DepositMethods` nor `WithdrawalMethods` includes an actual withdraw call --
# the abstract `Wallet` interface is read-only. `v1.wallet.transactions.execute()` (paired
# with the `preview()` proforma used for the fee quotes above) is the natural next step a
# real integration would need. Included only to show the mapping -- **never executed**.

# %%
async def withdraw(*, asset: str, network: str, address: str, amount: Decimal) -> str:
  proforma = await client.v1.wallet.transactions.preview(
    amount=str(amount),
    currency=asset,
    destination={'address': address, 'network': network},
  )
  result = await client.v1.wallet.transactions.execute(proforma=proforma['id'])
  return result['id']


# Not executed here -- would send a real on-chain withdrawal from the account.
await withdraw(
  asset='USDT', network='ethereum', address='<destination-address>', amount=Decimal('5')
)

# %% [markdown]
# ## Coverage
#
# **`DepositMethods`: supported, with gaps.** Asset + network takes two calls: the public
# `v2.currency.assets.list()` for the `enabled` set, then one signed
# `v1.wallet.currency.network()` per asset for its real chain list. That second call is
# per-asset, so an unfiltered enumeration costs one request per asset (503 today) and a real
# implementation would cache it; the one-call `v1.wallet.network()` doesn't avoid it, having
# no coin-to-network mapping to join on. `fee`, `min_confirmations` and `contract_address`
# are all `None` purely for lack of a source field: neither endpoint carries a fee-shaped
# key (checked across the whole 503-asset catalogue response), a confirmations count, or a
# contract address despite the catalogue's `isERC20Token` flag. Unlike KuCoin's `all_currencies()`, there's still no
# per-network deposit-enabled flag distinct from the whole-asset `enabled` one. `hasTag` is
# the one genuinely new field with nowhere to go: neither `DepositMethod` nor
# `WithdrawalMethod` has a memo/tag field, and `preview()`'s `Destination` has no tag key
# either -- so a TON or XRP withdrawal can be quoted here but not actually addressed
# through this typed surface.
#
# **`WithdrawalMethods`: partially supported.** Same enumeration as `DepositMethods`, and
# `fee` populates for every network the notebook holds a demo address for, via the
# `preview()` trick -- which needs a key holding the wallet-withdrawal permission. A key
# without it gets `403 invalid credentials`, and the run degrades to the full method list
# with `fee=None` plus a printed diagnostic naming the unquoted pairs, rather than losing
# every row to one permission gap. No part of the
# asset/network enumeration is hand-written: the per-coin endpoint's `id` is exactly the
# slug `preview()` expects, so the display-vs-slug mismatch that would otherwise force a
# curated map never comes up. What remains hand-written is one
# destination address per network, and there's still no static, generically-derivable fee
# schedule in `typed_bit2me` at all -- every fee costs a proforma quote against a real
# address and amount. A real implementation covering every asset would need a sample
# address per network (or the user's own) plus one `preview()` per asset/network pair.
#
# `v2.wallet.pockets` (account-scoped deposit address) and
# `v1.wallet.transactions.{preview,execute}` (withdrawal) are outside the abstract `Wallet`
# interface -- included as supplements. The withdraw cell is written but not executed.
