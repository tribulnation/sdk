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

# Collateral & Risk Management

`collateral()` answers a different question from `available_notional()`: not "how much can I
open?" but "how close am I to liquidation?". It is built on the **margin-bucket** model.

A **bucket** is a set of markets sharing one collateral pool and one liquidation event.
**An `Exchange` *is* one bucket**. Venues that don't support collateral raise
`NotImplementedError` at call time.

## Routing: exchange-level vs market-level

`collateral()` and `perp_collateral()` accept an optional `market_id` at every level. When
omitted they return the exchange's own bucket; when provided they delegate to the market's
mode-aware collateral:

| Called on | No arg / fewer segments | With market / more segments |
| --- | --- | --- |
| `Exchange.collateral()` | exchange bucket | `exchange.collateral('BTC-USD')` → market-level |
| `TradingVenue.collateral('perp')` | exchange bucket | `venue.collateral('perp:BTC-USD')` → market-level |
| `TradingMarkets.collateral('dydx:perp')` | exchange bucket | `sdk.collateral('dydx:perp:BTC-USD')` → market-level |

Same applies to `perp_collateral()` on `PerpExchange`/`TradingVenue`/`TradingMarkets`.

`Market.collateral()` is **mode-aware**: it returns the pool that actually backs *this*
market. For a cross-margin market that is the exchange bucket; for an isolated market it is
the market's own bucket. This is the accessor a liquidation watcher wants per watched market,
and it is the only model that expresses (e.g.) dYdX holding the same instrument both cross
(parent subaccount) and isolated (a child subaccount) at once.

Risk **never aggregates** across buckets: child/isolated buckets liquidate independently, so
a combined `maintenance_ratio` would be a lie. Additive history reads (trades, funding) may
default to an aggregate scope, but `collateral()` always scopes to exactly one bucket.

## Types

The returned types (`tribulnation.sdk.market`):

- **`Collateral`** — spot / base: `equity` (total account value in quote units) and
  `free_collateral` (not backing positions/orders — withdrawable opening capacity, **not**
  risk). No `None` fields ever: a field exists only if every supported venue can produce it
  truthfully.
- **`PerpCollateral`** (extends `Collateral`) — adds:
  - `initial_margin` — quote units; can't open new positions when `equity <= initial_margin`.
    Equals `equity - free_collateral`.
  - `maintenance_margin` — quote units; liquidation when `equity <= maintenance_margin`.
  - `leverage` — total position notional / equity, `0` when flat.
  - `margin_mode` — `'cross'` | `'isolated'`, always known.
  - `initial_ratio` property — `initial_margin / equity`. At `>= 1` you can't open more.
    This is what dYdX's UI shows as "margin usage".
  - `maintenance_ratio` property — `maintenance_margin / equity`. Liquidation at `>= 1`.
    `+Infinity` when `equity <= 0`.

  Per-position `liquidation_price` is deliberately excluded (dYdX can't give it cleanly).

Note: `initial_ratio` reaching 1.0 does **not** mean liquidation — it means you can't open
new positions. Between `initial_ratio = 1` and `maintenance_ratio = 1` there is a buffer
(typically ~2x, since MMF ≈ IMF/2). `maintenance_ratio` is the actual liquidation signal.

<!-- next -->

---

← [Methods](methods.md) · **Next:** [Streaming](streaming.md) →

<!-- /next -->
