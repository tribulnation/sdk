# Aster Market qualification

Aster 0.1.0 added spot and linear perpetual Market support on `typed-aster` 0.1.0.
Aster 0.2.0 moves to `typed-aster` 0.2.0, adds bulk `perp_stats` and supports Python
3.10.
Public reads are release-qualified on mainnet. Account reads (fees, spot balances, spot
and perpetual trade history, perpetual position, collateral, leverage and available
notional) were checked read-only on mainnet on 2026-10-08; the market read suite does not
call account methods, so release evidence does not attest them. Order placement and
cancellation are verified on testnet only.

## Capability handoff

| Surface | Scope | Native mapping |
| --- | --- | --- |
| Discovery | Symbols with status `TRADING`; perpetual contracts only | `exchange_info`, cached per owner; `rules(refetch=True)` and `tickers` refresh it |
| Tickers | All or selected symbols | `ticker_24hr` joined with `book_ticker` |
| Rules | Price, lot, notional and percent-price filters | Spot fee asset is `None` (fill-dependent, ADR 0028); perpetual fee asset is the margin asset |
| Depth | 1–1000 levels | Smallest native `limit` covering the request |
| Depth stream | 1–20 levels | One shared 20-level `partial_depth` stream per symbol |
| Candles | Six SDK intervals | `klines`, half-open 500-candle windows retried individually |
| Funding | Index, next funding, settled rates | `premium_index`, per-symbol `funding_info`, `funding_rate_paged` |
| Perpetual stats | All or selected contracts; open interest for at most five named contracts | Unfiltered `premium_index` joined with unfiltered `funding_info`, plus one undocumented `openInterest` read per named contract |
| Orders | MARKET, LIMIT (GTC), POST_ONLY (GTX); query, open, cancel | Batch cancellation in native chunks of ten |
| Fills | Shared account stream per exchange | Listen key renewed every 25 minutes, closed with the last subscriber |
| Trade history | One pair or contract, or every spot pair; inclusive bounds, up to the current time | `user_trades_paged` per seven-day window, each `fromId` page retried alone; symbol-less spot windows are halved when a page fills |
| Spot account | Mainnet only; base position, quote collateral | `spot.account.info`, free plus locked |
| Perpetual account | One-way position; cross or isolated collateral | `position.risk`, `account.info_with_join_margin` |
| Available notional | Perpetuals: free cross balance times leverage, capped | `availableBalance`, the position row's `maxNotional`, `remainingOpenableNotionalValue` |

## Credentials

Only the trading agent key is loaded. `typed_aster.Aster.new` would also read the
main wallet's key (`ASTER_USER_PRIVATE_KEY`) from the environment, which can withdraw,
so the package builds `Credentials` from explicit arguments instead. The SDK account
resolves `ASTER_*` for `aster` and `TEST_ASTER_*` for `aster_testnet`, never mixing them.

## Unsupported methods and why

1. Testnet spot trade history: testnet `user_trades` omits confirmed buy fills
   (testnet observation 1 below, still true on 2026-09-29). Mainnet returns both sides
   (mainnet observations below), so spot history is supported on mainnet only.
2. Testnet spot position and collateral: on testnet, `spot.account.info()` returned
   `balances=[]` after a confirmed 250 USDT transfer and filled orders, while the
   WebSocket reported nonzero balances. Zero would hide known holdings. Mainnet
   balances match the Report snapshot's source and are supported.
3. Hedge-mode positions, exchange-wide perpetual trade history (the venue requires a
   symbol) and order settings raise `NotImplementedError`.
4. Report snapshots on testnet, for the same reason as spot balances. Report history
   maps the perpetual income and spot transaction ledgers to `UnknownObservation`; one
   spot transaction ID spans several asset/type legs, so record IDs include both.

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
5. The unfiltered `funding_info` response carried null `fundingIntervalHours`,
   `fundingFeeCap` and `fundingFeeFloor` for 501 of 758 rows, all symbols absent from
   testnet exchange information. Mainnet rows were complete. `typed-aster` 0.2.0
   accepts the nulls; bulk `perp_stats` reports them as `funding_interval=None` and
   `next_funding` raises `MissingData`.

## Testnet observations (2026-09-29)

1. Perpetual `userTrades` refuses a window wider than seven days (`-4165`, "Maximum
   time interval is 7 days."), a future `startTime` (`-4181`) and an `endTime` more
   than about a day ahead (`-4165`, "Invalid time interval."), even within seven days.
   Both bounds are inclusive. Windows back to 2020 answer empty, with no retention
   error.
2. The 16 ASTERUSDT fills walked at `limit=3` (8 pages) matched one native page
   exactly, with no repeated or missing trade ID.
3. Spot `userTrades` still omits buys: over six days of ASTERUSDT, the spot
   transaction ledger names 12 trade IDs and `userTrades` lists 6, all sells.

## Mainnet observations (2026-10-08)

Read-only, with the trading agent of one mainnet account.

1. Spot fills pay their fee in the asset they deliver: a taker buy of USDCUSDT paid
   USDC and a taker sell paid USDT, each exactly the account's taker rate of the
   notional, with no ASTER discount. `rules().fee_asset` is therefore `None`.
2. Spot `userTrades` returned both fills, with or without a symbol, and matched the
   spot transaction ledger's trade IDs exactly (2 of 2 over 182 days). `fromId` is
   accepted without a symbol, but its ordering across symbols is unverified, so the
   exchange-wide walk splits windows instead. Seven-day windows are accepted.
3. With Multi-Assets margin on, `account.info` totals count USDT alone (its
   `totalMarginBalance` equals the USDT asset's), while `account.info_with_join_margin`
   values every margin asset. Collateral uses the join-margin view. Its
   `totalInitialMargin` and `totalMaintMargin` equal the sums over position rows. How
   isolated positions enter the totals is inferred from the Binance-compatible
   layout: the account held no isolated position to confirm it.
4. A position row's `maxNotional` (and `positionRisk`'s `maxNotionalValue`) equals the
   leverage bracket's notional cap at the symbol's configured leverage, for every
   symbol `leverageBrackets` lists.
5. `GET /fapi/v3/openInterest?symbol=` (also `/fapi/v1`) is public and undocumented;
   without a symbol it answers `-1102`. `typed-aster` 0.4.0 adds it.
6. Perpetual commissions were paid in USDT, the margin asset.

## PoC and live checks

The PoCs under `packages/impl/aster/poc/` record the original mapping. Credentials for
lifecycle cells come from `poc/.env` (`ASTER_USER`, `ASTER_SIGNER_PRIVATE_KEY` for a
testnet agent). Mutating cells check for the testnet transport and create real test
activity; do not run two lifecycle sessions against the same account.
