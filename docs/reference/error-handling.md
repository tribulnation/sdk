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
  - `ApiError` — the venue returned an error or could not supply required data.
    - `MissingData` — a successful response omitted required market data;
      `market_id` identifies the native instrument and `field` the SDK field.
    - `BadRequest` — invalid request or input.
    - `AuthError` — invalid or missing credentials.
    - `RateLimited` — the venue's rate limit was hit.
    - `OrderRejected` — the venue answered that an order was not accepted: nothing
      rests and nothing filled.
  - `LogicError` — a bad assumption on the SDK's side, i.e. a bug.

Implementations translate their venue's errors into these classes at the edge, so
`RateLimited` from MEXC and `RateLimited` from dYdX are the same exception.

## Rejected or unknown?

When `place_order` fails, the question that matters is whether the order exists.
`OrderRejected` is the only definitive answer: the venue processed the request and
refused the order, so it is dead and can be sent again, e.g. an IOC with nothing to
match against. Every other error may be ambiguous. A `NetworkError` or a 5xx `ApiError`
can arrive after the venue accepted the order, so check `open_orders` or your fills
before re-sending. Venues raise `OrderRejected` only where their answer makes the
refusal certain (currently Hyperliquid, Aster and Lighter); elsewhere refusals stay
`ApiError` or `BadRequest`.

```python
from tribulnation.sdk import OrderRejected

try:
  await sdk.place_order(market_id, order)
except OrderRejected:
  ...  # nothing was placed: safe to re-send
```

`OrderRejected` subclasses `ApiError`, so existing `except ApiError` handlers still catch
it. It keeps its class across the [gateway](../gateway.md).

Two related notes: [Context](context.md) retries whichever of these you choose — usually
`NetworkError` and `RateLimited` — and errors raised while *acquiring* a resource are not
translated, as covered in [Async Usage](async-usage.md).

<!-- next -->

---

← [Async Usage](async-usage.md) · **Next:** [Context, Logging & Retries](context.md) →

<!-- /next -->
