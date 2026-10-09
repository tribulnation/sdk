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

# dYdX Market

`tickers()` returns native `quote_volume_24h`; `base_volume_24h` remains `None` because the indexer reports quote turnover.

> Perpetuals only. `tribulnation-dydx`, venue name `dydx`.

See the [generic market interface](../index.md) for the shared method surface. This page
covers only what is dYdX-specific.

## Account

`venue` selects the network: `dydx` is mainnet, `dydx_testnet` is testnet. The built-in `dydx` account is `accounts.Dydx(public=True)`, read-only.

**Either `address` or `mnemonic` must resolve to a value.** The address is required for all
indexer reads (subaccount, positions, orders, collateral). The mnemonic is only needed for
signing (placing/canceling orders). When both are provided, `address` is used directly;
when only `mnemonic` is given, the address is derived from it at construction time.
`parent_subaccount` picks the parent subaccount (see below).

`full_node_grpc` and `full_node_rpc` (both optional, `None` by default, `$ENV_VAR` allowed)
point at a full node you run: its plaintext gRPC streaming endpoint (`host:port`, e.g.
`'20.222.23.181:9090'`) and its CometBFT RPC URL (e.g. `'http://20.222.23.181:26657'`).
They are only read by the [node fill sources](#fill-sources), which need both.

## Exchange & ID conventions

- The only exchange is `perp` (`exchange_id == 'perp'`); any other exchange ID raises.
- Market IDs are dYdX tickers: `<BASE>-USD`, e.g. `BTC-USD`, `ETH-USD`.
- Full SDK ID: `dydx:perp:BTC-USD` (or `<your-account-key>:perp:BTC-USD`).

### Subaccounts — the exchange qualifier

A dYdX subaccount is a margin/liquidation bucket, so it lives on the **exchange**, not on the
market ID. The exchange qualifier selects it:

| `exchange_id` | Selects |
| --- | --- |
| `perp` | the account's **parent** subaccount (`parent_subaccount`, the default cross pool). |
| `perp.<N>` | subaccount `<N>`, validated `N % 128 == parent_subaccount`. |

So `dydx:perp:BTC-USD` addresses the parent/cross pool and `dydx:perp.256:XAUT-USD` addresses
child subaccount `256` (isolated). Child subaccounts of parent `p` are `p, 128+p, 256+p, …`;
any `N` failing `N % 128 == p` raises. Markets **inherit** the subaccount from their exchange,
so trading and position methods (`place_order`, `open_orders`, `query_order`, `perp_position`,
`available_notional`, `perp_collateral`) keys off the same bucket by construction.

> **Migration:** the old `<BASE>-USD:<N>` market-ID suffix (`parse_market_id`) has been
> **retired** in both `exchange.py` and `venue.py`. It was only half-wired — `place_order`/
> `cancel_order`/`available_notional` honored it while `open_orders`/`query_order`/
> `perp_position` ignored it and read the parent subaccount — and grep confirmed no callers
> used it. Move any `dydx:perp:BTC-USD:<N>` usage to `dydx:perp.<N>:BTC-USD`. The `.`-qualifier
> lives inside the exchange segment, so it does not disturb the top-level
> `<account>:<exchange>:<market>` colon split.

### Historical trades and funding

`trades_history` and `funding_payments` include **all subaccounts of the configured
address**, including isolated child accounts. This applies to both selected-market
and exchange-wide history, regardless of which `perp` or `perp.<N>` object is used.
Exchange-wide records carry `market_id`, the native instrument ticker (for example,
`BTC-USD`). Positions and collateral continue to use the selected margin bucket.

## Settings

`place_order` / `cancel_order` and `trades_stream` accept `settings={'dydx': {...}}`, typed
by the dYdX `Settings` TypedDict (`market/impl/mixin.py`). All keys are optional:

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `order_flags` | `'SHORT_TERM' \| 'LONG_TERM' \| 'CONDITIONAL'` | `'LONG_TERM'` | Order flags applied to all orders. |
| `limit_tif` | `TimeInForce` | `'GOOD_TIL_TIME'` | Time-in-force for `LIMIT` orders. |
| `market_tif` | `TimeInForce` | `'IMMEDIATE_OR_CANCEL'` | Time-in-force for `MARKET` orders. |
| `short_term_gtb` | `int` | — | GTB delta for short-term orders: good-til-block = `current_block + short_term_gtb`. Only applied when `order_flags == 'SHORT_TERM'`. |
| `long_term_gtbt` | `int` | — | GTBT delta (seconds) for long-term orders: good-til-block-time = `current_block_time + long_term_gtbt`. Only applied for `LONG_TERM`/`CONDITIONAL` flags. |
| `reduce_only` | `bool` | `False` | Place as reduce-only. |
| `trades_source` | `'indexer' \| 'node' \| 'fastest'` | `'indexer'` | Where `trades_stream` reads fills from; see [Fill sources](#fill-sources). |

Type mapping: `POST_ONLY` orders always use TIF `POST_ONLY`; `MARKET` uses `market_tif`;
`LIMIT` uses `limit_tif`.

## Fill sources

`trades_stream` covers the parent subaccount and all its children. `trades_source` picks
where it reads your fills from:

| `trades_source` | Source | Notes |
| --- | --- | --- |
| `'indexer'` (default) | The indexer's `v4_subaccounts` WebSocket channel | Unchanged behaviour: indexer fill ids, block `time`. |
| `'node'` | Your full node only | About 0.4 s ahead of the indexer. No fallback. |
| `'fastest'` | Both, raced | Each fill once, from whichever source delivers it first. |

`'node'` and `'fastest'` need both `full_node_grpc` and `full_node_rpc` on the account;
without them, entering the stream raises `ValueError`. The node must run with
`--grpc-streaming-enabled`, and with the fix for
[v4-chain#3414](https://github.com/dydxprotocol/v4-chain/issues/3414): the SDK sets
`filter_orders_by_subaccount_id`, which crashes an unpatched v9.7.1 node on a liquidation.

How node fills are read:

- One `StreamOrderbookUpdates` subscription per client, shared by every market: all CLOB
  pairs listed when it connects, the parent subaccount and its children. Connecting costs
  one snapshot of every book (a few MB); after that only your own updates flow. A market
  listed after it connected is covered from the next reconnection.
- Finalized updates only (`exec_mode == 7`). Optimistic updates (below 7) and post-commit
  replays (102) can be reverted or name a different maker, and are ignored.
- Fills of your orders (as maker or taker, including as maker against a liquidation) and
  fills liquidating your subaccount come from the stream, priced at the maker order.
  Deleveraging fills carry no price or side in the stream; they come from the block's
  CometBFT `match` event (`block_results` on `full_node_rpc`), read as soon as the fill
  arrives.
- `time` is the local receive time: the stream carries block heights, not block times,
  and waiting for the block time would delay the fill. It runs about 0.7–1.0 s after the
  block time the indexer reports.
- `id` is synthetic, `<height>:<subject>:<n>`: the subject is the SDK order id for your
  orders, `<subaccount>:<kind>:<perpetual id>` for liquidated, deleveraged and offsetting
  fills, and `n` counts that subject's fills in the block. It differs from the indexer's id.
- `order_id` is the SDK (protocol) order id, `None` when you were liquidated or
  deleveraged; `fee` is `None`; `details` is
  `{'source': 'node', 'height', 'exec_mode', 'kind', 'subaccount'}`.
- The node feed reconnects with backoff and never fails the stream. With `'node'`, fills
  finalized while the node is unreachable are missed: reconcile with `trades_history`.

With `'fastest'`, a fill is identified on both sources by its block height, order (the
indexer's order id is derived from the protocol order id) and size; orderless fills by
height, subaccount, market, side and size. Identical fills in one block are counted, not
merged. The first copy wins and the other is dropped; indexer trades carry
`details={'source': 'indexer', 'fill': <indexer fill>}`. Keys are kept for 1000 blocks;
the indexer keeps delivering while the node is down, and an indexer failure ends the stream
as it does with `'indexer'`.

```python
async with sdk.trades_stream(
  'dydx-account1:perp:BTC-USD', settings={'dydx': {'trades_source': 'fastest'}}
) as my_trades:
  async for trade in my_trades:
    print(trade.details['source'], trade.qty, trade.price)
```

## Candles

`candles` serves every `CandleInterval` (`CANDLE_INTERVALS` is the full set) from the
indexer in its native newest-first pages without buffering the whole history. Both
timezone-aware bounds are required: `start <= candle.time < end`. The SDK does not
guarantee ordering. `volume` is `baseTokenVolume`, `quote_volume` is
`usdVolume`, and `trades` is reported.

## Venue-specific semantics

- **`leverage`** = `1 / effective_IMF`: the market's initial-margin fraction, adjusted
  upward by open-interest caps per the dYdX margining docs. dYdX has no per-account
  leverage setting, so it is the same for every subaccount, cross (parent, `< 128`) or
  isolated (child): an isolated market only changes which subaccount's collateral backs
  the position. The open interest and oracle price come from the cached market list
  shared with `rules()`; `refetch=True` reloads it.
- **`available_notional`** is the SDK default: the addressed subaccount's
  `freeCollateral` (its `perp_collateral().free_collateral`) × `leverage()`.
- **`perp_collateral`** returns the addressed subaccount's bucket. `equity` and
  `free_collateral` come straight from the indexer `get_subaccount` fields;
  `initial_margin` = `equity - free_collateral` (what dYdX's UI shows as "margin usage");
  `maintenance_margin` = Σ`|notional|·effective_mmf` and `leverage` = Σ`|notional|/equity`
  over the subaccount's open positions, priced at each market's `oraclePrice`. `margin_mode`
  is `'cross'` when the subaccount is `< 128` (parent) else `'isolated'` (child). dYdX
  exposes no per-market mode, so `Market.perp_collateral()` just delegates to its exchange.
  Maintenance margin is derived via `effective_mmf` — the base `maintenanceMarginFraction`
  scaled by the same open-interest factor as `effective_IMF`
  (`effective_imf · base_mmf / base_imf`), so it isn't understated at high OI.
- **`index`** returns the market's `oraclePrice`; it raises `ApiError` if unavailable.
- **`perp_position`** aggregates all open positions for the parent subaccount in that
  market into a single net size and average entry price.
- **`query_order`** is overridden to query the indexer directly, so it can return
  filled/canceled states — not just open ones.
- **`cancel_orders`** splits by flag: short-term orders (`order_flags == 0`) go through a
  batch cancel, long-term orders are cancelled one by one.
- Order IDs returned by the SDK are base64-encoded dYdX protocol `OrderId`s.
- **`place_order`** never raises `OrderRejected` yet: a failed broadcast arrives without
  its CheckTx code, so a refusal cannot be told from a transaction already pending in the
  mempool. Treat every placement error as ambiguous and check `open_orders`/fills.
- **`OrderResponse.filled_qty`** is `None`: the broadcast answers before the order is
  matched in a block, so it carries no execution.

## Example: short-term IOC order

The `settings` payload maps directly onto dYdX order flags and expiry:

```python
import os
from tribulnation.sdk import MarketSDK, accounts
from dotenv import load_dotenv

load_dotenv()

market = MarketSDK(
  {
    'dydx-account1': accounts.Dydx(),
  }
)

await market.place_order(
  'dydx-account1:perp:BTC-USD',
  {'price': 10, 'qty': 0.00001, 'type': 'LIMIT'},
  settings={
    'dydx': {
      'limit_tif': 'IMMEDIATE_OR_CANCEL',
      'order_flags': 'SHORT_TERM',
      'short_term_gtb': 2,
    }
  },
)
```

<!-- next -->

---

← [Implementations](index.md) · **Next:** [Hyperliquid Market](hyperliquid.md) →

<!-- /next -->
