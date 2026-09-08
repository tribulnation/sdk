# %% [markdown]
# # `Wallet` -- not supported for a retail Coinbase App account
#
# The `Wallet` surface (`DepositMethods`, `WithdrawalMethods`) has no honest implementation
# against a retail Coinbase **App** account, so there is nothing to run in this notebook. What
# follows is why.
#
# The short version: the App API publishes no per-asset network catalogue and no withdrawal-fee
# source. Coinbase **Exchange** publishes a catalogue, and its public routes answer even to this
# credential-less client -- but it describes a different product, and over-lists what this
# account can actually reach.

# %% [markdown]
# ## Two Coinbase products, one client
#
# `typed_coinbase` fronts two separate Coinbase products, and that distinction is the whole
# question here.
#
# | product | this key | what it knows |
# | --- | --- | --- |
# | Coinbase **App** (v2 + Advanced Trade) | a CDP key for a retail account | this account: its wallets, provisioned receive addresses, linked payment methods |
# | Coinbase **Exchange** | no credentials at all (`exchange_public=True`, `Coinbase.new()`'s default) | Exchange's own catalogue, over unauthenticated routes |
#
# Exchange's [`GET /currencies`](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/currencies/get-all-known-currencies)
# answers because it needs no credentials -- which is also why it cannot know anything about this
# App account.

# %% [markdown]
# ## `DepositMethods`
#
# No App endpoint lists the networks an asset can be deposited over.
#
# App v2's own reference list, `GET /v2/currencies/crypto`, is 409 entries of `code`, `name`,
# `color`, `sort_index`, `exponent`, `type`, `address_regex` and `asset_id` -- no network among
# them. Nothing else on the surface carries one either: across all 76 App endpoints `network`
# appears only on individual resources (an address's `network`, a transaction's
# `network.network_name`), never as a per-asset list. There is no App answer to "which networks
# does BTC support", the way Binance's `capital/config/getall` answers it.
#
# The only App-native way to discover a network is to mint a receive address:
# `app.accounts.addresses.create` takes `network=` and rejects what the account cannot use. That
# is a mutating POST, and one address at a time is not a catalogue.

# %% [markdown]
# ## `WithdrawalMethods`
#
# Two independent gaps, either one fatal.
#
# **No network catalogue.** Crypto withdrawal on App is an arbitrary-destination send
# (`app.accounts.transactions.create`, `type: 'send'`): the caller supplies the address and
# optionally a `network`, and nothing enumerates which networks are allowed. Only the fiat rails
# are enumerable, from this account's linked payment methods
# (`GET /api/v3/brokerage/payment_methods`) -- one rail of two.
#
# **No fee source.** The App surface is 76 endpoints across 66 REST paths, and none of them
# prices a withdrawal before it happens. `fee` appears only retrospectively -- `V2Transfer.fee`
# on a completed fiat withdrawal, `network.transaction_fee` on an executed send -- and not as a
# schedule: this account's four visible USDC sends on `arbitrum` recorded 0.000478, 0.000000,
# 0.000000 and no fee field at all. The send endpoint has no dry-run, and `orders/preview` is a
# trading endpoint. `exchange.http.withdrawals.fee_estimate` is not the missing piece: it prices
# a withdrawal out of a Coinbase **Exchange** account, which this key does not have. Exchange
# credentials would not fix it -- they would price a different product's withdrawal.

# %% [markdown]
# ## Why not borrow Exchange's catalogue
#
# It is the tempting shortcut: `GET /currencies/{id}` returns `supported_networks[]`, it maps
# cleanly onto `DepositMethod`/`WithdrawalMethod`, and this client can call it today. It would
# also be wrong in a way the caller could not detect.
#
# The route is account-blind by construction -- a bare `httpx` request carrying no
# `Authorization` and no `cb-access-*` headers gets the same 200 -- and it over-lists what this
# account can reach:
#
# - **PYUSD**: Exchange lists it on `ethereum` and `solana`; this App wallet refuses to issue a
#   PYUSD address at all (400, "This asset is not eligible for address generation").
# - **ETH**: Exchange lists six networks; the account's staking wallet issues none of them (400).
# - **Catalogue size**: 505 Exchange currencies against App v2's 409 -- 87 crypto currencies
#   Exchange lists and App does not, and none the other way. A strict superset.
#
# Nothing contradicts Exchange in the opposite direction, so the list is directionally right. It
# is just not this account's: a caller asking where USDC can be deposited would get fourteen
# networks, exactly one of which this wallet has ever been given an address on.

# %% [markdown]
# ## Coverage
#
# | Method | Status |
# | --- | --- |
# | `deposit_methods` | Not supported. App publishes no per-asset network catalogue, and the only App-native discovery is `addresses.create`, a mutating call. |
# | `withdrawal_methods` | Not supported. No crypto-network catalogue, and no withdrawal-fee source anywhere on the App surface -- Exchange's `fee_estimate` prices a different product. |
