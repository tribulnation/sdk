<!-- github-only -->
<table><tr>
<td align="center"><a href="../index.md">Docs</a></td>
<td align="center"><b>Market</b></td>
<td align="center"><a href="../earn/index.md">Earn</a></td>
<td align="center"><a href="../wallet/index.md">Wallet</a></td>
<td align="center"><a href="../report/index.md">Report</a></td>
<td align="center"><a href="../reference/index.md">Reference</a></td>
<td align="center"><a href="https://tribulnation.com/sdk/docs/support">Support matrix</a></td>
</tr></table>
<!-- /github-only -->

# Market

> [!NOTE]
> <!-- tldr -->
> The `Market` interface helps you place orders, query balances, and read public and private data from a venue.

## Getting started — Public data

You can start with public data right away, no credentials required:

```python
from tribulnation.sdk import MarketSDK

sdk = MarketSDK()
book = await sdk.depth('hyperliquid::BTC')
# Book(bids=[...], asks=[...])
```

What is this `hyperliquid::BTC` string? It's a market identifier: let's see how that works next.

<!-- next -->

---

← [Tribulnation SDK](../index.md) · **Next:** [Market Identifiers](identifiers.md) →

<!-- /next -->
