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

## typed-grvt

### `Ticker.funding_rate` is documented in centibeeps but sent in percentage points

`market.ticker` sends `funding_rate` in the same percentage points as `market.funding_rate`'s
`FundingRate.funding_rate`, not in centibeeps as declared (GRVT's schema docs also say
centibeeps).

`schemas.py:612`:

```python
  funding_rate: NotRequired[Decimal]
  """The current indicative funding rate for the active interval, expressed in centibeeps."""
```

- Kind: wrong-unit (docstring; the declared type is right)
- Observed: 2026-10-22 mainnet, indicative vs last settled (`FundingRate.funding_rate`, percent) vs `adjusted_funding_rate_cap`: BTC_USDT_Perp `0.01` / `0.0057` / `0.3`; ETH `-0.0053` / `0.0021` / `0.3`; XAU (4 h) `0.0017` / `0.0046` / `0.5`. Always equal to the deprecated `funding_rate_8h_curr`. Read as centibeeps, BTC's `0.01` would be 1e-8 of notional, four orders of magnitude below every settlement.
- Blocks: nothing; `poc/market/perp.py` cells 24 (`next_funding`), 25 (unit check) and 26 (`perp_stats`) divide by 100 on this evidence
- Suggestion (unverified): document percentage points over `funding_interval_hours`, as `FundingRate.funding_rate` does

### `ClientTier` fee docstrings leave the unit undocumented and give `450` as every tier-1 rate

`trading.funding_account_summary`'s `tier` sends integers in millionths of notional, and
tier 1's maker, spot and options values are not `450`.

`schemas.py:763`:

```python
  futures_taker_fee: int
  """Futures taker fee at this tier, an integer rate in a unit GRVT does not document (`450` for the first tier)."""
  futures_maker_fee: int
  """Futures maker fee at this tier, an integer rate in a unit GRVT does not document (`450` for the first tier)."""
```

(the options and spot fields at lines 767-774 likewise)

- Kind: wrong docstring (the declared type is right)
- Observed: mainnet and testnet, tier 1: `futures_taker_fee 450, futures_maker_fee -1, options_taker_fee 450, options_maker_fee -1, spot_taker_fee 850, spot_maker_fee 600`. The unit is fixed by GRVT's published schedule (tier 1 perps: taker 0.0450%, maker -0.0001%) and by testnet tier-1 taker fills: `fee_rate` `0.045` (percent), `fee` `0.07404` on 0.002 BTC at 82267 (= notional × 450e-6).
- Blocks: nothing; `poc/market/perp.py` cell 9 (`fees`) scales by 1e-6 on this evidence
- Suggestion (unverified): document millionths of notional (GRVT's "centibeeps") and drop the shared `450` example

### `set_position_config` is missing, so no position can be made isolated

GRVT sets a sub-account's margin type (isolated or cross) and leverage per instrument with
the signed `set_position_config` RPC; `typed-grvt` has no endpoint for it (only the
deprecated `set_initial_leverage`, which takes no margin type), so an account whose
instruments are all cross can never hold an isolated position through the client.

- Kind: missing-endpoint
- Docs: <https://api-docs.grvt.io/trading_api/> (Position: `set_position_config`; listed in typed-dev's own `clients/grvt/spec/discovery.md`, left out until its EIP-712 encoding is verified)
- Observed: 2026-10-22 testnet, `all_initial_leverage` reports `margin_type` `CROSS` for all 200 instruments of the funded account; `create_order` takes no margin type
- Blocks: `poc/market/perp.py` cell 33 (`perp_collateral`: the isolated bucket raises `NotImplementedError` until an isolated position can be opened and read)

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
