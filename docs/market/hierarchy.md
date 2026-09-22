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

# Hierarchy & Scoping

The markets implementation is structured following the market IDs: `account` → `venue` → `exchange` → `market`.

| Level | Instantiation | Example |
| --- | --- | --- |
| Top-level | `sdk = MarketSDK()` | `sdk.depth('mexc:spot:BTCUSDT')` |
| Venue | `venue = await sdk.venue('mexc')` | `venue.depth('spot:BTCUSDT')` |
| Exchange | `exchange = await sdk.exchange('mexc:spot')` | `exchange.depth('BTCUSDT')` |
| Market | `market = await sdk.market('mexc:spot:BTCUSDT')` | `market.depth()` |

## Examples

### Exchange discovery metadata

`await venue.exchanges()` returns `ExchangeDescription` records with required
`id`, `type` (`spot` or `perp`) and nonempty `name`, plus an optional official
HTTPS `url`. Names describe product families within a venue, not necessarily
distinct legal entities. They may change and are never identifiers.

For Coinbase, `spot` is named `Advanced Trade` and `intx` is named
`International Exchange`. Resolve the object with `await venue.exchange(id)`;
never substitute its display name. Hyperliquid's empty default ID stays empty,
and dynamically discovered DEXs carry their API-provided full names. Consumers
persisting metadata should key it by `(venue_id, exchange_id)`. URLs may be
omitted rather than guessed. No discovery ordering or trading-access guarantee
is implied by a name.

**Top-level**: For example, if you're working across multiple venues, you'd likely work at the top level:

```python
sdk = MarketSDK()

mexc_book, binance_book = await asyncio.gather(
  sdk.depth('mexc:spot:BTCUSDT'),
  sdk.depth('binance:usdm:BTCUSDT'),
)
if mexc_book.best_bid.price > binance_book.best_ask.price:
  print('Arbitrage opportunity!')
```

**Exchange**: If you're managing collateral within a same exchange, you'll want to scope to the exchange level:

```python
exchange = await sdk.perp_exchange('mexc:perp')
collateral = await exchange.collateral()
if collateral.maintenance_margin > 0.5*collateral.equity:
  print('You are near liquidation!')
```

**Market**: If instead you're doing many operations on a single venue, you may scope down instead:

```python
market = await sdk.market('mexc:spot:BTCUSDT')
rules, book = await asyncio.gather(
  market.rules(),
  market.depth(),
)
```

## Exchange-wide account history

Pass `None` as the market selector to read across a supported exchange:

```python
exchange = await sdk.perp_exchange('dydx:perp')
async for page in exchange.trades_history(None, start, end):
  for trade in page:
    print(trade.market_id, trade.time, trade.qty)

async for page in exchange.funding_payments(None, start, end):
  for payment in page:
    print(payment.market_id, payment.time, payment.amount)
```

Both datetime bounds are required and inclusive. Exchange-wide rows are
`ExchangeTrade` or `ExchangeFundingPayment`, with the existing record fields plus
`market_id`, the native ID within that exchange. Funding paid is positive and
funding received is negative. Hyperliquid and dYdX now apply that sign convention
to both exchange-wide and selected-market results. Passing a string market ID
keeps the existing single-market API and base record types.

Hyperliquid supports trades on spot and perpetual exchanges, and funding payments
on perpetual exchanges. Each builder DEX is scoped separately. dYdX supports both
methods for the selected subaccount (`perp` or `perp.<N>`). All other venues
currently raise `NotImplementedError` for exchange-wide reads; single-market
support is unchanged.

These reads use native account feeds, with their retention and pagination limits.
Pages have no global ordering guarantee. Hyperliquid's fills feed retains only its
recent history and does not include TWAP slice fills. A current market catalogue
is never scanned as a substitute for historical account data.

## Perpetuals

Perpetual markets are scope similarly, just use different methods:

**Top/Venue level**:

```python
await sdk.next_funding('mexc:perp:BTCUSDT') # raises NotImplementedError if the market isn't a perpetual
venue = await sdk.venue('mexc')
await venue.next_funding('perp:BTCUSDT') # raises NotImplementedError if the market isn't a perpetual
```

**Exchange**:

```python
exchange = await sdk.perp_exchange('mexc:perp') # raises NotImplementedError if you pass a non-perpetual exchange ID
await exchange.next_funding('BTCUSDT')
```

**Market**:

```python
market = await sdk.perp_market('mexc:perp:BTCUSDT') # raises NotImplementedError if you pass a non-perpetual market ID
await market.next_funding()
```

<!-- next -->

---

← [Market Identifiers](identifiers.md) · **Next:** [Your First Order](first-order.md) →

<!-- /next -->
