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

# Client Order IDs

Every fill names the order it executed as `Trade.order_id`, the `response.id` that
`place_order` returned. That is enough to follow an order once you hold its response. A
strategy reacting to its own fills, such as a hedger, can see a fill on
[`trades_stream()`](streaming.md) before `place_order` has returned, though. Tagging the order
with an ID of your own lets you recognise its fills either way.

Put it in the order as `client_order_id`. The market's `random_client_order_id()` generates
one in the form it accepts:

```python
market = await sdk.market('mexc_account1:spot:BTCUSDT')
client_order_id = market.random_client_order_id()

async with market.trades_stream() as my_trades:
  await market.place_order({
    'type': 'LIMIT', 'qty': qty, 'price': price, 'client_order_id': client_order_id,
  })
  async for trade in my_trades:
    if trade.client_order_id == client_order_id:
      print(trade.order_id, trade.qty, '@', trade.price)
```

## Format and support

The SDK sends the string unchanged, so an ID of your own must follow the venue's rules:
most limit its length and characters and reject an ID already in use.
`random_client_order_id()` follows them by construction: 128 random bits as 32 hex digits on
most venues, with `0x` in front on Hyperliquid, and a UUID on Coinbase. On markets without
client order IDs it returns `None`, which `place_order` treats like no ID at all, so the code
above runs unchanged everywhere. Either field is `None` on fills that don't report it:

| Venue | Sent as | `order_id` on fills | `client_order_id` on fills |
| --- | --- | --- | --- |
| Aster | `newClientOrderId`; perpetuals take up to 36 of `A-Z a-z 0-9 . : / _ -` | Stream | Stream |
| Binance | No trading | History and stream | Stream |
| Bit2Me | `clientOrderId` | History and stream | History and stream |
| Bitget | No trading | History and stream | UTA history and stream; Classic futures stream |
| Bybit | `orderLinkId`, up to 36 characters | History and stream | History and stream |
| Coinbase | `client_order_id` | History and stream | Stream |
| dYdX | Ignored | Stream | — |
| Hyperliquid | `cloid`: `0x` and 32 hex digits | History and stream | History and stream |
| Kraken | No trading | History and stream | Stream |
| Lighter | Ignored | History and stream | — |
| MEXC | `newClientOrderId` (spot) | History and stream | History and stream |

Where you give none, Aster, Binance and Bybit spot generate an ID, and so does the SDK on
Coinbase, which requires one: fills report that one. On Coinbase, reusing an ID doesn't
place a second order; you get back the order already placed under it. Deribit and KuCoin
serve public data only.

<!-- next -->

---

← [Streaming](streaming.md) · **Next:** [Types](types.md) →

<!-- /next -->
