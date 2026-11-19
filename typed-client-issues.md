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

## typed-evedex

### `Instruments.instruments` returns the union of every `fields` shape

`exchange.market.instruments` sends a different record per `fields` (full records by
default, summaries for `short`, full records with funding, volume and open interest for
`metrics`), but declares one return type for all three, so a caller who asked for
`metrics` still gets the union and has to cast to reach `fundingRate` or `openInterest`.
The values validate as the right member (prod, 2026-11-19: `fields='metrics'` rows keep
every metric), so this is a typing gap, not a validation one.

`exchange/market/instruments.py:177`:

```python
Response = list[InstrumentInfo] | list[InstrumentSummary] | list[Instrument]
```

- Kind: wrong-type (declared wider than any one call returns)
- Observed: `fields=None` sends `InstrumentInfo` rows, `fields='metrics'` sends
  `Instrument` rows (70 of each on prod)
- Blocks: `pkg/src/tribulnation/evedex/core.py` (`load_instruments`) and
  `pkg/src/tribulnation/evedex/market/exchanges.py` (`metrics`): a `cast` bridging the
  union to the requested shape; `poc/market/perp.py` cells 1, 6 and 22
- Suggestion (unverified): `@overload` on `fields`

### Centrifugo `temporary` subscribe errors raise the final `ApiError`

`raise_error` maps every Centrifugo command error outside permission, token and
bad-request codes to `ApiError`, ignoring the error's `temporary` flag. On 2026-11-19
(probed read-only after the owner's 14:09 UTC run) prod answered every subscribe, public and private alike
(`futures-perp:orderBook-XRPUSD-0.1`, `futures-perp:heartbeat`,
`futures-perp:orderFills-83911`), with `{"code": 100, "message": "internal server
error", "temporary": true}`, after a successful `connect`. Centrifugo's `temporary`
means the client should retry; as an `ApiError` the SDK translates it to its final
`ApiError`, which no retry middleware treats as transient. Subscribes at 13:39 and
13:56 the same day succeeded.

`core/transport/ws.py:101`:

```python
  if code in (UNKNOWN_CHANNEL, BAD_REQUEST):
    raise BadRequest(context)
  raise ApiError(context)
```

- Kind: wrong-type (error classification: a transient failure raised as a final one)
- Observed: code `100`, `temporary: true`, on every channel, wallet session or none
- Blocks: `pkg/src/tribulnation/evedex/market/books.py` and `market/history.py`
  (`depth_stream` and `trades_stream` cannot be retried on it); the owner's 2026-11-19
  lifecycle run, whose `trades_stream` saw none of its 2 fills
- Suggestion (unverified): `NetworkError` when `temporary` is true

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

## typed-nado

### `archive_v2.tickers` declares prices and volumes as `float`

The archive's REST v2 sends `last_price`, `base_volume` and `quote_volume` as JSON numbers,
and typed-nado declares them `float`, so a price reaches Python already rounded to a
binary float. The same holds for `archive_v2.contracts` (`index_price`, `mark_price`,
`funding_rate`, `open_interest`, ...).

`archive_v2/tickers.py:26`:

```python
  last_price: float
```

- Kind: wrong-type
- Observed: `"last_price": 64304.0`, `"quote_volume": 212003391.2444924` (BTC-PERP, mainnet, 2026-11-17)
- Blocks: `pkg/src/tribulnation/nado/market/stats.py` (`decimal`, read back through the
  float's shortest repr) and `poc/market/{perp,spot}.py` `tickers`
- Suggestion (unverified): decode the v2 bodies with `parse_float=Decimal` and declare
  `Decimal`

### `archive.matches_paged` drops the `txs` that time each match

A `Match` carries no time: it is joined to its transaction in the page's `txs` by
`submission_idx`. `matches_paged` yields only `matches`, so a paged walk loses every
fill's time, and the adapter walks `matches` by hand with `idx` instead.
`matches_and_liquidations_paged` has the same gap.

`archive/matches.py:37`:

```python
  def matches_paged(
```

- Kind: missing-endpoint (a paged walk that keeps each row's transaction)
- Observed: `Matches = {matches, txs}`; `PaginatedResponse[Match, ...]`
- Blocks: `pkg/src/tribulnation/nado/market/history.py` (`matches`, a hand walk)
- Suggestion (unverified): page `(Match, Tx)` pairs, or attach the timestamp to each row
