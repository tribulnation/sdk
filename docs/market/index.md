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
