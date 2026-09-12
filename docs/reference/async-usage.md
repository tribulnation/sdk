<!-- github-only -->
<table><tr>
<td align="center"><a href="../index.md">Docs</a></td>
<td align="center"><a href="../market/index.md">Market</a></td>
<td align="center"><a href="../earn/index.md">Earn</a></td>
<td align="center"><a href="../wallet/index.md">Wallet</a></td>
<td align="center"><a href="../report/index.md">Report</a></td>
<td align="center"><b>Reference</b></td>
<td align="center"><a href="https://tribulnation.com/sdk/docs/support">Support matrix</a></td>
</tr></table>
<!-- /github-only -->

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

An entered `MarketSDK` constructs venues lazily, once per account ID within that context.
Repeated `venue()`, `exchange()` and `market()` routes share their venue's clients,
metadata caches and subscriptions. Unused accounts are neither constructed nor entered.
A newly requested venue is entered before its lookup returns; most transports connect
only on use, but venue-specific initialization (such as loading a signing wallet) may
perform I/O.

Root exit closes acquired venues in reverse acquisition order and clears the cache,
including when the body or cleanup raises. Re-entering the root creates fresh venues.
Keep borrowed references within their owner's context, and finish tasks and stream
contexts before leaving it.

For a long-lived service or strategy gateway, enter the root once around the service
lifetime. Consumers can continue borrowing markets without managing each one:

```python
async with MarketSDK(accounts=accounts) as sdk:
  maker = await sdk.market(maker_id)
  hedger = await sdk.market(hedger_id)
  await run_strategy(maker, hedger)
```

## Standalone factories

Outside a root context, each routed market venue is fresh and caller-managed:

```python
sdk = MarketSDK(accounts=accounts)
venue = await sdk.venue('my_account')
async with venue:
  market = await venue.market('spot:BTCUSDT')
  book = await market.depth()
```

Entering the root does not adopt venues previously constructed outside it. They remain
independently owned; managed lookups create separate venues even for the same account.

The synchronous `MarketSDK.all` property remains a factory collection outside a root
context. Within an entered root it can return already acquired venues, but raises if
any venue still needs acquisition: use `await sdk.venue(id)` for those lookups. Accessing
`sdk.all` outside a context constructs fresh caller-managed venues for every account.

`EarnSDK`, `WalletSDK` and `ReportSDK` retain their synchronous `venue()` factory APIs:
enter the returned child, not the root. Direct venue-specific factories also remain
independently owned; they do not participate in a `MarketSDK` root's routing cache.

```python
from tribulnation.sdk import WalletSDK

wallet = WalletSDK(accounts=accounts).venue('my_account')
async with wallet:
  methods = await wallet.deposit_methods()
```

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

<!-- next -->

---

← [Reference](index.md) · **Next:** [Error Handling](error-handling.md) →

<!-- /next -->
