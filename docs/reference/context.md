# Context, Logging & Retries

> [!NOTE]
> <!-- tldr -->
> The SDK uses a middleware-based system. You can use this to retry on failure, log calls, or add your own middleware.
>

## Introductory Example

The SDK's methods run plainly by default. But you can easily wrap them to add exponential backoff retries (and more):

```python
from tribulnation.sdk import EarnSDK, Context, NetworkError, RateLimited

earn = EarnSDK()

with Context().retried(NetworkError, RateLimited, max_retries=5).use():
  instruments = await earn.instruments(tags=['flexible'])
  print('OK')
  # Retry 1 for instruments after NetworkError('No network connection'); sleeping 1.00s
  # Retry 2 for instruments after NetworkError('No network connection'); sleeping 2.00s
  # OK
```

## What else can it do?

You can also add logging, or you own middleware. Let's see logging first:

```python
from tribulnation.sdk import MarketSDK, Context, NetworkError, RateLimited

market = MarketSDK()

with Context().logged().use():
  tickers = await market.tickers('mexc:spot')
  # Calling "tickers" with args: ('mexc:spot',), kwargs: {}
  # Calling "tickers -> exchange" with args: ('mexc:spot',), kwargs: {}
  # Calling "tickers -> exchange -> venue" with args: ('mexc',), kwargs: {}
  # Calling "tickers -> exchange -> exchange" with args: ('spot',), kwargs: {}
  # Calling "tickers -> tickers" with args: (), kwargs: {'markets': None, 'settings': {}}
```

And now you know what's going on under the hood! Let's explore it further.

## How it works

All external methods in the SDK (`Market.place_order`, `Earn.instruments`, etc.) are decorated with `@SDK.method`. The decorator checks for an active `Context` and, if found, applies its middleware to the call.

Therefore, it's not only the method you call: any delegated calls made inside it will also have the same context applied. If there's a long method hitting rate-limits, do not worry!: the inner calls will be retried, not just the whole thing.

## Writing your own middleware (unstable)

A middleware is a callable with this signature:

```python
def middleware(self, fn: Fn, ctx: Context) -> Fn:
  ...
```

Here `Fn` is a callable type and `Context.path: tuple[str, ...]` is a tuple of the method names that have been called to reach this point. This API is yet unstable and may change in the future. Feel free to reach out/open an issue to discuss improvements.
