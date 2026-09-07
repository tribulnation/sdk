# Typed client issues

Open defects in the `typed_*` clients and in the generator that produces them, found by
running the PoC notebooks under `packages/impl/*/poc/` against the live venues. This file
is the hand-over from the sdk repo to typed-dev: it is meant to be read there without
anything else from here.

## How to read an entry

Entries are grouped by client under `## typed-<venue>` (`## codegen` and `## typed-core`
for the shared parts) and titled by the declaration they concern. Each carries:

- the declaration as it stands, quoted, with its path relative to the client package
  (`typed_<venue>/`), or to the typed-dev repo for `codegen` and `typed-core`;
- `Kind`: `wrong-type` (the venue always sends something the type rejects),
  `absent-under-condition` (missing, `null` or `''` only sometimes), `missing-literal`
  (a value outside a `Literal`), or `missing-endpoint` (the venue documents what the
  client cannot express);
- `Observed`, `Condition`, `Samples`: what the wire carried and when. An entry whose
  `Observed` says the endpoint could not be reached (Binance signed USD-M futures,
  Coinbase INTX, MEXC futures, Moralis) was verified against the declaration only; read
  it as "the declared type looks wrong", not "seen on the wire";
- `Blocks`: the notebook cells and `pkg/` code on the sdk side that wait on the fix;
- `Suggestion`, when present: unverified, and never acted on in the PoC.

The file records what the venue sent, not what the type should be. Whether a field
becomes optional, a union or a wider literal is typed-dev's decision, which is why entries
carry `Condition` and `Samples` rather than a fix.

## The round trip

1. typed-dev fixes and releases. It does not edit this file; disagreement with an entry
   goes in typed-dev's own commit message or docs.
3. The sdk side re-runs the cells named under `Blocks` against the released client. When
   they pass, the entry is deleted, not marked fixed; git history is the record.
4. New entries are added only from a PoC that hit the defect live, in the format above.
   The rules are in `.agents/skills/sdk-poc/SKILL.md`.

## Priority

By what a fix unblocks on the sdk side, most first, except that a defect leaking
credentials comes first regardless:

1. typed-core `NetworkError` messages embed the request URL: an Alchemy API key, or a
   Binance private-stream `listenKey`, reaches every log, traceback and crash report a
   consumer keeps.
2. typed-etherscan `erc20_transfers_paged`/`erc721_transfers_paged` require
   `contractaddress`: a regression; two spec `required` lists; restores `history()` on
   four chains.
3. typed-hyperliquid `AssetPosition.liquidationPx` is `null`: breaks `Report.snapshot()`
   on any mainnet account holding such a position.
4. typed-core `ValidationError` carries no message: cheap, and makes every future
   finding legible at the sdk boundary.
5. codegen `number` fields with an epoch format render as `float`: Kraken's whole history
   surface.
6. typed-bit2me `float` money fields (both entries): silent precision loss in shipped
   balances today.
7. Everything else is typing quality; nothing shipped is wrong because of it.

## Environment

- The sdk venv installs every `typed_*` client editable from the typed-dev main checkout
  (`clients/<venue>/pkg`), on `pagination-redesign` @ `642e265f8` as of 2026-09-06.
  Whatever lands there is what the PoCs run against immediately; this file was verified
  against that commit.
- The impls now floor their client dependencies at the versions found there
  (typed-binance 2.0, bit2me 0.4, bitget 0.4, bybit 0.3, coinbase 0.4, dydx 4.0,
  hyperliquid 3.0, alchemy 3.0, etherscan 0.4, moralis 0.3). Those must reach PyPI before
  the impls can be released.

## codegen

### `number` fields carrying an epoch format render as bare `float`

`Parser.number()` never consults `TIMESTAMP_FORMATS`, so a field spec'd `type: number,
format: epoch-seconds` generates as `float` instead of the client's `TimestampSeconds`
alias. `Parser.string()` and `Parser.integer()` both branch on the format; the `number`
case drops it silently, where an unsupported string format at least raises.

`common/client-generation/src/client_generation/python/types/parser.py:167-170`:

```python
  def number(self, schema: Schema, id: str | None = None) -> Type:
    if schema.enum:
      return {'type': 'literal', 'values': schema.enum, 'id': id}
    return {'type': 'ref', 'id': 'float'}
```

- Kind: wrong-type
- Observed: typed-kraken `spot/account/trades_history.py:17` `time: float` (required) and
  `ledgers.py:12`, `open_positions.py:21`, `query_ledgers.py:11`, `query_trades.py:15`
  `time: NotRequired[float]`; typed-moralis `bitcoin/blockchain/transaction.py:97,122,147`
  `blockTime: float`, `evm/defi/{detailed_positions.py:74,wallet_positions.py:73,wallet_protocols.py:87}`
  `syncedAt: dict[str, float | TimestampIso]`, `schemas.py:228,1641` `blockTime: float | None`.
  Control: `bitcoin/blockchain/block.py:64` renders `TimestampSeconds` for the same field
  spec'd `type: integer`.
- Condition: always; all 13 `type: number` timestamp nodes in the specs use `epoch-seconds`
- Samples: kraken `trades_history` rows land `Trade.time` as a raw epoch float
  (`packages/impl/kraken/poc/market.ipynb` cell 6); kraken ledger rows coerce at runtime
  through pydantic but fail the type check (`poc/reporting.ipynb` cell 2)
- Blocks: `packages/impl/kraken/poc/market.ipynb` cell 6 (`trades_history`) and
  `poc/reporting.ipynb` cell 2 (`history`), plus the 16 pyright errors `sdk-dev poc check
  kraken` reports from them
- Suggestion (unverified): give `Parser.number()` the `TIMESTAMP_FORMATS` branch
  `Parser.integer()` has

### `validate=False` returns a value that contradicts the declared return type

`validate` is a plain keyword argument, not an overload discriminant, so an unvalidated
call is typed as if validated: a `TimestampMillis` field reveals as `datetime` and arrives
as `'1786616376100'`, a `Decimal` field arrives as `'0.0001'`. No client has a single
`@overload` on an endpoint (`grep -rl @overload clients/*/pkg/src` hits one unrelated
file in mexc).

typed-bybit `asset/coin_info.py`:

```python
  async def coin_info(
    self,
    coin: str | None = None,
    *,
    validate: bool | None = None,
  ) -> CoinInfoResult:
```

- Kind: wrong-type
- Observed: every generated endpoint
- Condition: `validate=False`
- Blocks: nothing in this repo; the sdk-poc rule forbids `validate=False`, so the only
  consumer is a future raw-read that wants an honest type
- Suggestion (unverified): overload each endpoint so `validate=False` returns a distinct
  raw variant

### Discriminated endpoints return an undiscriminated union

The generator emits no `@overload`, so an endpoint whose response shape follows a literal
argument returns the whole union whatever the caller passed.

typed-bybit `market/tickers.py:201` and `market/instruments.py:306`:

```python
Response = SpotTickers | ContractTickers | OptionTickers
Response = SpotInstrumentsInfo | ContractInstrumentsInfo | OptionInstrumentsInfo
```

typed-binance `usdm_futures/http/market/premium_index.py:57`, where `MarkPriceInfo0` (`:8`)
and `MarkPriceInfoItem` (`:29`) are the same eight fields, docstring for docstring:

```python
Response = MarkPriceInfo0 | list[MarkPriceInfoItem]
```

- Kind: wrong-type
- Observed: a `category='linear'` call is typed as possibly `SpotTickers`; `premium_index`
  with a `symbol` is typed as possibly a list
- Condition: always
- Samples: `packages/impl/bybit/poc/market.ipynb` cells 4, 8, 9, 15, 19, 20, 25 each
  `assert x['category'] == ...`
- Blocks: the six `assert` narrowings in `packages/impl/bybit/pkg` (`market/perp_exchange.py`,
  `market/perp_market.py` ×2, `market/spot_exchange.py`, `market/impl/mixin.py` ×2) and the
  seven notebook cells above; `packages/impl/binance/pkg/.../market/perp_market.py`
  `one_mark_price` and its two call sites; bybit `instruments_paged` cannot be converted to
  `PaginatedResponse` until the union has an item type
- Suggestion (unverified): emit `@overload` per literal branch; collapse the `premium_index`
  duplicate into one TypedDict and overload on `symbol`

### Item-counted pagers refuse endpoints that declare `total` optional

The pagination redesign made the old silent one-page truncation loud: `next()` now poisons
the walk when `total` is absent and raises `LogicError` on the following page. An endpoint
whose response type declares `total: NotRequired[int]` therefore cannot be paged at all
when the venue omits it.

typed-binance `spot/http/bfusd/history/rate_history.py:36` and `:81-84`:

```python
  total: NotRequired[int]
      if total is None or (total_seen is not None and total != total_seen):
        total_poisoned = True
        total_poison_message = f'`rate_history_paged` needs a `total` on every page. ...'
```

- Kind: absent-under-condition
- Observed: asserted from the generated source and the declared type, not seen live
- Condition: a page without `total`
- Samples: `bfusd/history/rate_history.py`, `rwusd/history/rate_history.py`
- Blocks: nothing; `packages/impl/binance/pkg/.../earn/instruments.py` reads one row with
  `size=1` and never enters the pager
- Suggestion (unverified): page on row count and use `total` only as an extra bound when
  present

### Three pagers still return a bare `AsyncIterator` of page envelopes

The `PaginatedResponse[T, S]` upgrade left three pagers yielding whole page envelopes
through a bare `AsyncIterator`, with no per-page seam and no flattened rows.

typed-bybit `market/instruments.py:323`, typed-bit2me `v2/wallet/transactions.py:527`,
typed-binance `usdm_futures/http/market/funding_rate.py:54`:

```python
  ) -> AsyncIterator[Response]:
  ) -> AsyncIterator[ListWalletTransactionsV2Response]:
  ) -> AsyncIterator[Response]:
```

- Kind: missing-endpoint (paged variant with the pager contract)
- Observed: hand-rolled cursor loops needed
- Condition: always
- Blocks: `packages/impl/bybit/pkg/.../market/impl/mixin.py` `perp_instruments` cursor loop
  and `INSTRUMENTS_PAGE`; `packages/impl/binance/pkg/.../market/perp_market.py` `windows(...)`
  walk over `funding_rate` and `FUNDING_RATES_WINDOW`; nothing for bit2me v2 (the pkg walks v3)

## typed-core

### `IsoConverter.parse` raises a bare `AttributeError` on a non-string value

A non-nullable `TimestampIso` field fed a JSON `null` (or any non-string) escapes
validation as an `AttributeError` from `value.endswith('Z')` rather than a
`ValidationError`, because the `BeforeValidator` dies before pydantic can wrap it. `T |
None` fields are safe (the `None` branch wins first) and malformed strings are safe
(`fromisoformat` raises `ValueError`). The epoch and date converters share the shape:
`ms.py` calls `int(value)` unguarded, `date.py` calls `strptime` unguarded.

`public/typed/packages/core/src/typed_core/times/iso.py:26`:

```python
    if value.endswith('Z'):
```

- Kind: wrong-type
- Observed: `AttributeError: 'NoneType' object has no attribute 'endswith'`
- Condition: a non-nullable ISO field receiving `null`
- Samples: typed-coinbase `Product.new_at` before it was made nullable
  (`products.list_paged(FUTURE)` on the old client); no live trigger remains after that fix
- Blocks: nothing
- Suggestion (unverified): reject a non-`str` (non-`int | str` for the epoch converter)
  with `ValueError`, so the failure arrives as a `ValidationError`

### `IsoConverter` has no `tz` and yields a naive datetime for an offset-free string

Unlike `EpochConverter`, `IsoConverter` takes no timezone, so any ISO string without an
offset parses to `tzinfo=None`, and `dump` then silently treats the naive value as UTC.
typed-binance carries a client-local `NaiveUtcIsoConverter` subclass (`core/types.py:36`)
to re-attach UTC, a per-client patch for a shared gap; typed-kraken and typed-moralis pass
`tz` to their epoch converters and nothing to ISO.

`public/typed/packages/core/src/typed_core/times/iso.py:13-15` and `ms.py:12`:

```python
@dataclass(kw_only=True)
class IsoConverter(TimeConverter[str]):
  """Converter for RFC 3339 timestamps, always UTC and `Z`-suffixed on the wire."""
  tz: timezone | None = None
```

- Kind: wrong-type
- Observed: naive `datetime` for `'2026-09-04T16:00:00'`
- Condition: an ISO wire value without an offset or `Z`
- Blocks: typed-binance's `NaiveUtcIsoConverter` and
  `packages/impl/binance/pkg/.../util.py` `as_utc` with its use in
  `reporting/history/spot.py` (already a no-op behind the subclass; both go together)
- Suggestion (unverified): a `tz` parameter defaulting to UTC

### `ValidationError` carries no message

`validator.json`/`validator.python` re-raise pydantic's error as
`ValidationError(*e.args)`, but a pydantic v2 `ValidationError` has empty `args` (its
detail lives in `str(e)` and `e.errors()`), so every typed-core validation failure reads
`ValidationError()` and the field, path and offending value are only recoverable from
`__cause__`.

`public/typed/packages/core/src/typed_core/validation.py:36,43`:

```python
      raise ValidationError(*e.args) from e
```

- Kind: wrong-type (the exception's own contract)
- Observed: `tribulnation.sdk.core.exc.ValidationError: ValidationError()` from the
  hyperliquid snapshot above, with the 11-error detail visible only on `__cause__`
- Condition: every validation failure
- Blocks: nothing runs wrong, but every SDK impl that translates client errors
  (`packages/impl/*/core/exc.py`) forwards an empty message
- Suggestion (unverified): `ValidationError(str(e))`, or carry `e.errors()`

### `NetworkError` messages embed the full request URL, API key included

The HTTP transport interpolates the whole URL into the message, and the websocket one does
the same with its socket URL. Where a credential lives *in* the URL, it is then part of the
exception string, and travels wherever that string goes: a caller's own
`except NetworkError as e: print(e)`, a traceback, a crash reporter, any retry log. Two
clients put one there:

- typed-alchemy appends the app API key as the final path segment
  (`core/auth.py:39` `api_key_url`), so every Alchemy request and RPC URL carries it;
- typed-binance embeds a live `listenKey` in the private-stream socket path
  (`core/transport/ws/private_stream.py:78`, `url=f'{self.base_url}/{listen_key}'`), which
  is a session token for that account's private stream.

The rest are unaffected and worth stating so the blast radius is clear: typed-etherscan
attaches its key as a `params=` query entry (`core/rest.py:118`), which httpx adds after
the interpolated `url`, and typed-moralis sends an `X-API-Key` header
(`core/rest.py:38`). Neither reaches the message.

The transport is the one layer that knows which substring is the credential, so it is the
only one that can remove it without guessing at a pattern.

`public/typed/packages/core/src/typed_core/http.py:66-68`:

```python
    except httpx.HTTPError as e:
      req = f'{method} {url}'
      raise NetworkError(f'Error sending request to {req}', *e.args) from e
```

`public/typed/packages/core/src/typed_core/ws/socket.py:151`:

```python
        raise NetworkError(f'Failed to connect to {self.url}') from e
```

- Kind: wrong-type (the exception's message contract)
- Observed: `NetworkError('Error sending request to POST
  https://eth-mainnet.g.alchemy.invalid/v2/FAKE-KEY-abc123', '[Errno -2] Name or service
  not known')`, and `tribulnation.sdk.core.exc.translate_exception` forwards it verbatim
- Condition: every `httpx.HTTPError` raised against an Alchemy URL; the websocket site is
  the same construction, not separately triggered
- Samples: reproduced offline against an unroutable host with a fabricated key, so no live
  credential was involved; the URL shape is Alchemy's own
- Blocks: nothing runs wrong. `packages/sdk/test/test_sdk_retry.py`'s
  `test_default_retry_logger_excludes_call_arguments` documents the gap and drops the
  assertion that the sdk's retry log stays credential-free, since it cannot hold while the
  message carries one
- Suggestion (unverified): have the client hand its known credential values to the
  transport, and replace those exact substrings with `[REDACTED]` before building the
  message. An exact match on a known value, not a pattern; and a placeholder rather than a
  deletion, so the URL stays legible and a reader can see something was removed instead of
  wondering why the path looks truncated. Failing that, interpolate only the method and
  `scheme://host`, which loses little since the endpoint is clear from the call site

## typed-binance

### Signed USD-M futures types declare every field `NotRequired[str]`

`UsdMFuturesIncome` (8 fields), `UsdMFuturesAccountTrade` (17), `UsdMFuturesAccountV3Asset`
(13) and `UsdMFuturesAccountV3Position` (10) are entirely `NotRequired`, decimals as `str`,
while the public endpoints in the same namespace are required and `Decimal`.

`usdm_futures/http/trading/user_trades.py:39-49`:

```python
  price: NotRequired[str]
  qty: NotRequired[str]
  realizedPnl: NotRequired[str]
```

(also `usdm_futures/http/account/income.py:49-91`, `account_v3.py:7-59`)

- Kind: wrong-type
- Observed: unverifiable on this account (every signed USD-M call 401s: `enableFutures` is
  off and the account is geo-blocked from enabling it)
- Condition: none
- Samples: none
- Blocks: `packages/impl/binance/poc/market.ipynb` cells 17, 22–25 and
  `poc/reporting.ipynb` cells 4, 8 (`.get()` ladders, also not attempted for the 401);
  `packages/impl/binance/pkg/.../reporting/history/usdm.py:49-118,154-181` and
  `reporting/snapshots.py:104-126`

### Decimal-string fields declared `str`, inconsistently

Fields documented "as a decimal string" typed `str` beside converted siblings.

`spot/http/simple_earn/locked/list.py:22,30,34,43,45` (`apr`, `extraRewardAPR`,
`boostApr`, `totalPersonalQuota`, `minimum`);
`spot/http/staking/on_chain_yields/locked/list.py:22,35,37`;
`spot/http/bfusd/history/rate_history.py:12` and
`spot/http/rwusd/history/rate_history.py:25` (`annualPercentageRate: NotRequired[str]`);
`spot/http/wallet/asset/transfer/history.py:33` (`amount: str`);
`spot/http/simple_earn/flexible/position.py:12,16,26` and
`locked/position.py:20,30,32,36,42`; `spot/ws/account/my_trades.py:35-41`;
`usdm_futures/public_streams/partial_depth.py:25,27`:

```python
  b: list[tuple[str, str]]
  a: list[tuple[str, str]]
```

- Kind: wrong-type
- Observed: decimal strings on the wire (earn cells 3, 5, 6, 7 and market cell 14 ran live)
- Condition: none
- Samples: `apr='0.0432'` shapes throughout
- Blocks: `packages/impl/binance/poc/earn.ipynb` cells 3, 5, 6, 7, `poc/reporting.ipynb`
  cells 10, 13, `poc/market.ipynb` cell 14 (`Decimal(...)` wrappers);
  `packages/impl/binance/pkg/.../earn/instruments.py`, `reporting/snapshots.py`,
  `reporting/history/spot.py:221`, `market/perp_market.py:141-142`

### `funding_rate_paged` still returns a bare `AsyncIterator[Response]`

Now a window walker (`allow_truncation`, `LogicError` on a capped window) but not a
`PaginatedResponse`.

`usdm_futures/http/market/funding_rate.py:54`:

```python
  ) -> AsyncIterator[Response]:
```

- Kind: missing-endpoint (pager shape)
- Blocks: `packages/impl/binance/pkg/.../market/perp_market.py:183-198` hand `windows()`
  walk and `FUNDING_RATES_WINDOW` (`:55`); `poc/market.ipynb` cell 21 is a single call

### `capital.deposit.history`, `capital.withdraw.history` and `usdm_futures.account.income` have no `*_paged` helper

`spot/http/wallet/capital/deposit/history.py:72`, `withdraw/history.py:72` (declares
`offset`/`limit`), `usdm_futures/http/account/income.py:101`: no `_paged` symbol in any.

- Kind: missing-endpoint
- Blocks: `packages/impl/binance/pkg/.../reporting/history/spot.py:130-158,169-200` and
  `usdm.py:192-208` hand loops with `CAPITAL_PAGE_SIZE`/`PAGE_SIZE`

### `WithdrawRecord.network` is required but documented absent on old withdrawals

`spot/http/wallet/capital/withdraw/history.py:48-49`:

```python
  network: str
  """Network the withdrawal was sent over. May be absent for old withdrawals predating network support."""
```

- Kind: absent-under-condition
- Observed: not reproduced (no withdrawals on this account in the 30-day window)
- Condition: withdrawals predating network support, per the docstring
- Samples: none
- Blocks: `packages/impl/binance/poc/reporting.ipynb` cell 7 and
  `packages/impl/binance/pkg/.../reporting/history/spot.py:190` (`.get('network') or None`)

## typed-bit2me

### `WalletResponse.balance`/`blockedBalance` are `float`

`v1/trading/balance`, `v1/trading/wallets/request_{deposit,withdrawal}` and the
`my-balance` stream carry balances as `float`, while the same concept is `Decimal` at
`schemas.py:291,304,:51` and `v1/wallet/pockets/get.py:23,25`.

`schemas.py:277-280`:

```python
  balance: float
  """Balance available"""
  blockedBalance: float
  """Balance in use on active orders"""
```

(`trading_ws/my_balance.py:12,14` repeat it.)

- Kind: wrong-type
- Observed: values reach the SDK only as `Decimal(str(float))`, e.g.
  `Decimal('0.00769999')`, `Decimal('1E-7')`; the wire's exact digits are not recoverable
- Condition: always
- Samples: `packages/impl/bit2me/poc/market.ipynb` cells 9–10, `poc/reporting.ipynb` cells
  2, 4
- Blocks: those cells (re-run to drop the transcription);
  `packages/impl/bit2me/pkg/.../market/impl/position.py:19,29-30`,
  `report/snapshots.py:40-42,67-69`
- Suggestion (unverified): `Decimal`

### Monetary, quantity and count fields are `float` across `schemas.py`, `v1/trading/markets.py`, `trading_ws/my_trades.py` and the Earn tables

`schemas.py:211` `TradeResponse`: `price` 222, `amount` 224, `cost` 234, `costEuro` 236,
`feeAmount` 240, `feePercentage` 242. `schemas.py:114` `OrderResponse` mixes them at
`:129/:131`:

```python
  amount: NotRequired[Decimal]
  filledAmount: NotRequired[float]
```

(`price` 127, `stopPrice` 128, `orderAmount` 130, `dustAmount` 133, `feeAmount` 135,
`cost` 143 also `float`.) `v1/trading/markets.py:12-32` `Entry` (`minAmount` through
`initialPrice`, with `pricePrecision`/`amountPrecision` being decimal-place counts).
`trading_ws/my_trades.py:19,23,39,41,43`. `v2/earn/apy.py:7,9,11`,
`v2/earn/assets.py:11,13,15`. `v1/earn/wallets/list_movements.py:11`
`value: NotRequired[float]` vs `schemas.py:33` `str` vs `:51,:333` `Decimal`. Counts:
`v1/trading/trades/list.py:15`, `v1/wallet/transactions/list.py:146`. `limit` params:
`v1/trading/candles.py:16,33`, `v1/trading/orders/list.py:36,63`,
`v1/trading/trades/list.py:28,51`. `v2/wallet/transactions.py:63`,
`v3/wallet/transactions.py:74` `TransactionBenefit.amount`. `types.py` is still an
unreferenced duplicate of `schemas.py`.

- Kind: wrong-type
- Observed: `rules` output `max_qty=Decimal('20.0')`, `fixed_min_price=Decimal('9000.0')`,
  `step_size=Decimal('1E-8')` (from `-int(amountPrecision)`); tickers
  `last=Decimal('68487.8')`
- Condition: always
- Samples: `packages/impl/bit2me/poc/market.ipynb` cells 4–8, `poc/reporting.ipynb` cells
  7–10, `poc/earn.ipynb` cell 2
- Blocks: those cells; `packages/impl/bit2me/pkg/.../market/spot_exchange.py`
  `parse_ticker`, `market/impl/rules.py:34-41`, `market/impl/orders.py:33-35`,
  `market/impl/trades.py:23-50,76`, `report/history/trades.py:22-35,68`,
  `report/history/earn.py:43`, `report/history/transactions.py:37,54,81`,
  `earn/instruments.py:46`
- Suggestion (unverified): `Decimal` for money and quantities, `int` for precisions, counts
  and `limit`

### `OrderBookUpdate.bids`/`asks` still admit only 2-element rows

`trading_ws/order_book.py:21,23`:

```python
  bids: list[tuple[float, float]]
  asks: list[tuple[float, float]]
```

against REST `v2/trading/order_book.py:13,15`, which accepts
`tuple[float, float] | tuple[float, float, float]`.

- Kind: wrong-type
- Observed: thin and stablecoin pairs send `[price, amount, notional]` (`B2M/EUR`,
  `HTX/USDC`, `BTC/EURCV`; 26 of 290 when last counted)
- Condition: market-dependent, same markets over REST and WS
- Samples: `packages/impl/bit2me/poc/market.ipynb` cell 3 ran clean only because it
  subscribed to `BTC/EUR`
- Blocks: `poc/market.ipynb` cell 3 (unpacks `for p, q in ...`; re-run against a triple
  market once fixed); `packages/impl/bit2me/pkg/.../market/impl/depth.py:15` `Level` alias,
  deletable then
- Suggestion (unverified): the REST union on both fields

### The proforma's `not-enough-funds` error body, which carries the withdrawal fee, is untyped

`POST /v1/wallet/transaction/proforma` is the only place Bit2Me publishes a withdrawal
fee, and on a `412 not-enough-funds` it is only in the error body, which reaches callers
as `ApiError.args[1]` typed `Any`.

`core/exc.py:46`:

```python
  payload: Any
```

raised at `:53-59` as `ApiError(status, payload)`; `v1/wallet/transactions/preview.py`
types only the success body.

- Kind: missing-endpoint (typed error body)
- Observed: `{'data': {'data': {'code': 'not-enough-funds', 'fee': '0.00000300', ...}}}`
  for BTC; `'0.00020000'` ETH, `'0.50000000'` USDT, `'0.00200000'` SOL, on all 19
  asset/network pairs tried
- Condition: always on an under-funded proforma
- Samples: `packages/impl/bit2me/poc/wallet.ipynb` cell 3
- Blocks: `poc/wallet.ipynb` cell 3;
  `packages/impl/bit2me/pkg/.../wallet/withdrawal_methods.py:95-105`
- Suggestion (unverified): declare the proforma error body and expose it on the raised error

## typed-bitget

### `MixTradeSide` is still `Literal['open', 'close']` on four response types

`classic.mix.order.fills` and `order.detail` were widened inline; the shared alias and the
four other responses referencing it were not. A one-way-mode account sends
`'buy_single'`/`'sell_single'`.

`schemas.py:423`:

```python
MixTradeSide = Literal['open', 'close']
```

Also `classic/mix/order/open.py:53`, `classic/mix/order/fill_history.py:44`,
`classic/mix/order/history.py:52`, `classic/mix/order/plan/open.py:50`
(`tradeSide: MixTradeSide`).

- Kind: missing-literal
- Observed: `'buy_single'` / `'sell_single'` on `classic.mix.order.fills` for this
  account's BTCUSDT USDT-FUTURES fills (the inline-widened endpoint); the four alias users
  are inferred, not yet observed
- Condition: `posMode == 'one_way_mode'`; hedge mode sends `open`/`close`
- Samples: this account is one-way; `order.open` returned no rows, so
  `packages/impl/bitget/poc/market/classic.ipynb` cell 12 (`perp_open_orders`) validates
  only vacuously
- Blocks: nothing failing today; `poc/market/classic.ipynb` cell 12 would fail on a
  one-way account with an open order
- Suggestion (unverified): widen the alias, drop the two inline copies

### `MixAccountAssetSummary.crossedUnrealizedPL`/`isolatedUnrealizedPL` are `str`

Fixed to `Literal[''] | Decimal` on `MixAccountAsset` (`get.py:35,37`) and left `str` on
the list variant, so a real value arrives unparsed.

`classic/mix/account/list.py:44,46`:

```python
  crossedUnrealizedPL: str
  isolatedUnrealizedPL: str
```

- Kind: wrong-type
- Observed: `''` or a decimal string, per `marginMode`, same as the singular type
- Condition: `''` when the symbol's active `marginMode` is the other one
- Samples: this account's USDT-FUTURES rows
- Blocks: nothing; neither the notebooks nor `pkg/` read these fields

## typed-bybit

### `tickers`/`instruments` return an undiscriminated category union

`market.tickers(category=...)` and `market.instruments(category=...)` take a
`Literal['spot', 'linear', 'inverse', 'option']` and return the full three-way union
regardless, so every caller narrows by hand on `category`. This is the codegen entry on
discriminated endpoints, seen from bybit; it also keeps `instruments_paged` from being
converted to `PaginatedResponse`.

`market/tickers.py:201`, `market/instruments.py:306`:

```python
Response = SpotTickers | ContractTickers | OptionTickers
Response = SpotInstrumentsInfo | ContractInstrumentsInfo | OptionInstrumentsInfo
```

- Kind: wrong-type
- Observed: a `'linear'` call is typed as possibly `SpotTickers`; no runtime failure
- Condition: always
- Samples: `packages/impl/bybit/poc/market.ipynb` cells 4, 8, 9, 15, 19, 20, 25
- Blocks: the six `assert ...['category'] == ...` narrowings in `packages/impl/bybit/pkg`
  (`market/perp_exchange.py`, `market/perp_market.py` ×2, `market/spot_exchange.py`,
  `market/impl/mixin.py` ×2) and the seven notebook cells above, to re-run after dropping
  the asserts
- Suggestion (unverified): emit `@overload` per `category` literal

### `ExecutionUpdate` declares as `str` what REST `Execution` declares as `Decimal`

The private `execution` stream types fourteen numeric fields `str` where
`trade.trade_history`'s `Execution` types them `Decimal`; `extraFees` is structurally
different on the two sides.

`private/execution.py:63,67,69,109,111` vs `trade/trade_history.py:83,89,91,129,133`:

```python
  execFee: str
  execPrice: str
  execQty: str
  closedSize: str
  extraFees: NotRequired[list[ExtraFee]]
```

- Kind: wrong-type
- Observed: wire strings; `Decimal(...)` applied by hand
- Condition: always, stream side only
- Samples: no live fill observed on this account (stream timed out); REST side confirmed
  `Decimal`
- Blocks: `packages/impl/bybit/poc/market.ipynb` cell 7 (`trades_stream`);
  `packages/impl/bybit/pkg/.../market/impl/parse.py` `parse_execution_update`, which exists
  only to re-parse the stream's strings and merges into `parse_execution`
- Suggestion (unverified): converge the stream type on the REST `Execution`

### Numeric fields declared `str` inconsistently within one response type

`ContractTicker` converts `indexPrice` and leaves `lastPrice`, `markPrice`, `bid1Price`,
`bid1Size`, `ask1Price`, `ask1Size`, `volume24h`, `openInterest` and eighteen siblings
`str`; `SpotTicker` and `OptionTicker` are `str` throughout; `Position.size` was missed
while its neighbours became `Literal[''] | Decimal`; `coin_info.confirmation` is a count
typed `str`; `product_info.minStakeAmount`/`maxStakeAmount` are `str`.

`market/tickers.py:13,17`, `position/list.py:22`, `asset/coin_info.py:14`,
`finance/easy_onchain/product_info.py:34,36`:

```python
  lastPrice: str
  markPrice: str
  size: str
  confirmation: str
  minStakeAmount: str
```

- Kind: wrong-type
- Observed: decimal strings on the wire, e.g. `size='0'` on a flat BTCUSDT position
- Condition: always
- Samples: `packages/impl/bybit/poc/market.ipynb` cell 23, `poc/wallet.ipynb` withdrawal
  chains
- Blocks: `poc/market.ipynb` cells 19, 20, 23 and the `Decimal(...)`/`int(...)` wraps in
  `poc/earn.ipynb` and `poc/wallet.ipynb`; in `pkg`, the twelve `num()` ticker reads
  (`market/perp_exchange.py`, `market/perp_market.py`), `earn/instruments.py:104-105`,
  `wallet/deposit_methods.py:41,47`, the `Decimal(...)` wrappers in `reporting/history.py`,
  `market/impl/history.py`, `reporting/snapshots.py`. `num()` itself stays: its
  `''`-to-zero half is venue behaviour

### `instruments_paged` yields page envelopes through a bare `AsyncIterator`

The last bybit pager not converted to `PaginatedResponse`, because the category union
above has no single item type.

`market/instruments.py:323`:

```python
  ) -> AsyncIterator[Response]:
```

- Kind: missing-endpoint (paged variant with the pager contract)
- Observed: hand-rolled `nextPageCursor` loop needed
- Condition: always
- Blocks: `packages/impl/bybit/pkg/.../market/impl/mixin.py` `perp_instruments` cursor loop
  and `INSTRUMENTS_PAGE`

### `funding_history_paged` refuses open bounds

The rewrite fixed the fixed-width window, the full-chunk raise and the overshoot, but the
pager still requires both bounds, while the SDK's `funding_rates(start=None, end=None)`
allows either to be open.

`market/funding_history.py:75`:

```python
    if start_time is None or end_time is None:
      raise ValueError(
```

- Kind: missing-endpoint (contract gap)
- Observed: `ValueError` on `start_time=None`
- Condition: either bound `None`
- Blocks: `packages/impl/bybit/pkg/.../market/impl/history.py` `funding_rates` and
  `FUNDING_PAGE` keep their own walk; `poc/market.ipynb` cell 21 calls the unpaged endpoint

### `parse_msg` drops the order-book frame's `snapshot`/`delta` type

The frame's `type` never reaches `OrderbookUpdate`, so a consumer cannot distinguish a
re-snapshot from a delta; `u == 1` is the only substitute and also fires on
mid-subscription re-snapshots.

`core/ws.py:280`, `spot/orderbook.py:8-17`, `linear/orderbook.py:8-17`:

```python
    return Subscription(channel=frame['topic'], notification=frame.get('data', frame))
```

- Kind: absent-under-condition (field dropped by the transport)
- Observed: no `type` key on any pushed update
- Condition: always
- Samples: `packages/impl/bybit/poc/market.ipynb` cells 3 and 14 (three pushes each)
- Blocks: `packages/impl/bybit/pkg/.../market/impl/mixin.py:75-78` `u == 1` test (becomes
  `update['type'] == 'snapshot'`, a correctness fix); `poc/market.ipynb` cells 3 and 14
  merge every push as a delta
- Suggestion (unverified): forward `frame['type']` and declare it on both update types

### `ContractTicker.deliveryTime` parses the perpetual sentinel into 1970

`market/tickers.py:55`:

```python
  deliveryTime: NotRequired[TimestampMillis]
```

- Kind: missing-literal (sentinel)
- Observed: per the field's own docstring, `0` on perpetuals; not recorded live
- Condition: perpetual contracts
- Samples: none recorded; nothing here reads the field
- Blocks: nothing
- Suggestion (unverified): `Literal[0] | TimestampMillis`, matching `fundingRate` and
  `nextFundingTime`

## typed-coinbase

### `Product.future_product_details` is an untyped `dict[str, Any]`

The only place Coinbase publishes an INTX perpetual's index price, funding rate, funding
time, funding interval and open interest is declared opaque, though the venue sends a
structured object (`perpetual_details.{funding_rate,funding_time,open_interest}`,
`index_price`, `funding_interval: '3600s'`, `contract_code`). `contract_expiry` and
`intraday_margin_rate` come back `null`.

`schemas.py:2024`:

```python
  future_product_details: NotRequired[dict[str, Any]]
```

- Kind: wrong-type
- Observed: a structured object on all three `*-PERP-INTX` products, live
- Condition: `product_type == 'FUTURE'`
- Samples: BTC-PERP-INTX, ETH-PERP-INTX, SOL-PERP-INTX
- Blocks: `packages/impl/coinbase/poc/market.ipynb` cells 15 (`perp_rules`,
  `contract_code`), 19 (`index`), 20 (`next_funding`);
  `packages/impl/coinbase/pkg/.../market/impl/{funding,rules,catalogue}.py` read it through
  `dict[str, Any]`
- Suggestion (unverified): a `FutureProductDetails` TypedDict with `perpetual_details`
  nested and the two nullable fields `| None`

### Every field of `Fill` is `NotRequired`

All nineteen fields of the historical-fills row are optional (`FillFutureLeg` likewise),
so nothing can be read without a guard.

`app/advanced_trade/http/orders/historical/fills.py:103-134`:

```python
  trade_time: NotRequired[TimestampIso]
  price: NotRequired[Decimal]
  size: NotRequired[Decimal]
```

- Kind: wrong-type (over-optional)
- Observed: every fill carries all nineteen keys (2 fills, 19/19 keys present in each)
- Condition: none seen
- Samples: two SPOT fills on this account, the whole live history; too thin to narrow on
- Blocks: `packages/impl/coinbase/poc/market.ipynb` cells 6, 17 and `poc/reporting.ipynb`
  cell 2; `packages/impl/coinbase/pkg/.../market/impl/trades.py:16-40` and
  `reporting/history.py:89-116` carry `.get()` guards and `| None` returns
- Suggestion (unverified): make the nine core fields required after a wider capture

### `ExchangeWrappedAsset.apy` and `redeem_time_estimate_days` are `str`

Two decimal-string fields sit `str` beside three `Decimal` siblings (`circulating_supply`,
`total_supply`, `conversion_rate`).

`schemas.py:1248,1250`:

```python
  apy: str
  redeem_time_estimate_days: str
```

- Kind: wrong-type
- Observed: `'0.0237'` and `'9.03'` on CBETH, live; the docstring says empty string when
  unavailable
- Condition: none
- Samples: CBETH (the only wrapped asset listed)
- Blocks: `packages/impl/coinbase/poc/earn.ipynb` cell 4 and
  `packages/impl/coinbase/pkg/.../earn/instruments.py:84` convert with `Decimal(...)`
- Suggestion (unverified): `Decimal | Literal['']`

## typed-deribit

### `BookSummary.open_interest` is required and absent on spot

The response element of `get_book_summary_by_currency` and
`get_book_summary_by_instrument`, both of which accept spot instruments, requires a field
its own docstring calls derivatives-only. The neighbouring `OrderBookSnapshot.open_interest`,
`Ticker.open_interest` and `BookSummary.estimated_delivery_price` were all made
`NotRequired`; this one was missed.

`schemas.py:240`:

```python
  open_interest: float
  """Optional (only for derivatives). The total amount of outstanding contracts ..."""
```

- Kind: absent-under-condition
- Observed: field omitted
- Condition: `kind == 'spot'`
- Samples: omission confirmed live on all 19 active spot instruments through
  `get_order_book` before that schema was fixed; not yet observed through
  `get_book_summary_*` specifically
- Blocks: nothing; no notebook or package calls `get_book_summary_*`

### `InstrumentInfo.base_currency`/`quote_currency`/`price_index` are `str` while their consumers take `Literal`s

`get_instrument` returns plain `str` for these, but `account.get_account_summary(currency=)`,
`account.get_positions(currency=)` and `market_data.get_index_price(index_name=)` declare
closed `Literal` parameters, so a value read from one endpoint cannot be passed to the
next without a cast.

`schemas.py:1252-1256`:

```python
  base_currency: str
  """The underlying currency being traded."""
  quote_currency: str
  """The currency in which the instrument prices are quoted."""
```

(and `price_index: str` on the same class)

- Kind: wrong-type (producer looser than its consumers)
- Observed: values are always members of the consumers' Literals in practice
- Condition: always
- Samples: `packages/impl/deribit/poc/market.ipynb` cell 1 defines
  `AccountCurrency`/`PositionsCurrency`/`IndexName` aliases copied from the consumers'
  signatures and casts into them
- Blocks: the `cast(...)` bridges in `packages/impl/deribit/poc/market.ipynb` cells 8, 9,
  19, 24 and `poc/reporting.ipynb` cell 3
- Suggestion (unverified): declare the instrument fields as the same Literals, or accept
  `str` on the three consumers

## typed-dydx

### Stream subscription replies are validated with the channel's notification type

`StreamsMixin.subscribe` takes one `response_type` and applies it to the subscription
reply and to pushed messages; for `v4_orderbook` the reply is `{"price","size"}` objects
and the notifications are `[price, size]` tuples, so entering the stream raises before
the first message. `block_height`, `candles` and `trades` have the same incompatible
split; `subaccounts`, `parent_subaccounts` and `markets` validate silently to `{}`. The
`*ReplyContents` types already exist in `indexer/schemas.py` and are unreferenced.

`indexer/streams/core.py:310`:

```python
        validator(cast(type, response_type)).python(reply_contents)
```

- Kind: wrong-type
- Observed: `ValidationError` (`tuple_type`) on the `v4_orderbook` reply, live on testnet
- Condition: always
- Samples: `packages/impl/dydx/poc/market.ipynb` `depth_stream('BTC-USD')`
- Blocks: `packages/impl/dydx/poc/market.ipynb` cell 10 (`depth_stream`);
  `packages/impl/dydx/pkg/.../market/impl/depth.py` `depth_stream` is written against the
  real split and raises at runtime today
- Suggestion (unverified): add `reply_type`, wire each channel's `*ReplyContents`,
  parameterize `StreamManager`'s second argument

### `Data` omits three endpoint mixins from its bases

`GetMarkets`, `ListPositions` and `GetFundingPaymentsForParentSubaccount` are reachable
only transitively through another mixin's base.

`indexer/data/__init__.py:39-73` (bases list; none of the three listed)

- Kind: missing-endpoint (latent: works today through inheritance)
- Blocks: nothing; `packages/impl/dydx/pkg/.../market/impl/mixin.py:63` calls
  `get_markets()` through the transitive base

### `TimeResponse.epoch` is a bare `float`

`indexer/schemas.py:496-497`:

```python
class TimeResponse(TypedDict):
  epoch: float
```

- Kind: wrong-type
- Blocks: nothing

## typed-etherscan

### `erc20_transfers_paged`/`erc721_transfers_paged` require `contractaddress`

Etherscan's `tokentx` and `tokennfttx` accept an address without a contract filter and
then return every token transfer for that address, which is what a history feed needs
(docs: https://docs.etherscan.io/api-endpoints/accounts#get-a-list-of-erc20-token-transfer-events-by-address).
The generated client makes `contractaddress` required on both, so an account-wide token
feed cannot be requested through the typed endpoint at all. This is a regression: the
hand-written client before the 2026-08-21 regeneration (`ccd695a10`, "impl: build codegen
backend, regenerate package, rebuild core, add tests") took no contract parameter.

`api/account/token_transactions.py:78-84` at `ccd695a10^`:

```python
  def token_transactions_paged(
    self, address: str, chain_id: int = 1, *,
    start_block: int = 0,
    end_block: int = 99999999,
    offset: int = 20,
    validate: bool | None = None,
  ) -> PaginatedResponse[TokenTransaction, int]:
```

(`api/account/nft_transactions.py:81-89` likewise, with `contract_address: str | None = None`.)

`account/erc20_transfers.py:93-101` now, same in `account/erc721_transfers.py:42`:

```python
  def erc20_transfers_paged(
    self,
    *,
    chainid: str | None = None,
    module: Literal['account'] = 'account',
    action: Literal['tokentx'] = 'tokentx',
    address: str,
    contractaddress: str,
```

- Kind: missing-endpoint (regression: parameter made required on regeneration)
- Observed: the endpoint cannot be called without a contract; omitting the parameter on
  the wire returned 246 `tokentx` rows for the test address on Arbitrum, and
  `contractaddress=''` returns `status='0'`, `message='NOTOK'`
- Condition: always
- Samples: `packages/impl/ethereum/poc/reporting/history/etherscan.ipynb`
- Blocks: `packages/impl/ethereum/pkg/.../reporting/history/etherscan.py`
  `token_transactions`/`nft_transactions` raise, so `EtherscanHistory.history()` raises
  (a history without token legs would be wrong, not partial); the notebook's
  `token_transfers`/`nft_transfers` (cell 4) raise and cells 13–15 (NFT, zero-decimal and
  inbound-ERC-20 samples) are not executed; re-run cells 1–18 once fixed
- Suggestion (unverified): remove `contractaddress` from `required` in
  `clients/etherscan/spec/endpoints/account/erc20_transfers/endpoint.json` and the
  erc721 twin

### Every field of every account feed row is `NotRequired[Any]`

`AccountTransaction`, `Erc20Transfer` and `InternalTransaction` declare all of their
fields `NotRequired[Any]` (`hash`, `timeStamp`, `value`, `isError`, `tokenDecimal`, ...),
and `erc721_transfers` has no row model at all (`list[dict[str, Any]]`). Etherscan sends
every field on every row, and the request side of the same client already resolves
formats (`blocks.number_by_time`'s `timestamp` is a `TimestampSeconds`), so the response
side loses what the client knows how to describe.

`account/transactions.py:15-54`:

```python
class AccountTransaction(AccountTransactionKeywords):
  blockNumber: NotRequired[Any]
  timeStamp: NotRequired[Any]
  hash: NotRequired[Any]
```

- Kind: wrong-type (over-optional and untyped)
- Observed: every row carries every field, as decimal strings (`timeStamp` is epoch
  seconds)
- Condition: none
- Samples: the full Arbitrum history of the test address in
  `packages/impl/ethereum/poc/reporting/history/etherscan.ipynb`
- Blocks: the `required()` adapter in that notebook (cell 5) and in
  `packages/impl/ethereum/pkg/.../reporting/history/etherscan.py`, plus its `block_time`
  parse of `timeStamp`
- Suggestion (unverified): required fields with real types; `timeStamp` as
  `TimestampSeconds`; a row model for `erc721_transfers`

## typed-ethereum

### `NodeRpcMixin.w3` is an unparameterized `AsyncWeb3`

`core/mixin.py:40`:

```python
  w3: AsyncWeb3
```

- Kind: wrong-type (missing type argument)
- Observed: every consumer of `.w3` is `AsyncWeb3[Unknown]` under the no-implicit-Any rules
- Condition: always
- Blocks: the 11 remaining pyright errors in `packages/impl/ethereum/pkg`
  (`core/rpc/{mixin,block_time}.py`, `reporting/history/mixin.py`)
- Suggestion (unverified): `AsyncWeb3[AsyncHTTPProvider]`, or a `TProvider` type variable on
  the mixin

## typed-hyperliquid

### `AssetPosition.liquidationPx` is `null` on positions that cannot be liquidated

`clearinghouse_state` sends `liquidationPx: null` for a position with no liquidation
price, which the required `Decimal` rejects and takes the whole account state down with
it.

`info/clearinghouse_state.py:82`:

```python
  liquidationPx: Decimal
  """Estimated liquidation price for the position."""
```

- Kind: absent-under-condition
- Observed: `null` on all 11 open positions of the test address on mainnet (`11 validation
  errors for ClearinghouseState ... assetPositions.N.position.liquidationPx ...
  input_value=None`)
- Condition: a position the venue reports no liquidation price for; the exact rule is
  not confirmed (the same address's testnet positions carry a number)
- Samples: the test address, mainnet, 2026-09-06
- Blocks: `Report.snapshot()` in `packages/impl/hyperliquid` on any account with such a
  position (the failure surfaced through `sdk-dev catalogue coverage report`)
- Suggestion (unverified): `Decimal | None`

### Exchange action responses declare `status` and `response` as independent fields

`PlaceOrderResponse`, `CancelResponse`, `CancelByCloidResponse` and `BatchModifyResponse`
declare `status: Literal['ok', 'err']` beside `response: <Result> | str`, so checking
`status` narrows nothing; `exchange/core/envelope.py`'s `ExchangeResponse[T]` models it
correctly and is unused.

`exchange/order.py:142-144`:

```python
  status: Literal['ok', 'err']
  response: OrderActionResult | str
```

- Kind: wrong-type
- Blocks: `packages/impl/hyperliquid/pkg/.../market/impl/orders.py` hand-checks `status`
  then indexes `response` in `place_order` and `cancel_order`; `raise_on_error` from the
  envelope module replaces both once the responses use it

## typed-mexc

### `OrderDeal` declares two spellings of the taker flag, with inverted requiredness across endpoints

`futures/http/trade/order_deals.py:28-30`:

```python
  isTaker: bool
  taker: NotRequired[bool]
```

`futures/http/trade/deal_details.py:28-30` swaps the requiredness;
`futures/streams/user/my_trades.py:33` declares only `taker`.

- Kind: absent-under-condition (which name the wire carries is undetermined)
- Samples: none; the test key lacks futures read scope (`703`)
- Blocks: `packages/impl/mexc/poc/market.ipynb` cell 17 (`perp_trades_history`)

### Futures timestamps are declared `int | str` in three modules

`futures/http/trade/order_deals.py:24`:

```python
  timestamp: int | str
```

Also `stop_orders.py:55,57` and `plan_orders.py:40,42` (`createTime`/`updateTime`);
`spot/http/rebate/affiliate_commission.py:29` `firstDepositTime: str | None`.

- Kind: wrong-type
- Blocks: `packages/impl/mexc/poc/market.ipynb` cell 17 (`perp_trades_history`)
