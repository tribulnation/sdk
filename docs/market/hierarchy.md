# Hierarchy & Scoping

The markets implementation is structured following the market IDs: `account` → `venue` → `exchange` → `market`.

| Level | Instantiation | Example |
| --- | --- | --- |
| Top-level | `sdk = MarketSDK()` | `sdk.depth('mexc:spot:BTCUSDT')` |
| Venue | `venue = await sdk.venue('mexc')` | `venue.depth('spot:BTCUSDT')` |
| Exchange | `exchange = await sdk.exchange('mexc:spot')` | `exchange.depth('BTCUSDT')` |
| Market | `market = await exchange.market('mexc:spot:BTCUSDT')` | `market.depth()` |

## Examples

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
