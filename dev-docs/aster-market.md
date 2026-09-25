# Aster Market qualification

Aster 0.1.0 adds spot and linear perpetual Market support on `typed-aster` 0.1.0.
Public reads are release-qualified on mainnet. Account and trading methods, and the
unrouted `Report`, are verified on testnet only; release evidence cannot attest them
because the release gate accepts mainnet observations only.

## Capability handoff

| Surface | Scope | Native mapping |
| --- | --- | --- |
| Discovery | Symbols with status `TRADING`; perpetual contracts only | `exchange_info`, cached per owner; `rules(refetch=True)` and `tickers` refresh it |
| Tickers | All or selected symbols | `ticker_24hr` joined with `book_ticker` |
| Rules | Price, lot, notional and percent-price filters | Spot fee asset is the quote; perpetual fee asset is the margin asset |
| Depth | 1–1000 levels | Smallest native `limit` covering the request |
| Depth stream | 1–20 levels | One shared 20-level `partial_depth` stream per symbol |
| Candles | Six SDK intervals | `klines`, half-open 500-candle windows retried individually |
| Funding | Index, next funding, settled rates | `premium_index`, per-symbol `funding_info`, `funding_rate_paged` |
| Orders | MARKET, LIMIT (GTC), POST_ONLY (GTX); query, open, cancel | Batch cancellation in native chunks of ten |
| Fills | Shared account stream per exchange | Listen key renewed every 25 minutes, closed with the last subscriber |
| Perpetual account | One-way position; cross-margin collateral | `position.risk`, `account.info_with_join_margin` |

## Credentials

Only the trading agent key is loaded. `typed_aster.Aster.new` would also read the
main wallet's key (`ASTER_USER_PRIVATE_KEY`) from the environment, which can withdraw,
so the package builds `Credentials` from explicit arguments instead. The SDK account
resolves `ASTER_*` for `aster` and `TEST_ASTER_*` for `aster_testnet`, never mixing them.

## Unsupported methods and why

1. Trade history: `user_trades_paged` adds `fromId` while keeping the time filters,
   which the venue rejects (`-1106`). See `typed-client-issues.md`.
2. Bulk `perp_stats`: the unfiltered `funding_info` response has null fields that fail
   validation. See `typed-client-issues.md`.
3. Spot position and collateral: on testnet, `spot.account.info()` returned
   `balances=[]` after a confirmed 250 USDT transfer and filled orders, while the
   WebSocket reported nonzero balances. Zero would hide known holdings.
4. Funding payments: only empty responses have been observed.
5. `available_notional` and `perp_collateral`: the API publishes neither account-side
   buying capacity nor actual (rather than configured) leverage.
6. Report snapshots, for the same reason as spot balances. Report history maps the
   perpetual income and spot transaction ledgers to `UnknownObservation`; one spot
   transaction ID spans several asset/type legs, so record IDs include both.

## Testnet observations (2026-09-25)

1. Spot `user_trades` omitted confirmed buy fills (e.g. trade `30454527`) that the
   execution stream and commission ledger reported; sells were returned. Fixing
   pagination alone will not restore the missing buys.
2. Spot order queries could briefly return not-found or stale state right after
   placement or a streamed fill; one filled order appeared after three 200 ms polls.
   The SDK returns each native result as is.
3. Fees were paid in the native asset of the fill: perpetuals in ASTER, spot buys in
   ASTER and spot sells in USDT.
4. `futures.wallet.withdraw_info()` returned `-1000` or gateway timeouts.

## PoC and live checks

The PoCs under `packages/impl/aster/poc/` record the original mapping. Credentials for
lifecycle cells come from `poc/.env` (`ASTER_USER`, `ASTER_SIGNER_PRIVATE_KEY` for a
testnet agent). Mutating cells check for the testnet transport and create real test
activity; do not run two lifecycle sessions against the same account.
