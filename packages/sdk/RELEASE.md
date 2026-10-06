# tribulnation-sdk 2.11.0

SDK roots no longer contain implicit accounts. `MarketSDK`, `EarnSDK` and
`WalletSDK` hold exactly the accounts they are given; an unconfigured venue raises
`ValueError` instead of falling back to a public account. See
[ADR 0036](../../dev-docs/adr/0036-no-implicit-accounts.md).

This is a breaking change:

1. `MarketSDK()`, `EarnSDK()` and `WalletSDK()` are empty. Configure
   credential-free venues explicitly, e.g.
   `MarketSDK({'hyperliquid': accounts.Hyperliquid(public=True)})`, or with
   `public = true` in `sdk.toml`.
2. `DEFAULT_ACCOUNTS` and `all_accounts` are removed; use `accounts`.
3. `venues()` and `all` now list configured venues only, so `all` no longer
   requires every adapter package to be installed.

Adapters do not use the removed members; their SDK floors are unchanged.
`sdk-dev test consistency` now requires `--accounts`.

QUALIFICATION
