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
