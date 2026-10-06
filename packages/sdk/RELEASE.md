# tribulnation-sdk 2.11.0

SDK roots no longer contain implicit accounts. `MarketSDK`, `EarnSDK` and
`WalletSDK` hold exactly the accounts they are given; an unconfigured venue raises
`ValueError` instead of falling back to a public account. See
[ADR 0036](../../dev-docs/adr/0036-no-implicit-accounts.md).

This is a breaking change:

1. `MarketSDK()`, `EarnSDK()` and `WalletSDK()` are empty. Name credential-free
   venues explicitly with the new `public()` constructor, e.g.
   `MarketSDK.public('hyperliquid', 'mexc')`, or list them in `sdk.toml`.
2. `DEFAULT_ACCOUNTS` and `all_accounts` are removed; use `accounts`.
3. `venues()` and `all` now list configured venues only, so `all` no longer
   requires every adapter package to be installed.
4. `accounts.public_accounts(*venues)` builds the same `public = true` mainnet
   accounts for manual composition.

Adapters do not use the removed members; their SDK floors are unchanged.
`sdk-dev test consistency` now requires `--accounts`.

Qualification on 2026-10-06: all 14 declared venues have passing, verified
read-suite evidence, and all 13 market venues have passing consistency evidence,
against the unchanged Catalogue pin `1851660ac2bed8243dd9ce9c7297fe05c7130973`.
Every run passed on its first attempt. The existing Bit2Me native-ticker
limitation (ADR 0014) remains visible. Qualification accounts were already
explicit in `sdk.test.toml`, so recorded coverage is unchanged.

All 1,308 repository unit tests pass, `sdk-dev docs check` passes, and the changed
files pass Ruff and Pyright.
