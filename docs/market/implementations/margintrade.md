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

# Margin Trade Market

> Perpetuals, read only. `tribulnation-margintrade`, venue names `margintrade` and
> `margintrade_testnet`.

See the [generic market interface](../index.md) for the shared method surface. This page
covers only what is Margin Trade-specific.

## Account

Margin Trade accounts are Solana wallets, and every account read is public by address:

```toml
[accounts.margintrade]
venue = "margintrade"          # or "margintrade_testnet"
address = "$MARGINTRADE_ADDRESS"
```

With `address` omitted, `margintrade` reads `MARGINTRADE_ADDRESS` (`margintrade_testnet`:
`MARGINTRADE_TESTNET_ADDRESS`). A `private_key` (default `MARGINTRADE_PRIVATE_KEY`, never
required) only names the account when no address is set; trading is not implemented.
`validate` toggles response validation; `rest_url` and `ws_url` override the network's
endpoints.

## Exchange & ID conventions

- One exchange, `perp`. Market ids are the venue's coin names: `margintrade:perp:BTC`,
  `margintrade:perp:NVDA`, `margintrade:perp:PRL`. The PRL/USDC spot pair is not mapped.
- Every market settles in USDC: `Rules.fee_asset` and `Trade.fee.asset` are `USDC`.

## Semantics

- `rules`: the price step is `10 ** -(6 - szDecimals)` and prices are also limited to 5
  significant figures. The oracle price band is `1 / (2 * maxLeverage)`, capped at 20%.
  Fees are the market's own `takerFee`/`makerFee`; the venue has no fee tiers.
- `trades_history` reads the venue's newest 10,000 fills since `start`, filtered to the
  range locally. When the response is full and its oldest fill is after `start`, older
  fills in the range were cut off and the method raises `ApiError`. The venue's `endTime`
  is not used: it is ignored for archived fills.
- `query_order` uses `orderStatus`, which the venue does not scope to the account.
- Collateral: the exchange bucket is cross margin; an isolated position reports its own
  bucket, whose maintenance margin is the documented `notional / (2 * maxLeverage)`.
- Funding settles hourly; `next_funding` is the current rate, settled at the top of the
  next hour. Funding payments are positive when received.
- Not supported: `tickers`, `fees`, `trades_stream`, `funding_rates` and trading.
- Public reads, including account reads of public accounts, are verified on mainnet.

<!-- next -->

---

← [Lighter Market](lighter.md) · **Next:** [Earn](../../earn/index.md) →

<!-- /next -->
