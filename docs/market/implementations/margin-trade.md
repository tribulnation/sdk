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

# margin.trade Market

> Perpetuals and spot. `tribulnation-margin-trade`, venue names `margin-trade` and `margin-trade-testnet`.

See the [generic market interface](../index.md) for the shared method surface. This page
covers only what is margin.trade-specific.

## Account

```toml
[accounts.margin-trade]         # trading: the master's key or an approved agent's
venue = "margin-trade"          # or "margin-trade-testnet"
address = "$MARGIN_TRADE_ADDRESS"
private_key = "$MARGIN_TRADE_PRIVATE_KEY"

[accounts.margin-trade-public]  # account reads by address, no key
venue = "margin-trade"
address = "$MARGIN_TRADE_ADDRESS"
public = true
```

`address` is the master account (base58). With an agent key it must be set; with the
master's key it is derived when omitted. With the fields omitted, `margin-trade` reads
`MARGIN_TRADE_ADDRESS` and `MARGIN_TRADE_PRIVATE_KEY`, and `margin-trade-testnet` the
same names prefixed `MARGIN_TRADE_TESTNET_`.

## IDs

- Exchanges `perp` and `spot`. Perpetual market ids are coin names (`BTC`, `XAU`,
  `NVDA`); spot ids are pair names (`PEARL/USDC`).
- Asset ids are token symbols (`USDC`, `PEARL`); perpetual fills and rules name their fee
  asset `USD`.

## Semantics

- `rules().fees` are each market's own `takerFee`/`makerFee`, the rates fills are
  charged. `fees()` raises `NotImplementedError`: the venue's account rate (`userFees`)
  is not what fills pay.
- `MARKET` is an `Ioc` limit at the order's `price`; the venue refuses one priced too far
  through the book (`slippage exceeded`, raised as `OrderRejected`).
- `query_order` trails placement and cancellation by about a second; `open_orders` is
  current.
- Tickers carry no best-level sizes; markets missing from the venue's CoinGecko feed
  (`SPY`, `QQQ`) keep volumes only.
- Funding settles hourly on the hour; there is no funding-rate history.
- `perp_collateral` is the perp wallet's cross bucket; a market with an isolated
  position raises `NotImplementedError`.
- Streams rely on typed-margin-trade 0.1.1's 10 s ping: the venue drops a connection
  about 30 s after the client's last ping.

No `settings` are read.

<!-- next -->

---

← [Lighter Market](lighter.md) · **Next:** [Earn](../../earn/index.md) →

<!-- /next -->
