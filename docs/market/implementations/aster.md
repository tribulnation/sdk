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

The built-in `aster` account is public: market data works without credentials. Account
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
- `Rules.fee_asset` is the quote asset on spot and the margin asset on perpetuals.
  Actual fills can pay fees in another asset (e.g. `ASTER`); `Trade.fee` keeps the
  native one. Standard fee rates are unknown; `fees()` reads the account's rates.

## Venue-specific semantics

- Tickers report an empty book side (native price `0`) as `None`, with no quantity.
- REST depth reads up to 1000 levels. Depth streams carry up to 20 levels, shared per
  symbol and trimmed per subscriber.
- Candles support all six SDK intervals in half-open 500-candle windows.
- Orders: `MARKET` ignores the SDK `price`; `LIMIT` is GTC and `POST_ONLY` is GTX.
  `cancel_orders` sends native batches of ten and returns every per-order result,
  including per-order errors. Venue-specific order settings are rejected.
- Fill streams share one account listen key per exchange, renewed every 25 minutes
  and closed when the last subscriber leaves. Do not run another consumer of the same
  account's listen key concurrently.
- Perpetual position and collateral support one-way (not hedge-mode) positions on the
  cross-margin bucket. Isolated-margin collateral raises `NotImplementedError`.
- `perp_stats` joins the bulk premium index with the funding configuration in two
  requests. Aster has no bulk open-interest source, so `open_interest` is `None`; a
  symbol without a published funding interval reports `funding_interval=None`.
- Unsupported, raising `NotImplementedError`: spot position and collateral, trade
  history, funding payments, `available_notional` and `perp_collateral`.
- Public reads are verified on mainnet. Account and trading methods are verified on
  testnet only.

<!-- next -->

---

← [Coinbase Market](coinbase.md) · **Next:** [Deribit Market](deribit.md) →

<!-- /next -->
