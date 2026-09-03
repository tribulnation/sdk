# Async Usage

> [!NOTE]
> <!-- tldr -->
> Await any method and it works. Wrap the object in `async with` to decide when its
> connections close.

## One-shot calls

Every method works on an object you never entered:

```python
from tribulnation.sdk import MarketSDK

sdk = MarketSDK()
book = await sdk.depth('hyperliquid::BTC')
```

Clients connect lazily: the first call opens a connection and keeps it for the next one.
Nothing closes it, though, so it lives until the process exits. That is fine for a script
or a notebook.

## Owning the connections

`async with` is how you choose when they close:

```python
async with MarketSDK.load('sdk.toml') as sdk:
  book = await sdk.depth('hyperliquid::BTC')
  await sdk.place_order('dydx:perp:BTC-USD', {'type': 'MARKET', 'qty': -1})
# every connection this sdk opened is closed here
```

Entering connects nothing — it only takes ownership — so there is no cost to entering
early. Do it in anything long-running, and anywhere you build SDK objects repeatedly: one
dropped without exiting takes its open connections with it.

## Entering a parent enters its children

Objects obtained from an entered parent are already live:

```python
async with venue:
  market = await venue.perp_market('BTC')
  await market.depth()  # correct -- already entered
```

Re-entering one is an error:

```python
async with venue:
  market = await venue.perp_market('BTC')
  async with market:  # RuntimeError: resources are already active
    ...
```

Enter whichever level you actually hold. Entering a child directly is fine when you did
not enter its parent.

## Streams are always entered

`depth_stream()` and `trades_stream()` return async context managers of their own,
whether or not you entered the SDK:

```python
async with sdk.trades_stream('mexc_account1:spot:BTCUSDT') as trades:
  async for trade in trades:
    print(trade)
```

See [Streaming](../market/streaming.md) for buffering and overflow behaviour.

## Notes

- Exceptions raised while *acquiring* a resource are not translated into the SDK error
  taxonomy — you may see a venue-native error from `async with`. See
  [issue #2](https://github.com/tribulnation/sdk/issues/2).
- Writing your own SDK object, or a venue implementation? Owning resources is covered in
  [CONTRIBUTING.md](https://github.com/tribulnation/sdk/blob/main/CONTRIBUTING.md#writing-sdk-objects).
