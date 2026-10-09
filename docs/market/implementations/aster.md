<!-- github-only -->
<table><tr>
<td align="center"><a href="../../index.md">Docs</a></td>
<td align="center"><b>Market</b></td>
<td align="center"><a href="../../earn/index.md">Earn</a></td>
<td align="center"><a href="../../wallet/index.md">Wallet</a></td>
<td align="center"><a href="../../report/index.md">Report</a></td>
<td align="center"><a href="../../reference/index.md">Reference</a></td>
<td align="center"><a href="https://tribulnation.com/sdk/docs/support">Support matrix</a></td>
</tr></table>
<!-- /github-only -->

# Aster Market

> Spot and linear perpetuals. `tribulnation-aster`, venue names `aster` and `aster_testnet`.

See the [generic market interface](../index.md) for the shared method surface. This page
covers only what is Aster-specific.

## Account

A public `accounts.Aster(public=True)` account is enough for market data. Account
and trading methods need the main wallet's address and the private key of a trading
agent (API wallet) registered for it. The main wallet's own key is never used.

```toml
[accounts.aster]
venue = "aster"            # or "aster_testnet"
user = "$ASTER_USER"
signer = "$ASTER_SIGNER_PRIVATE_KEY"
```

With `user`/`signer` omitted, `aster` reads `ASTER_USER` and `ASTER_SIGNER_PRIVATE_KEY`,
and `aster_testnet` reads `TEST_ASTER_USER` and `TEST_ASTER_SIGNER_PRIVATE_KEY`. Testnet
never falls back to mainnet variables. `validate` toggles response validation.

## Exchange & ID conventions

- Exchanges are `spot` and `perp`, with native symbols: `aster:spot:ASTERUSDT`,
  `aster:perp:BTCUSDT`. Discovery lists symbols currently trading; perpetual discovery
  excludes dated contracts.
- `Rules.fee_asset` is `None`: the fee asset depends on the fill. A spot fill pays in
  the asset it delivers, the base asset on a buy and the quote asset on a sell. A
  perpetual fill pays ASTER when the account's futures fee-burn setting is on and its
  futures wallet holds ASTER, and the margin asset otherwise; rules read no account
  setting, so they claim neither. `Trade.fee.asset` keeps each fill's native fee asset. Standard
  fee rates are unknown (`rules().fees` is `None`); `fees()` reads the account's rates
  and needs `user` and `signer`.

## Venue-specific semantics

- Tickers report an empty book side (native price `0`) as `None`, with no quantity.
- REST depth reads up to 1000 levels. Depth streams carry up to 20 levels, shared per
  symbol and trimmed per subscriber.
- `Book.time` is the message's event/output time `E`: REST `depth` and partial-depth
  pushes are full top-N snapshots, each current as of when Aster produced it, which is
  at or after the transaction time `T` of the last change it includes. A message
  without `E` falls back to `T`.
- Candles support all six SDK intervals in half-open 500-candle windows.
- Orders: `MARKET` ignores the SDK `price`; `LIMIT` is GTC and `POST_ONLY` is GTX.
  `settings={'aster': {'time_in_force': 'IOC'}}` sends a `LIMIT` order
  immediate-or-cancel, on spot and perpetuals; set on `MARKET` or `POST_ONLY` it raises
  `ValueError`. Other venues' settings keys are ignored; `aster` settings on a
  cancellation raise `NotImplementedError`. `cancel_orders` sends native batches of ten
  and returns every per-order result, including per-order errors.
- `place_order` raises `OrderRejected` for a `4XX` refusal carrying a business code
  (e.g. `-2019` insufficient margin, `-1111` bad precision), and for a result that ended
  `EXPIRED` or `REJECTED` with nothing filled, such as a `POST_ONLY` that would have
  crossed or an IOC that found nothing to match; a partially filled IOC is a response. Codes `-1000`, `-1001`, `-1006`, `-1007` and `-1008`, a `408`, a code-less
  body and any `5XX` leave the outcome unknown and stay `BadRequest`/`ApiError`;
  throttling stays `RateLimited`.
- Fill streams share one account listen key per exchange, renewed every 25 minutes
  and closed when the last subscriber leaves. Do not run another consumer of the same
  account's listen key concurrently.
- `trades_history` reads inclusive `[start, end]` bounds in native seven-day windows
  and stops at the current time because Aster refuses future bounds. One pair or
  contract is walked by trade ID. Spot also serves every pair at once
  (`trades_history(None, ...)`), splitting any window that fills a page; exchange-wide
  perpetual history raises `NotImplementedError`.
- Spot `position` is the base asset's balance and `collateral` the quote asset's, free
  plus locked; free collateral is the free quote balance. Spot balances and trade
  history are mainnet-only: testnet omits them, so they raise `NotImplementedError`.
- Perpetual position and collateral support one-way (not hedge-mode) positions.
  `perp_collateral` reads the join-margin account, whose totals value every margin
  asset in USDT. The cross bucket is those totals less isolated positions' own margin
  and requirements; its leverage is the cross positions' notional over equity. An
  isolated market reports its position's own margin (isolated wallet plus unrealized
  PnL), with any margin above its initial margin as free collateral. The exchange-level
  `perp_collateral()` is the cross bucket. Both buckets were verified against a live
  isolated position on testnet (2026-10-08): the isolated equity matches
  `positionRisk`'s `isolatedMargin` and the cross equity matches the account's
  `totalCrossWalletBalance` plus `totalCrossUnPnl`. Aster rejects isolated margin in
  Multi-Assets mode, so isolated positions only exist on single-asset accounts.
- `perp_stats` joins the bulk premium index with the funding configuration in two
  requests. Open interest (base units) has no bulk source: it is read per contract only
  when at most five contracts are named, and is `None` otherwise. A symbol without a
  published funding interval reports `funding_interval=None`.
- Perpetual funding payments are available per market or exchange-wide, positive when
  received.
- Perpetual `leverage` is the symbol's configured initial leverage, the `leverage` field
  of its `positionRisk` rows (one per side in hedge mode; the lowest is used should they
  differ). Aster lists flat symbols too, so a missing row raises `MissingData` rather than
  falling back. The setting applies to cross and isolated margin. Cached per symbol;
  `refetch=True` reads it again.
- Perpetual `available_notional` is the account's `availableBalance` times
  `leverage()`, in either margin mode (new margin comes from the available balance),
  capped by the room left in the leverage bracket at that leverage (`maxNotional` less
  the position's own notional) and by the symbol's remaining open-interest allowance
  (`remainingOpenableNotionalValue`). It is the same-direction room; reducing or
  reversing a position is not modelled. Testnet does not serve
  `remainingOpenableNotionalValue` (HTTP 404), so perpetual `available_notional` fails
  there. Spot `available_notional` is the free quote balance.
- Unsupported, raising `NotImplementedError`: hedge-mode positions and exchange-wide
  perpetual trade history.
- Public reads and the account reads are verified on mainnet. Order placement and
  cancellation are verified on testnet only.

<!-- next -->

---

← [Coinbase Market](coinbase.md) · **Next:** [Deribit Market](deribit.md) →

<!-- /next -->
