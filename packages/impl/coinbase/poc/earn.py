# %%
from typing_extensions import Collection

from typed_coinbase import Coinbase
from dotenv import load_dotenv

from tribulnation.sdk.earn.instruments import Instrument, InstrumentTag

load_dotenv()

client = await Coinbase.new().__aenter__()

ASSETS = ['ETH', 'BTC', 'USDC']

# %% [markdown]
# ## `Earn` — instruments

# %% [markdown]
# Coinbase's App tier has no dedicated earn/staking product API: no catalogue of
# subscribable instruments, no subscribe/redeem endpoints. `app.accounts` and
# `app.advanced_trade` were both searched (per the client's generated endpoint tree in
# `typed_coinbase/app/{accounts,advanced_trade}`) and neither exposes anything under an
# `earn`/`staking` namespace.
#
# The client's *other* top-level surface does, though — the one `wallet.ipynb` already
# reaches for the network catalogue. `client.exchange.http.wrapped_assets` is a real,
# browsable earn catalogue: `list()` and `get(id)` are unauthenticated (verified live) and
# `get('CBETH')` returns `apy` `0.0237` and `redeem_time_estimate_days` `9.01` for Coinbase
# Wrapped Staked ETH, without holding any of it. `stake_wrap_create`/`redeem_create` on the
# same surface are genuine subscribe/redeem calls, gated behind Coinbase Exchange's
# `cb-access-*` HMAC scheme rather than this key — a signed sibling,
# `exchange.http.loans.assets()`, fails live with *"No credentials: this client was built
# with exchange_public=True"*. `instruments()` below reads that catalogue alongside the
# account-level signal.
#
# The closest App-tier signal is incidental: Coinbase auto-enrolls certain assets (e.g. ETH) in
# a rewards program and reflects it as an opaque `rewards` blob (`{apy, formatted_apy,
# label}`) on that currency's `AccountCurrency`, returned by `app.accounts.list`/`.get`. It
# shows up only on accounts the user already holds (there is no way to list *which* assets
# are eligible ahead of holding them), carries no `id`/min/max/duration, and there is no
# `subscribe`/`redeem` call — the "instrument" isn't something this API lets a caller act
# on, only observe after the fact. `app.accounts.transactions.list`'s `type` enum also
# includes `earn_payout`/`staking_transfer`/`unstaking_transfer` (settlement records for
# this same passive program, and live rows carry a `staking_reward` type the enum doesn't
# declare at all -- see `reporting.ipynb`), reinforcing that Earn is a background account
# feature on this tier, not a tradable product surface.
#
# Two further staking/rewards product APIs sit outside this client entirely, and neither
# closes the remaining gap:
#
# - **Staking API** — protocol docs (shared-ETH, dedicated-ETH validators, SOL) at
#   [docs.cdp.coinbase.com/staking/staking-api](https://docs.cdp.coinbase.com/staking/staking-api/introduction/welcome).
#   **Correction**: this was previously believed to need a separate "CDP secret API key",
#   distinct from this client's App-tier credentials. That's wrong — verified live below,
#   the exact same `COINBASE_API_KEY_NAME`/`COINBASE_PRIVATE_KEY` CDP API Key authenticates
#   fine against the Staking API's host. The real gap is architectural, not credential-based:
#   every Staking API endpoint (`list-validators`, `get-staking-context`,
#   `fetch-staking-rewards`, `stake/build`) operates on an externally-supplied onchain wallet
#   address the caller controls, not a Coinbase App account balance — and none of them
#   returns a browsable catalogue of assets/APY/min-max amounts independent of an address.
#   It's a "build and track staking transactions for a wallet you hold the key to" API, not
#   a "browse subscribable products" API like Binance/Bitget Earn.
# - **USDC Rewards** — up to ~3.35% APY on qualifying USDC balances:
#   [docs.cdp.coinbase.com/wallets/usdc-rewards](https://docs.cdp.coinbase.com/wallets/usdc-rewards).
#   Documented as applying only to CDP non-custodial wallets; custodial (Coinbase App)
#   account support is explicitly listed there as "coming soon", not yet live.
#

# %% [markdown]
# #### Live verification: does the App-tier key actually work against the Staking API?
#
# Reusing this client's own JWT-signing internals (`typed_coinbase.core.auth`'s
# `Credentials`/`resolve_credentials`/`auth_headers` — the same `_build_jwt` logic
# `HttpRpcClient.authed_request` uses against `api.coinbase.com`, see
# `core/transport/http.py`), just signed against the Staking API's own host
# (`api.cdp.coinbase.com`) and paths instead. No new credentials, no new signing code.

# %%
import httpx

from typed_coinbase.core.auth import resolve_credentials, auth_headers

STAKING_HOST = 'api.cdp.coinbase.com'
STAKING_BASE_URL = 'https://api.cdp.coinbase.com'

staking_credentials = resolve_credentials(None, None, public=False)
# `public=False` either returns real `Credentials` or raises `AuthError` -- it never
# actually returns `None` -- but the two behaviors aren't distinguished by an overload,
# so the declared return type is still `Credentials | None`.
assert staking_credentials is not None
staking_http = httpx.AsyncClient()

# `list-validators` needs only a network + asset, no address -- the closest thing the
# Staking API has to a catalogue endpoint. Signed with the exact same `Credentials` /
# `auth_headers` this client already uses against `api.coinbase.com`, just pointed at the
# Staking API's own host.
list_validators_path = '/platform/v1/networks/ethereum-mainnet/assets/eth/validators'
list_validators_headers = auth_headers(
  staking_credentials, method='GET', host=STAKING_HOST, path=list_validators_path
)
list_validators_response = await staking_http.get(
  STAKING_BASE_URL + list_validators_path, headers=list_validators_headers
)
(list_validators_response.status_code, list_validators_response.text)

# %%
# `get-staking-context` requires a real onchain address (read-only balance snapshot,
# no staking/unstaking action) -- used the well-known Ethereum "dead" burn address, just
# to see whether the *credential* is accepted before any address-specific logic runs.
stake_context_path = '/platform/v1/stake/context'
stake_context_headers = auth_headers(
  staking_credentials, method='POST', host=STAKING_HOST, path=stake_context_path
)
stake_context_response = await staking_http.post(
  STAKING_BASE_URL + stake_context_path,
  headers=stake_context_headers,
  json={
    'network_id': 'ethereum-mainnet',
    'asset_id': 'eth',
    'address_id': '0x000000000000000000000000000000000000dead',
    'options': {'mode': 'partial'},
  },
)
await staking_http.aclose()
(stake_context_response.status_code, stake_context_response.text)


# %% [markdown]
# Both requests come back **`200`**, not `401`/`403` — the existing App-tier CDP API Key
# authenticates against the Staking API host with no changes. `list-validators` returns an
# empty (but successfully authenticated) list — this CDP project has no dedicated-ETH
# validators provisioned. `get-staking-context` returns a real balance snapshot for the
# queried address (the dead-address' actual stakeable ETH balance, in wei).
#
# Checked every documented Staking API endpoint's schema
# ([list-validators](https://docs.cdp.coinbase.com/api-reference/rest-api/staking/list-validators),
# [get-staking-context](https://docs.cdp.coinbase.com/api-reference/rest-api/staking/get-staking-context),
# [fetch-staking-rewards](https://docs.cdp.coinbase.com/api-reference/rest-api/staking/fetch-staking-rewards),
# `stake/build`) for an APY/reward-rate/min-amount field: none exists anywhere in the API.
# Every endpoint is scoped to a specific onchain address (a balance snapshot, historical
# reward payouts, or an unsigned transaction to sign) — there is no way to ask "what can I
# stake, and at what rate" independent of already holding a position. So even with working
# credentials, the Staking API cannot back `instruments()`: not a permissions gap, an
# architecture gap. The best-effort `rewards.apy` inference below remains the only signal.

# %%
async def instruments(
  *,
  tags: Collection[InstrumentTag] | None = None,
  assets: Collection[str] | None = None,
) -> list[Instrument]:
  """Two live sources, neither a full Earn catalogue: the `rewards.apy` blob carried by
  held accounts, and Coinbase Exchange's public wrapped-asset list -- see above."""
  out: list[Instrument] = []
  seen: set[str] = set()

  page = await client.app.accounts.list(limit=100)
  for account in page['data']:
    currency = account['currency']
    rewards = currency.get('rewards')
    code = currency['code']
    if not rewards or code in seen:
      continue
    seen.add(code)
    out.append(
      Instrument(tags=['staking', 'flexible'], asset=code, apr=rewards['apy'])
    )

  # `GET /wrapped-assets` omits the per-asset detail the single-asset route carries, so
  # `apy` is read from `get(id)` -- both unauthenticated. The catalogue names only the
  # wrapped asset (`CBETH`) and nothing in the response links it back to the asset it is
  # staked from, so the wrapped id stands as `asset`.
  wrapped = await client.exchange.http.wrapped_assets.list()
  for entry in wrapped['wrapped_assets']:
    detail = await client.exchange.http.wrapped_assets.get(entry['id'])
    # `apy` and `redeem_time_estimate_days` are `Literal[''] | Decimal`: the list route
    # blanks both, the single-asset route fills them in.
    apy = detail['apy']
    if not apy or detail['id'] in seen:
      continue
    seen.add(detail['id'])
    out.append(
      Instrument(
        tags=['staking', 'flexible'],
        asset=detail['id'],
        apr=apy,
        id=detail['id'],
      )
    )

  if assets is not None:
    out = [instrument for instrument in out if instrument.asset in assets]
  if tags is not None:
    out = [instrument for instrument in out if set(instrument.tags) & set(tags)]
  return out


await instruments()

# %% [markdown]
# ### Coverage
#
# | Method | Status |
# | --- | --- |
# | `instruments()` | Partially supported, live-tested above, from two sources. (1) Coinbase Exchange's wrapped-asset catalogue, reached through this client's own `exchange` surface with no credentials: `CBETH` (Coinbase Wrapped Staked ETH) at `apr` `0.0237`, browsable without holding it, with `stake_wrap_create`/`redeem_create` as real subscribe/redeem calls on the same surface -- gated behind Exchange's `cb-access-*` HMAC scheme, which this key is not issued under. It names only the wrapped asset, never the asset it is staked from, and carries no min/max or duration (`redeem_time_estimate_days` `9.01` is an unwrap delay, not a term). (2) The App tier's `rewards.apy` blob on accounts the caller already holds (real output above: this account's ETH wallets, apr `0.0161`) -- no `id`, min/max, url or duration there either. What neither gives is the Binance/Bitget-style Earn product list; the [Staking API](https://docs.cdp.coinbase.com/staking/staking-api/introduction/welcome) was checked live (see the verification cells above) and its App-tier CDP API Key **does** authenticate, but every endpoint (`list-validators`, `get-staking-context`, `fetch-staking-rewards`, `stake/build`) is scoped to a specific externally-supplied onchain wallet address and none expose APY or a browsable catalogue independent of one. [USDC Rewards](https://docs.cdp.coinbase.com/wallets/usdc-rewards) remains out of reach for a different reason -- documented as non-custodial-wallet-only, with custodial (Coinbase App) support listed there as "coming soon". |
