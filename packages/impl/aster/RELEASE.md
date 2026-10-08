# tribulnation-aster 0.8.0

Requires SDK >=2.13.0 and typed-aster >=0.4.0. Fills most of Aster's account
gaps in the Market surface.

New:

1. Spot `position()`, `collateral()` and `available_notional()`, from the spot
   account: the position is the base asset's free plus locked balance; collateral
   equity is the quote asset's free plus locked balance, and free collateral its
   free balance. Testnet raises `NotImplementedError` (its spot account omits
   funded balances).
2. Spot `trades_history()`, per pair and exchange-wide (`None`), in native
   seven-day windows. Testnet raises `NotImplementedError` (it omits buy fills).
3. Perpetual `perp_collateral()`, and `collateral()` for isolated positions, from
   the futures account (read with joined margin, so Multi-Assets mode counts every
   margin asset). Cross leverage is the cross positions' notional over equity. The
   isolated path is unit-tested but not yet verified against a live isolated
   position.
4. `perp_stats()` reports open interest when five or fewer contracts are
   requested, from the public, undocumented `openInterest` endpoint; larger
   requests keep it `None`.

Behaviour changes:

1. Perpetual `available_notional()` is now capped by the leverage bracket's room
   (its `maxNotional` less the position's notional) and by the venue's remaining
   openable notional (ADR 0041).
2. `rules().fee_asset` is `None` for spot and perpetuals (ADR 0028). Spot fees are
   paid in the asset received; futures fees are paid in ASTER when the account's
   fee-burn setting is on and it holds ASTER, otherwise in the margin asset.
   `Trade.fee.asset` names each fill's asset.

Unchanged: hedge-mode positions, exchange-wide perpetual trade history and order
settings still raise.

Release qualification on 2026-10-08 passed the read suites and market
consistency. Committed evidence under `release-evidence/aster/` matches pinned
Catalogue `1851660ac2bed8243dd9ce9c7297fe05c7130973`; offline release
verification passes. This adapter release follows SDK 2.14.0 publication.
