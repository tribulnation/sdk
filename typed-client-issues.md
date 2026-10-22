# Open typed-client issues

## typed-aster

### Request decimals reach the wire as their `str()`, in exponent form when round or tiny

`dump_request` round-trips every request through the validator's JSON dump, so a
`Decimal` reaches the transport already turned into its `str()`. `wire_value` writes a
`Decimal` positionally (`format(value, 'f')`, `core/transport/http.py:48`), but it only
ever sees the string. `Decimal('1.9E+2')` goes out as `quantity=1.9E%2B2`, and so does any
decimal below `1E-6`, even one built positionally (`Decimal('0.0000001')` is `1E-7`). The
venue rejects both.

`core/endpoint/wire.py:20`:

```python
  return json.loads(validator(cast(type, request_type)).dump(request))
```

- Kind: wrong-serialization (a valid `Decimal` the venue cannot parse)
- Observed: `{'code': -1102, 'msg': "Mandatory parameter 'quantity' was not sent, was empty/null, or malformed."}` for a step-rounded 190-unit `ENAUSDT` order
- Blocks: nothing listed today. `native_order` writes quantities and prices through `plain_decimal`, which is enough for every value of `1E-6` or more. A price below `1E-6` would still be rejected; the lowest Aster price is `0.0000095` (`1000SATSUSDT`), against a smallest tick of `1E-8`.

## typed-extended

### `balance` and `spot_balances` raise a bare `BadRequest(404, '')` for an account holding nothing

The venue answers a sub-account with no balance at all with HTTP 404 and an empty body
(docs: "Returns a 404 error if the user's balance is 0"). The client raises it as
`BadRequest(404, '')`, the same error an unknown path gets, so a caller can only tell
"zero" from a broken request by matching the status.

`account/balance.py:50`:

```python
  async def balance(self, *, validate: bool | None = None) -> Balance:
```

- Kind: absent-under-condition
- Observed: HTTP 404, empty body, from both `account.balance` and `account.spot_balances`
- Condition: the sub-account holds no asset at all
- Samples: mainnet 321158 (0 USD) raises on both; testnet 3880 (994.79 USD) validates. 321158's account-stream `BALANCE` snapshot sends every field as `0`.
- Blocks: `poc/market/perp.py` cell 1 (the `balance` helper, read by cells 17 `available_notional` and 30 `perp_collateral`), `poc/report.py` cells 3 (`snapshot`) and 4

### `order` raises a bare `BadRequest(404, '')` for an unknown order id

`account.order` gets the same bodiless 404 for an id the venue does not know, so "no such
order" is indistinguishable from a broken request.

`account/order.py:17`:

```python
  async def order(self, id: int, *, validate: bool | None = None) -> Order:
```

- Kind: absent-under-condition
- Observed: HTTP 404, empty body
- Condition: the order id is unknown to the venue (never existed, or past its retention)
- Samples: a closed testnet order parses; an unknown id raises
- Blocks: `poc/market/perp.py` cell for `query_order` (reads the 404 as `None`)

### `orderbook` fails validation on inactive and unknown markets

`info.orderbook` gets `{"status":"OK"}` with no `data` for a market whose `active` is
false, or a name the venue does not know. The core unwraps the missing `data` to `None`,
which the declared `Orderbook` rejects (`Input should be a valid dictionary`).

`info/orderbook.py:28`:

```python
  async def orderbook(self, market: str, *, validate: bool | None = None) -> Orderbook:
```

- Kind: absent-under-condition
- Observed: HTTP 200 `{"status":"OK"}`, no `data`
- Condition: `active: false` or unknown market; a delisted market still `active: true` answers an empty book
- Samples: MATIC-USD, FTM-USD (`DELISTED`, inactive) and NOPE-USD fail; NOW_24_5-USD (`DELISTED`, active) and MKR-USD (`REDUCE_ONLY`) validate with 0/0 levels
- Blocks: nothing in the PoC, whose `markets` leaves delisted markets out; `depth` of an inactive market raises `ValidationError` instead of an API error

### `spot_balances(account_id=...)` sends a filter the venue ignores

From one API key, every `accountId` value returns that key's own sub-account, with no
error, so the parameter promises a cross-account read the venue does not do.

`account/spot_balances.py:67`:

```python
      request['accountId'] = account_id
```

- Kind: wrong request shape
- Observed: from 3880's key, `[3881]` (sub-account 1 of the same wallet), `[1]` and `[999999999]` each return only `(3880, 'USD')` (testnet, 2026-10-22)
- Blocks: nothing; one API key reads exactly one sub-account

### `AssetOperation.accountId`/`counterpartyAccountId` docstrings give the wrong transfer direction

`accountId` is always the key's own sub-account and the amount's sign gives the direction:
on an incoming transfer `accountId` is the destination and `counterpartyAccountId` the
source, the opposite of what the docstrings say.

`account/asset_operations.py:29`:

```python
  accountId: int
  """Source account for transfers and withdrawals; destination account for deposits."""
  counterpartyAccountId: NotRequired[int]
  """Destination account of a transfer."""
```

- Kind: wrong description
- Observed: operations `2112523545589317632` (`+10`) and `2112523528711438336` (`-10`), both `accountId` 3880 and counterparty 3881 (testnet)
- Blocks: nothing; `poc/report.py` cell 7 derives the direction from the sign

### `candles` and `funding_rates` have no `_paged` walk

Both endpoints truncate a wide range (candles at 2800 rows live, though the docstring
says 10,000; funding rates at 1000 rows, ignoring `cursor`/`limit`), so every caller walks
them by hand.

`info/candles.py:58`: the docstring's "at most 10,000 candles per request".

- Kind: missing-endpoint (pagination declaration)
- Observed: 2800-row cap on candles; 1000-row cap on funding rates, newest first, `endTime` moved back per page
- Blocks: `poc/market/perp.py` `candles` and `funding_rates` cells (hand-rolled windows)

## typed-lighter

### `Candle` OHLCV fields are `float`

The venue sends candle prices and volumes as JSON numbers, and the client declares them
`float`, so a `Decimal` consumer has to go through `Decimal(str(x))`. Volumes arrive with
binary noise (`12.927500000000002`, `4883.652435999999`) that a `Decimal` parse of the raw
JSON text would keep as sent, but a `float` round-trip cannot tell apart from real digits.

`schemas.py:94`:

```python
  o: NotRequired[float]
```

(and `h`, `l`, `c`, `v`, `V` at lines 96-104; `MarkPriceCandle` at 708-714 likewise)

- Kind: wrong-type (too loose for money: validates, but loses the textual form)
- Observed: `"o": 2680.38`, `"v": 12.927500000000002`
- Blocks: `poc/market/perp.py` cell 10 and `poc/market/spot.py` cell 9 (`parse_candle`); tracked fleet-wide in typed-dev#229

### `MarketStats` and `PerpsOrderBookDetail` volumes and open interest are `float`

`MarketStats.daily_base_token_volume` / `daily_quote_token_volume` and
`PerpsOrderBookDetail.open_interest` (and its daily volumes) are declared `float`, while the
prices beside them are `Decimal`.

`schemas.py:756`:

```python
  daily_base_token_volume: float
  """24-hour volume, in base units."""
  daily_quote_token_volume: float
```

`api/markets/order_book_details.py:164`:

```python
  open_interest: float
```

- Kind: wrong-type (too loose for money)
- Observed: `daily_base_token_volume: 104077.34300000001`, `open_interest: 213.494`
- Blocks: `poc/market/perp.py` cells 7 (`tickers`) and 28 (`perp_stats`); `poc/market/spot.py` cell 6 (`tickers`), where `SpotMarketStats` volumes are `float` likewise; tracked fleet-wide in typed-dev#229

## typed-margin-trade

### `DerivativeContract.next_funding_rate_timestamp` is epoch seconds, parsed as milliseconds

`coingecko.derivatives.contracts` sends the next funding time in seconds; the declared
`TimestampMillis` turns it into a January 1970 date.

`coingecko/derivatives/contracts.py:47`:

```python
  next_funding_rate_timestamp: TimestampMillis
```

- Kind: wrong-type
- Observed: `1970-01-21 17:56:38.400` for every contract at 15:2x UTC on 2026-10-21, i.e.
  the raw `1792598400`, which as seconds is 2026-10-21 16:00 UTC, the next hourly settlement
- Samples: BTC-USD and ETH-USD, testnet and mainnet
- Blocks: nothing yet: `next_funding` and `perp_stats` use the documented hourly cadence
  (settlements land on the hour in `userFunding`); the fix would let them read the venue's
  own next time

### `Info.order_status(cloid=...)` sends a field the venue does not read

The venue looks a client order id up through `oid` (`{"oid": "0x..."}` finds the order),
and answers a request carrying `cloid` instead with `oid or cloid is required`, raised as
`BadRequest`.

`info/order_status.py:60`:

```python
    if cloid is not None:
      request['cloid'] = cloid
```

- Kind: wrong request shape
- Observed: `order_status(user=..., cloid='0x1f1f...1f')` raises `BadRequest(oid or cloid is
  required)` for a resting order that `order_status(user=..., oid='0x1f1f...1f')` returns
  (testnet, 2026-10-21)
- Blocks: nothing: the SDK queries by exchange order id

### `Exchange.usd_class_transfer` amount is micro-USDC, and an agent signature moves the agent's own funds

The docstring and the deposits/withdrawals how-to call `amount` a USDC amount
(`usd_class_transfer(Decimal('1'), to_perp=False)` "perp -> spot"), but `'1'` moves
`0.000001` USDC: the venue reads micro-units, as `withdraw` does (documented there).
Signed by an approved agent with `vault`, the same call answers `failed to transfer:
insufficient balance` while the master's perp wallet holds ~100k: the venue acts on the
agent's own (empty) account, so the call is effectively master-only.

`exchange/usd_class_transfer.py:27` and `:38`:

```python
      amount: USDC amount, as a decimal string.
      ...
      meta={'auth': 'signed'},
```

- Kind: wrong-type (unit), plus an auth scope (`signed` where only the master works)
- Observed: master `amount='1'` moved `0.000001` (spot balance `0.000001`), `'20000000'`
  moved 20; agent with `vault` refused with `insufficient balance` (testnet, 2026-10-21)
- Blocks: nothing in the SDK (no transfer method); `poc/market/spot.py` lifecycle signs its
  transfers with the master key and micro-units
