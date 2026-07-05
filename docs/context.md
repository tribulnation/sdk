# Context, Logging & Retries

> Wraps SDK calls with opt-in logging and retries.

`@SDK.method` wraps every trading/wallet/earn/report method. Without an active `Context`, calls run plainly — no logging, no retries. Activating one applies its middleware to that call, and to any nested `@SDK.method` calls made inside it.

- `Context().retried(*exceptions, max_retries=None, base_delay=1.0, max_delay=None)`
- `Context().logged(log_self=False)`
- `Context().add(middleware)`

Nested calls (e.g. the SDK-level `place_order` calling the underlying `Market.place_order`) each re-apply the active context, so a persistent failure can be retried at every layer it passes through, not just once.

**Example:**

```python
from tribulnation.sdk import Context, NetworkError, RateLimited

ctx = Context().retried(NetworkError, RateLimited, max_retries=5).logged()
with ctx.use():
  await sdk.place_order('mexc_account1:spot:BTCUSDT', {'type': 'LIMIT', 'qty': 0.01, 'price': 60_000})
```
