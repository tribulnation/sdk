# tribulnation-hyperliquid 0.14.0

Requires SDK >=2.13.0 and typed-hyperliquid >=2.5.0, which keeps the per-asset
HIP-3 fee fields. HIP-3 and spot markets now report fees.

New:

1. `fees()` and `rules().fees` for HIP-3 perpetuals with USDC collateral, and for
   spot pairs quoted in USDC or USDE, via Hyperliquid's official fee formula: the
   asset's deployer fee scale and growth mode for HIP-3, the stable-pair discount
   for spot pairs between two spot quote tokens, and the account's referral
   discount on charges. `rules().fees` uses the standard schedule without referral.
2. Perpetuals and spot pairs with other collateral or quote tokens (USDH, USDT0,
   ...) raise `NotImplementedError` from `fees()` and return `rules().fees=None`:
   whether their token is an aligned quote token is not readable from the API. USDC
   (AQAv2) carries no fee adjustment. See ADR 0039.

Behaviour changes:

1. Perpetual `rules().fee_asset` is the collateral token's index (`'0'` for USDC),
   the same identifier as `Trade.fee.asset` and balances, instead of its name.
2. Spot `rules().fee_asset` is `None` (ADR 0028): fees are paid in the token
   received, and maker rebates credited in the token given. `Trade.fee.asset`
   names each fill's token.

Verified against 27,018 public mainnet fills across default and HIP-3
perpetuals and USDC, USDT0/USDC and USDE spot pairs.

Release qualification on 2026-10-08 passed the read suites and market
consistency. Committed evidence under `release-evidence/hyperliquid/` matches pinned
Catalogue `1851660ac2bed8243dd9ce9c7297fe05c7130973`; offline release
verification passes. This adapter release follows SDK 2.14.0 publication.
