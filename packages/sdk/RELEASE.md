# tribulnation-sdk 2.14.0

Lighter accounts gain a read-only credential mode and public account reads.

New:

1. `accounts.Lighter.auth_token`: a read-only (`ro:`) auth token, defaulting to
   the network's `AUTH_TOKEN` variable (`LIGHTER_AUTH_TOKEN`,
   `LIGHTER_TESTNET_AUTH_TOKEN`). It is an alternative to the API key for private
   reads (`fees`, orders, fills, funding payments); trading still needs the API
   key. With a token, `account_index` is optional: the token names its account.
2. Public Lighter accounts (`public = true`) read the account's positions,
   collateral, leverage, available notional and trade history from the configured
   `account_index`, or else the master account of the configured `address`.
   Previously every account-scoped read raised `AuthError` in public mode.
3. `MarketSDK` passes the token and address to `LighterMarket`.

If the network's API key variables are also set, the Lighter client uses them even
for an account configured with only a token. See ADR 0040.

This release requires Lighter 0.7.0, which requires SDK >=2.14.0; the SDK extras
now require Aster 0.8.0, Hyperliquid 0.14.0 and Lighter 0.7.0. Upgrade the SDK and
those adapters together. Other adapters are unaffected.

The live market suite now also reads Hyperliquid account `fees()` on its reference
markets, which include a HIP-3 market (`xyz:SILVER`), and these changes are a live
qualification change: every declared venue was requalified (ADR 0033).

Qualification on 2026-10-08: all 14 declared venues have passing, verified
read-suite evidence, and all 13 market venues have passing consistency evidence,
against the unchanged Catalogue pin `1851660ac2bed8243dd9ce9c7297fe05c7130973`.
The existing Bit2Me native-ticker limitation (ADR 0014) and Bitget's venue-wide
withdrawal suspension (ADR 0027) remain visible.

All 1,511 repository unit tests pass.
