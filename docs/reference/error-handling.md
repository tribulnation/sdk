# Error Handling

> [!NOTE]
> <!-- tldr -->
> Every error the SDK raises subclasses `Error`, whatever the venue.

```python
from tribulnation.sdk import Error, RateLimited

try:
  await sdk.place_order('mexc_account1:spot:BTCUSDT', order)
except RateLimited:
  ...
except Error as e:
  print(f'Order failed: {e}')
```

## The hierarchy

- `Error` — base class for everything below.
  - `NetworkError` — the venue could not be reached.
  - `ValidationError` — the response did not match the expected shape.
  - `ApiError` — the venue returned an error.
    - `BadRequest` — invalid request or input.
    - `AuthError` — invalid or missing credentials.
    - `RateLimited` — the venue's rate limit was hit.
  - `LogicError` — a bad assumption on the SDK's side, i.e. a bug.

Implementations translate their venue's errors into these classes at the edge, so
`RateLimited` from MEXC and `RateLimited` from dYdX are the same exception.

Two related notes: [Context](context.md) retries whichever of these you choose — usually
`NetworkError` and `RateLimited` — and errors raised while *acquiring* a resource are not
translated, as covered in [Async Usage](async-usage.md).
