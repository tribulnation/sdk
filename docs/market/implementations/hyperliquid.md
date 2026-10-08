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

# Hyperliquid Market

> Spot **and** perpetuals. `tribulnation-hyperliquid`, venue name `hyperliquid`.

See the [generic market interface](../index.md) for the shared method surface. This page
covers only what is Hyperliquid-specific.

## Account

`venue` selects the network: `hyperliquid` is mainnet, `hyperliquid_testnet` is testnet. An
`address` without a `private_key` is read-only, and so is
`accounts.Hyperliquid(public=True)`.

## Exchanges & ID conventions

Hyperliquid exposes several exchanges under one venue. `exchanges()` reports:

| `exchange_id` | Type | What it is |
| --- | --- | --- |
| `spot` | spot | The spot exchange. |
| `''` (empty) | perp | The default perpetuals DEX. |
| `<dex-name>` | perp | A named builder-deployed perp DEX. |

For perps, **`exchange_id` is the DEX name**; the empty string means the default/no-DEX
universe. Under the hood `perp_exchange(dex)` treats `''` and `None` equivalently.

Market IDs by exchange:

- **Perp** — the asset name, e.g. `BTC`. Full ID: `hyperliquid::BTC` (empty exchange
  segment = default DEX) or `hyperliquid:<dex>:BTC`.
- **Spot** — canonical form `BASE/QUOTE:ASSET_IDX`, e.g. `BTC/USDC:0`. Full ID:
  `hyperliquid:spot:BTC/USDC:0`. The `ASSET_IDX` is Hyperliquid's `spotMeta.universe[].index`;
  `market()` cross-checks that the `BASE/QUOTE` names match that index and raises on
  mismatch. `Exchange.markets()` returns fully-formed `BASE/QUOTE:IDX` strings you can pass
  straight back in.

## Settings

`place_order`, `index`, `depth` and `depth_stream` accept `settings={'hyperliquid': {...}}`,
typed by the `Settings` TypedDict (`core/settings.py`). All keys are optional:

| Key | Type | Applies to | Meaning |
| --- | --- | --- | --- |
| `reduce_only` | `bool` | `place_order` | Place as reduce-only. |
| `limit_tif` | `TimeInForce` | `place_order` | Time-in-force for limit orders. |
| `index_price` | `'oracle' \| 'mark'` | `index` (perp) | Which price `index()` returns; defaults to `'oracle'`. |
| `depth_source` | `'l2' \| 'fast' \| 'bbo'` | `depth_stream`, `depth` | Which order-book feed to read; defaults to `'l2'`. |

`index_price='mark'` returns the market's mark price, falling back to the oracle price when
mark is unavailable; the default `'oracle'` always returns the oracle price.

### Depth sources

`depth_source` picks one of three Hyperliquid WebSocket feeds for `depth_stream`, on spot,
default-DEX and builder-DEX perp markets alike:

| `depth_source` | Feed | Levels per side | Typical cadence |
| --- | --- | --- | --- |
| `'l2'` (default) | `l2Book` | 20 | ~5.4 s |
| `'fast'` | `l2Book` with `fast=True` | 5 | ~0.5 s |
| `'bbo'` | `bbo` | 1 (best bid/ask with sizes) | on change: ~100–150 ms on liquid markets |

```python
async with sdk.depth_stream('hl::ETH', settings={'hyperliquid': {'depth_source': 'bbo'}}) as books:
  async for book in books:
    print(book.time, book.best_bid.price, book.best_ask.price)
```

- These are different feeds, not one feed at different speeds, and they won't agree
  tick-for-tick: `'bbo'` usually leads the best level of `'l2'` by up to seconds. Every
  book carries the feed's own exchange time in `Book.time`.
- `levels` only trims what the feed delivers (`levels=3` on `'fast'` gives 3 levels; on
  `'bbo'` it still gives 1). It never selects the feed.
- On `'bbo'` a side Hyperliquid reports as empty comes back as an empty `bids` or `asks`.
- All consumers of one coin and source share a single upstream subscription. Hyperliquid
  tags `'l2'` and `'fast'` pushes identically, so `'fast'` subscriptions are held on a
  second WebSocket connection, opened on first use and closed with the SDK.
- REST `depth` has no faster endpoint. Every source reads the same `l2Book` snapshot
  (20 levels), trimmed to 5 levels for `'fast'` and 1 for `'bbo'`, and to `levels` when
  lower. The setting changes the shape, not the freshness.

## Venue-specific semantics

- Spot and perp markets are separate objects (`SpotMarket` / `PerpMarket`) with their own
  rules and position logic. Only `PerpMarket` exposes funding and `index()`.
- `candles` raises `NotImplementedError` on both, and `CANDLE_INTERVALS` is empty:
  `info.candle_snapshot` answers at most 5000 candles per call and the typed client
  declares no paged walk for it yet, so the series cannot be swept through the client.
- Perp `available_notional`/leverage and spot balances are computed against
  Hyperliquid-native metadata (asset/collateral tokens, user fees), cached venue-wide and
  refreshed lazily.
- **`perp_collateral`** at the exchange level returns the account **cross** pool in **unified
  account** mode. The implementation asserts `user_abstraction == "unifiedAccount"` and raises
  on other modes. In unified mode, the real equity backing perps is the **spot collateral token
  balance** (determined by `perp_meta['collateralToken']`, USDC for the default DEX), not
  `crossMarginSummary.accountValue` (which only reflects USDC deposited into the perps engine).
  Fields: `equity=spot_collateral_balance` (its spot `total`), `free_collateral=total-hold`
  for the collateral token (what backs positions and open orders is held, so this matches
  Hyperliquid's "available to trade"; `tokenToAvailableAfterMaintenance` only nets out
  maintenance margin and overstates it), `initial_margin=equity-free_collateral` (the hold),
  `maintenance_margin=crossMaintenanceMarginUsed`, `leverage=totalNtlPos/equity`,
  `margin_mode='cross'`. `Market.perp_collateral()` is **mode-aware**: it finds the asset in
  `assetPositions` and branches on the position's leverage type — a cross position reports the
  same cross pool, while an **isolated** position gets its own bucket from that position's
  `rawUsd + unrealizedPnl` (equity), `marginUsed` (= `initial_margin`), and
  `margin_mode='isolated'`. HL gives no isolated maintenance figure directly, so it is
  approximated as `positionValue / (2 · maxLeverage)` (half the initial-margin fraction at max
  leverage).
- **`collateral`** (spot) returns the quote-token balance (`equity=total`,
  `free_collateral=total-hold`).
- Builder-DEX perps use a DEX-scoped asset-id formula (`100000 + dex_idx*10000 + asset_idx`);
  default-DEX perps use the plain asset index. This only matters internally — you address
  markets by name.

## Example

```python
from dotenv import load_dotenv
from tribulnation.sdk import MarketSDK, accounts

load_dotenv()

sdk = MarketSDK({'hl': accounts.Hyperliquid()})

# default-DEX perp
await sdk.index('hl::BTC')

# spot
book = await sdk.depth('hl:spot:BTC/USDC:0')

await sdk.place_order(
  'hl::ETH',
  {
    'type': 'LIMIT',
    'qty': 0.01,
    'price': 1000,
  },
  settings={'hyperliquid': {'limit_tif': 'Alo', 'reduce_only': False}},
)
```

<!-- next -->

---

← [dYdX Market](dydx.md) · **Next:** [MEXC Market](mexc.md) →

<!-- /next -->
