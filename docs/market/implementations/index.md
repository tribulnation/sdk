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

# Implementations

What each venue does differently behind the shared `Market` interface: account fields,
exchange and market ID conventions, accepted `settings`, and venue-specific semantics.
Per-method differences are on the [Methods](../methods.md) page, under each method.

- [dYdX](dydx.md) — perpetuals only; subaccounts as the exchange qualifier
- [Hyperliquid](hyperliquid.md) — spot and perpetuals, several exchanges under one venue
- [MEXC](mexc.md) — spot only
- [Bitget](bitget.md) — spot and USDT-, USDC- and coin-margined perpetual data; account reads on spot and USDT only
- [Coinbase](coinbase.md) — spot and INTX perpetuals; authenticated access recommended, explicit public fallback
- [Kraken](kraken.md) — spot only, read only; altname market ids

- [Deribit](deribit.md) — public spot and linear perpetuals; four intraday candle intervals
- [Lighter](lighter.md) — perpetuals and spot; numeric market ids, unified accounts for spot collateral

<!-- next -->

---

← [Methods](../methods.md) · **Next:** [dYdX Market](dydx.md) →

<!-- /next -->
