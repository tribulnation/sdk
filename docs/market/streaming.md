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

# Streaming

`depth_stream()` and `trades_stream()` are async context managers that yield an async
iterable. Enter one, iterate it, and leave the block to unsubscribe:

```python
async with sdk.depth_stream('mexc_account1:spot:BTCUSDT') as books:
  async for book in books:
    print(book.best_bid, book.best_ask)
```

```
(Decimal('60123.40'), Decimal('60124.00'))
(Decimal('60123.50'), Decimal('60124.00'))
(Decimal('60122.90'), Decimal('60123.60'))
```

`trades_stream()` works the same way and yields your own fills, which is how you follow an
order from [Your First Order](first-order.md) without polling `query_order`:

```python
async with sdk.trades_stream('mexc_account1:spot:BTCUSDT') as my_trades:
  async for trade in my_trades:
    print(trade.qty, '@', trade.price, 'maker' if trade.maker else 'taker')
```

## Which venues stream

Every venue with a Market implementation streams both, natively over the venue's own
websocket. There's no polling fallback anywhere in the SDK: a venue that didn't stream
would raise instead.

<!-- streams -->
| Venue | `depth_stream` | `trades_stream` |
| --- | --- | --- |
| dYdX | ✅ | ✅ |
| Hyperliquid | ✅ | ✅ |
| MEXC | ✅ | ✅ |
| Binance | ✅ | ✅ |
| Bit2Me | ✅ | ✅ |
| Coinbase | ✅ | ✅ |
| Bybit | ✅ | ✅ |
<!-- /streams -->

Per-venue caveats are on the
[support matrix](https://tribulnation.com/sdk/docs/support). Coinbase's `trades_stream`,
for one, reports order-level cumulative quantities rather than itemized fills, so
`trades_history` is the reliable source there for per-fill maker/taker and fee.

## When your consumer falls behind

A venue opens one shared upstream subscription and fans it out to every subscriber through a
*bounded per-subscriber queue*. Two arguments control yours:

- `queue_size`: how many items to buffer for *this* subscriber.
- `overflow`: what happens when that buffer is full.
  - `'latest'`: keep only the newest item. A slow consumer silently skips stale ones.
  - `'fail'`: fail the subscriber with a `NetworkError`, so you can reconnect instead of
    losing data without noticing.

The defaults follow from what each stream is for:

| Stream | `queue_size` | `overflow` | Rationale |
| --- | --- | --- | --- |
| `depth_stream` | `1` | `'latest'` | You only care about the freshest book. |
| `trades_stream` | `1000` | `'fail'` | Don't drop your own fills silently. |

To capture *every* book, say if you're recording full depth history, ask for both:

```python
async with sdk.depth_stream(market_id, queue_size=10_000, overflow='fail') as books:
  ...
```

<!-- next -->

---

← [Collateral & Risk](collateral.md) · **Next:** [Types](types.md) →

<!-- /next -->
