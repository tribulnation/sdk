# Market

> `Market` places orders and queries data for a single account/exchange/market.

- `depth()`, `depth_stream()`, `rules(refetch=False)`
- `query_order(id)`, `open_orders()`, `trades_history(start, end)`, `trades_stream()`, `position()`, `available_notional()`
- `place_order(order, settings={})`, `place_orders(orders, settings={})`, `cancel_order(id, settings={})`, `cancel_orders(ids, settings={})`, `cancel_open_orders(settings={})`
- Perp only: `index()`, `next_funding()`, `funding_history(start, end)`, `funding_payments(start, end)`, `perp_position()`

The first segment of a market ID is the *account ID* (your `accounts` mapping key), not the venue's name. `rules()` is cached by default; pass `refetch=True` to bypass. `position()`/`perp_position()` return the same data on `PerpMarket`, just typed differently.

**Example:**

```python
import os
from tribulnation.sdk import MarketSDK, accounts
from dotenv import load_dotenv

load_dotenv()

market = MarketSDK({
  'dydx-account1': accounts.Dydx(),
})

await market.place_order('dydx-account1:perp:BTC-USD', {
  'price': 10,
  'qty': 0.00001,
  'type': 'LIMIT'
}, settings={
  'dydx': {
    'limit_tif': 'IMMEDIATE_OR_CANCEL',
    'order_flags': 'SHORT_TERM',
    'short_term_gtb': 2
  }
})
```
