# Typed client issues

Open defects in the `typed_*` clients and in the generator that produces them, found by
running the PoC scripts under `packages/impl/*/poc/` against the live venues. This file
is the hand-over from the sdk repo to typed-dev: it is meant to be read there without
anything else from here.

This is round two. The first report's 42 entries were answered in typed-dev's
`sdk-issues` branch, now merged to its `main`, and every answer was re-verified here
against the merged client. What follows is what is left: the entries that stayed open, the
defects the fix pass introduced, and what we found while checking. `typed-client-issues-reply.md`
holds typed-dev's own answers, entry for entry.

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
  `Observed` says the endpoint could not be reached was verified against the declaration
  only; read it as "the declared type looks wrong", not "seen on the wire";
- `Blocks`: the script cells and `pkg/` code on the sdk side that wait on the fix;
- `Suggestion`, when present: unverified, and never acted on in the PoC.

The file records what the venue sent, not what the type should be. Whether a field
becomes optional, a union or a wider literal is typed-dev's decision, which is why entries
carry `Condition` and `Samples` rather than a fix.

## The round trip

1. typed-dev fixes and releases. It does not edit this file; disagreement with an entry
   goes in typed-dev's own commit message or docs.
2. The sdk side re-runs the cells named under `Blocks` against the released client. When
   they pass, the entry is deleted, not marked fixed; git history is the record.
3. New entries are added only from a PoC that hit the defect live, in the format above.
   The rules are in `.agents/skills/sdk-poc/SKILL.md`.

Round one taught us a fourth step: **re-verify the answers, do not just read them.** Doing
that caught three claims in the reply that did not hold, three mistakes of our own, and
two regressions the fix pass introduced. All six are below.

## Priority

By what a fix unblocks on the sdk side, most first, except that a defect leaking
credentials comes first regardless:

1. typed-core `NetworkError` messages embed the request URL: an Alchemy API key, or a
   Binance private-stream `listenKey`, reaches every log, traceback and crash report a
   consumer keeps. Being fixed as this was written.
2. typed-bybit `coin_info.confirmation` is `''` when a chain has deposits disabled: a
   **regression from this fix pass** that takes out the whole bybit wallet surface.
3. typed-bybit `SpotTicker.ask1Price`/`ask1Size` reject the empty-string sentinel their
   own bid twins accept: a **regression from this fix pass**; `tickers(category='spot')`
   fails against the live venue today.
4. typed-bitget `MixTradeSide` against the stream's own 22-value vocabulary: a liquidated
   or auto-deleveraged close would reject a whole page of mix fills.
5. typed-deribit `get_index_price`'s `index_name` literal against 344 real index names,
   flagged in the reply but not acted on.
6. typed-dydx stream replies are unvalidated rather than typed: the workaround unblocks
   us, the `*ReplyContents` types are generated and unused.
7. Everything else is typing quality; nothing shipped is wrong because of it.

## Environment

- typed-dev `main` @ `81b2acd89` (the `sdk-issues` merge, PR #175). The sdk venv installs
  every `typed_*` client editable from `clients/<venue>/pkg` in that checkout, plus
  typed-core from `public/typed/packages/core`, so what lands there is what the PoCs run
  against immediately.
- **typed-core is 0.8.0 and no client version moved.** binance is still 2.0.0, bit2me
  0.4.0, bitget 0.4.0, bybit 0.3.0, coinbase 0.4.0, deribit 0.3.0, dydx 4.0.0,
  etherscan 0.4.0, hyperliquid 3.0.0, mexc 3.0.0, alchemy 3.0.0, moralis 0.3.0 -- the same
  numbers as before the pass, on materially different behaviour and, in bit2me's case, a
  removed public module. The impls floor exactly those numbers, so a release resolving
  against PyPI would pick up the unfixed clients. Each touched client needs a bump before
  anything ships.

## Corrections to the previous report

Ours, found while re-verifying. Recorded so the same claims do not come back:

- **`as_utc` never existed in this repo.** The `IsoConverter` `tz` entry's `Blocks` line
  named `packages/impl/binance/pkg/.../util.py` `as_utc` as a helper that would retire
  with the fix. There is no such function and there never was; the entry should have named
  only typed-binance's own `NaiveUtcIsoConverter`, which is indeed gone.
- **The deribit `InstrumentInfo` entry had it backwards.** We reported the producer as too
  loose. typed-dev's probe of 5,550 live instruments found 44 distinct `base_currency`
  values, 41 outside our five-value literal, and 54 distinct `price_index` values. The
  producer is right; the consumers are too narrow. What survives is the consumer half,
  below.
- **`typed_bit2me.types` was not unreferenced.** The reply deleted it on that basis, and
  our own `poc/market.py` imported `OrderSide` from it. Our side moved to
  `typed_bit2me.schemas`; the process point is in the accepted-limitations section.

And four in the reply, none of them consequential, each checked here:

- `Erc721Transfer`'s requiredness is described as resting on documentation because both
  captures were empty. All 14 live `tokennfttx` rows carried every one of its 21 required
  fields, so it is confirmed on the wire now.
- Coinbase's CDE `perpetual_details` is described as "empty on every CDE contract"; after
  validation the key is **absent** on all 100. And on all 131 INTX perpetuals the nested
  and parent funding values are identical, so reading the nested copy was latently wrong
  rather than wrong in production.
- The reply says undeclared keys like `option_legs` "will be visible through the tolerant
  base". Not for typed-coinbase: its generated modules import
  `typing_extensions.TypedDict`, so pydantic drops undeclared keys at validation.
- binance's `locked/position` day counts are described as left alone as counts. They were
  never `int`; they are still numeric `str`.

## Accepted, not defects

Closed by typed-dev with reasoning we accept. Listed so a later PoC does not re-file them:

- **`validate=False` contradicts the declared return type**, and **discriminated endpoints
  return an undiscriminated union**. Both need `@overload` generation across roughly 2,900
  methods. Our own rules forbid `validate=False`, and the `assert` narrowings on bybit's
  category unions are cheap. Raise as a design request with an ADR if a raw-read consumer
  ever appears.
- **bit2me's JSON-number money fields stay `float`.** We re-tested the argument rather than
  accepting it: on pydantic 2.13.5,
  `TypeAdapter(Decimal).validate_json(b'0.1234567890123456789')` gives
  `Decimal('0.12345678901234568')`, bit-identical to `Decimal(str(float(...)))`. A
  `format: decimal` would recover no digits and would make the value look exact. The real
  fix is decoding with `parse_float=Decimal` before validation, which is a per-venue core
  change; ask for it if bit2me precision ever matters in practice. Thirty
  `Decimal(str(...))` transcriptions remain on our side and are correct.
- **dydx's `Data` omits three endpoint mixins from its bases.** Verified at runtime here:
  `Data` is a subclass of all three and every method resolves. Working as designed.
- **A public module was removed without a version bump.** `typed_bit2me/types.py` went away
  under an unchanged 0.4.0. Our import moved in one line, so nothing is blocked, but it is
  the concrete case for the version-bump point in Environment above.

## codegen

Nothing open. Both closures are in "Accepted, not defects" above.

## typed-core

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

### `HttpClient.request`'s `headers` is a bare `Mapping`, making the method partially unknown

Every other parameter of `HttpClient.request` is fully typed (`httpx._types.*`), but
`headers` is an unparameterised `Mapping`. Under the no-implicit-Any rules the whole method
type becomes partially unknown, so every caller reports `reportUnknownMemberType` on the
attribute access itself -- not on the result, so no annotation on the caller's side can
silence it.

`public/typed/packages/core/src/typed_core/http.py:51`:

```python
    headers: Mapping | None = None,
```

- Kind: wrong-type
- Observed: pyright renders the parameter as `headers: Mapping[Unknown, Unknown] | None`
- Condition: any caller type-checked with `reportUnknownMemberType` enabled
- Samples: `packages/impl/mexc/pkg/src/tribulnation/mexc/earn/instruments.py:138`
  (`await client.request('GET', ...)`), the only remaining pyright error in
  `packages/impl/mexc`
- Blocks: nothing; `pkg/` code only
- Suggestion (unverified): `httpx._types.HeaderTypes | None`, matching the sibling
  parameters

## typed-bybit

### `coin_info.confirmation` is `''` on a chain with deposits disabled

A regression from this pass. `confirmation` became a required `int`, but 15 of 793 coins
send the empty string, so `asset.coin_info` now fails validation outright for every
caller. Its own sibling `withdrawFee` already admits the sentinel, two lines below.

`asset/coin_info.py:14`:

```python
  confirmation: int
```

- Kind: absent-under-condition (sentinel)
- Observed: `''`, e.g. `{'chain': 'SOL', 'confirmation': '', 'depositMin': '',
  'safeConfirmNumber': '', 'chainDeposit': '0', 'chainWithdraw': '1'}` on `1SOL`
- Condition: `chainDeposit == '0'`. Cross-tabulated over all 1034 coin/chain rows on
  2026-09-07: with deposits enabled, 571 rows and none empty; with deposits disabled, 448
  non-empty and 15 empty. Never empty when deposits are on.
- Samples: 1SOL/SOL, BANA/ETH, CAPO/BSC, CLEAR/ETH, ETH/ZKSYNC, ETHF/ETHF, KARATE/ETH,
  PEPE2NEW/ETH, PLANET/ETH, POKT/BASE, POKT/POKT, STAT/KLAY, STC/BSC, USDC/ZKSYNC,
  USDT/ZKSYNC
- Blocks: the whole bybit wallet surface -- `pkg/.../wallet/deposit_methods.py` and
  `wallet/withdrawal_methods.py`, and `poc/wallet.py` cells 2 and 4, which raised
  `ValidationError` on 2026-09-07 and were reverted to their last-good outputs
- Suggestion (unverified): `Literal[''] | int`, as `withdrawFee` already does.
  `depositMin` and `safeConfirmNumber` are `''` on the same 15 rows

### `SpotTicker.ask1Price`/`ask1Size` reject the sentinel their bid twins accept

A regression from this pass, and an asymmetry visible in the file itself: the bid fields
were widened to `Literal[''] | Decimal` with a docstring citing a live probe, and the ask
fields four lines later were left bare. `market.tickers(category='spot')` fails today.

`market/tickers.py:148,150` against `:152,154`:

```python
  bid1Price: Literal[''] | Decimal
  bid1Size: Literal[''] | Decimal
  ask1Price: Decimal
  ask1Size: Decimal
```

- Kind: absent-under-condition (sentinel)
- Observed: re-probed from the sdk side on 2026-09-07 against
  `GET /v5/market/tickers?category=spot`: 538 pairs, 3 with an empty ask, 3 with an empty
  bid. Validating that exact payload through `SpotTickers` raises
  `ValidationError(6 validation errors ... ask1Price ... input_value='')`
- Condition: nothing resting on that side of the book
- Samples: empty ask on `ETHTRY`, `AEDZUSDT`, `AEDZUSDC`; empty bid on `BTCTRY`, `ETHTRY`,
  `AEDZUSDC`. `linear` (863 rows) and `inverse` (26) carry no empties
- Blocks: `pkg/.../market/spot_exchange.py` `tickers()` -- every spot ticker call
- Suggestion (unverified): mirror the bid declaration onto the ask

### Stream ticker types keep `str` numerics on all five surfaces

The reply says the numeric fix covered "the ticker types on all five surfaces". It covered
the REST ones. The five stream ticker types took only the new `type` field, and every
numeric on them is still `str`.

`spot/ticker.py`, `linear/ticker.py`, `inverse/ticker.py`, `option/ticker.py` and
`spread_ws/ticker.py`, each a four-line diff in the fix commit.

- Kind: wrong-type
- Observed: not re-probed; the declarations are unchanged from the previous round
- Condition: always
- Blocks: nothing -- the sdk side reads tickers over REST
- Suggestion (unverified): the same `decimal-string` treatment the REST twins got

### `transaction_log` and `withdraw.record` still declare decimal strings as `str`

Same defect class as the entry that was fixed, on the two endpoints whose `Decimal(...)`
transcriptions the previous round named under `Blocks`. They survive.

`account/transaction_log.py:94,98,100` and `asset/withdraw/record.py:36,38`:

```python
  funding: str
  cashFlow: str
  change: str
```

- Kind: wrong-type
- Observed: decimal strings on the wire, same shapes as the converted siblings
- Condition: always
- Blocks: the `Decimal(...)` wraps in `pkg/.../reporting/history.py` and
  `pkg/.../market/impl/history.py`
- Suggestion (unverified): `format: decimal-string`. `asset/coin_info.py` also left six
  sibling numerics `str` at `:18,20,22,28,32,34`

### `funding_history_paged` sends an open `endTime` beside a closed `startTime`

The pager accepts either bound open now, but the venue rejects that one combination.

`market/funding_history.py:47`:

```python
  def funding_history_paged(
```

- Kind: missing-endpoint (contract gap)
- Observed: `retCode 10001 params error: Time Is Invalid` for `startTime` alone;
  `endTime` alone and neither bound both return `retCode 0` with 200 rows
- Condition: `start_time` given, `end_time` omitted
- Blocks: nothing -- `pkg/.../market/impl/history.py` `funding_rates` resolves an open
  upper bound to now, as the hand-rolled walk did before it
- Suggestion (unverified): let the walk seed its own upper bound

### `ExecutionUpdate.extraFees`/`execPnl` still differ from the REST `Execution`

The reply says the stream type matches REST "field for field". Fourteen numerics do; three
declarations do not, so the two types are still not interchangeable in general.

`private/execution.py:72,112`:

```python
  execPnl: NotRequired[str]
  extraFees: NotRequired[list[ExtraFee]]
```

- Kind: wrong-type
- Observed: not on the wire (no fill on this account). `trade/trade_history.py:133`
  declares `extraFees: NotRequired[str]` for the same concept; `execPnl` is a realised-PnL
  figure typed `str`; the two `execType` literal sets also differ
- Condition: always
- Blocks: nothing -- `parse_execution` reads none of the three, which is what let
  `parse_execution_update` collapse into it this round

### `market.kline` rows keep decimal strings as `str`

Same defect class as the `transaction_log` entry above, on the candle row the sdk's new
`Market.candles` reads.

`market/kline.py:19`:

```python
  list: list[tuple[TimestampMillis, str, str, str, str, str, str]]
```

- Kind: wrong-type
- Observed: decimal strings on the wire (`'63069.8'`, `'644.072'`, `'40611254.6565'`),
  spot and linear BTCUSDT, 2026-09-08
- Condition: always
- Blocks: the `Decimal(...)` wraps in `pkg/.../market/impl/history.py` `parse_candle`
- Suggestion (unverified): `format: decimal-string` on the six price/volume positions

## typed-bitget

### `MixTradeSide` is four values against the stream's own 22

The alias was widened to four values this round and every response type now references it.
The gap the reply itself flagged is still open: this repo's WebSocket specs declare a
22-value `tradeSide` vocabulary from bitget's stream documentation, including liquidation
and auto-deleverage closes. REST fill rows declare the four-value alias, so a liquidated
row rejects the whole page, not the row.

`schemas.py:423`, referenced by `classic/mix/order/fills.py:45` and
`fill_history.py:44`:

```python
MixTradeSide = Literal['open', 'close', 'buy_single', 'sell_single']
```

- Kind: missing-literal
- Observed: not reproduced -- the test account holds no futures position and
  `classic.mix.order.fills` returns an empty `fillList` for every symbol, so the PoC cell
  validates vacuously. The 22-value list is bitget's own, at `classic_streams/fill.py:41-64`
- Condition: a fill closed by liquidation, ADL, offset or delivery
- Blocks: `poc/market/classic.py` cell 13 (`perp_trades_history`),
  `poc/reporting/classic.py`'s mix fills, and futures trade reporting once
  `pkg/.../reporting/history/futures.py` is finished. UTA is immune:
  `uta/trade/order/fills.py:73` types it a bare `str`
- Suggestion (unverified): split into a narrow request enum and a wider response enum,
  as the reply proposes, rather than widening one alias in both directions.
  `classic_streams/order/place.py:87,118` also still hard-codes the two-value literal

## typed-binance

### `position_risk_v3` and spot `account.open_orders` still declare decimal strings as `str`

The reply's own open list names roughly 50 further endpoint files carrying this defect.
These two are the ones the sdk side actually reads, and both sit beside siblings that were
converted: `usdm_futures.account.account_v3` renders `Decimal` for the same quantities
`position_risk_v3` returns as `str`, and `spot.account.my_trades` renders `Decimal` for the
same `price`/`qty` shapes `spot.account.open_orders` returns as `str`.

`usdm_futures/http/trading/position_risk_v3.py:14,16`:

```python
  positionAmt: str
  entryPrice: NotRequired[str]
```

`spot/http/account/open_orders.py:25,27,29`:

```python
  price: str
  origQty: str
  executedQty: str
```

- Kind: wrong-type
- Observed: decimal strings on the wire. Spot `open_orders` ran live against the test
  account (`poc/market.py` cell 5); `position_risk_v3` is unreachable here (signed USD-M
  401s) and was verified against the declaration only
- Condition: always
- Blocks: the `Decimal(...)` wraps in `pkg/.../market/spot_market.py:148-156` and
  `pkg/.../reporting/snapshots.py:117-123`, each now carrying a comment saying why it
  survives, and `poc/reporting.py` cell 13
- Suggestion (unverified): `format: decimal-string`, as the sibling endpoints got

### `usdm_futures.http.market.klines` has no paged walk and types its open time as a bare `int`

The spot twin (`spot/http/market/klines.py`) has both a `klines_paged` walk and a
`SpotCandle` whose open and close times are `TimestampMillis`; the USD-M endpoint has
neither, so the sdk cannot sweep futures candles through the client.

`usdm_futures/http/market/klines.py:38-51`:

```python
Response = list[
  tuple[
    int,
    Decimal,
    ...
    int,
```

`clients/binance/spec/endpoints/usdm_futures/http/market/klines/endpoint.json` declares
no `pagination` block, and its `openTime`/`closeTime` items are `type: integer` with no
`format: epoch-millis`.

- Kind: missing-endpoint (walk) and wrong-type (open and close time)
- Observed: verified against the declaration only; the endpoint is public and answers
  the same row shape as spot
- Condition: always
- What the walk needs: the spot declaration verbatim -- `seek` on `[-1][0]`, bounds
  `startTime`/`endTime` (both inclusive on open time), anchor `start`, `limit` as size
  (default 500, maximum 1500 here rather than 1000), rows oldest first
- Blocks: `packages/impl/binance/pkg/.../market/perp_market.py` `candles`, which raises
  `NotImplementedError`; the sdk-dev market suite has no `binance:usdm` case
- Suggestion (unverified): copy spot's `pagination` block and `format: epoch-millis`

## typed-etherscan

### `proxy.*` results are `dict[str, Any] | None`

`proxy.eth_get_transaction_receipt`, `eth_get_transaction_by_hash` and `eth_get_code`
declare their JSON-RPC result as an untyped mapping, although the shapes are fixed by the
Ethereum JSON-RPC spec and the account feeds of the same client are fully typed now.

`proxy/eth_get_transaction_receipt.py:31`:

```python
  result: NotRequired[dict[str, Any] | None]
```

- Kind: wrong-type (untyped)
- Observed: every receipt carries `from`, `gasUsed`, `effectiveGasPrice`, `status`, `logs`;
  Arbitrum adds `gasUsedForL1`, OP-stack chains `l1Fee`
- Condition: always
- Samples: the full Arbitrum history of the test address in
  `packages/impl/ethereum/poc/reporting/history/etherscan.py`
- Blocks: nothing shipped -- the impl reads receipts from the node, not from `proxy.*`.
  The notebook's `hex_int`/`.get()` reads in cells 7-9 are what the gap costs

### `sort` is `str` on every paged account endpoint

`transactions_paged`, `internal_transactions_paged`, `erc20_transfers_paged`,
`erc721_transfers_paged` and `erc1155_transfers_paged` all take `sort: str | None`, where
Etherscan documents exactly `asc` and `desc`.

`account/erc20_transfers.py:107`:

```python
    sort: str | None = None,
```

- Kind: missing-literal (declared wider than the vocabulary)
- Observed: `asc` accepted; the documentation lists only `asc`/`desc`
- Condition: always
- Samples: every paged call in
  `packages/impl/ethereum/poc/reporting/history/etherscan.py`
- Blocks: nothing -- a typo in `sort` is a runtime error rather than a type error at the
  four call sites in `pkg/.../reporting/history/etherscan.py`
- Suggestion (unverified): `Literal['asc', 'desc']`

## typed-deribit

### `get_index_price`'s `index_name` literal is narrower than the venue's own index list

The surviving half of the previous round's `InstrumentInfo` entry, which had the direction
backwards. typed-dev's probe settled it: the instrument fields are correctly `str`, and it
is the consumer literal that is too narrow. The reply flags this and does not act on it,
because it is a public surface change on a shipped client.

- Kind: missing-literal
- Observed: typed-dev's probe found 344 index names served by the venue's own
  `get_index_price_names`, and confirmed live that `get_index_price` serves several the
  literal does not list, against 54 distinct `price_index` values on 5,550 instruments
- Condition: any index outside the literal
- Blocks: nothing shipped -- deribit has no package yet, only PoCs
- Suggestion (unverified): widen the literal to the venue's own list, or drop it to `str`.
  The `currency` literals on `get_account_summary` and `get_positions` do look genuinely
  closed and should stay

## typed-bit2me

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
- Samples: `packages/impl/bit2me/poc/wallet.py` cell 3
- Blocks: `poc/wallet.py` cell 3;
  `packages/impl/bit2me/pkg/.../wallet/withdrawal_methods.py:95-105`
- Suggestion (unverified): declare the proforma error body and expose it on the raised error

The reply offers a concrete shape for this and asks whether we want it: a
`ProformaShortfall` TypedDict (`code`, `fee`) on bit2me's `core/exc.py` plus a
`not_enough_funds(error) -> ProformaShortfall | None` helper reading `args[1]['data']`,
roughly 20 lines with no codegen change. The sdk side still reads `ApiError.args[1]` as
`Any` in `pkg/.../wallet/withdrawal_methods.py`, which is the only place a withdrawal fee
can be read at all, so the shape would land somewhere real. Awaiting a decision here before
we answer.

### `v1.trading.candles` rows are `list[float]` and the endpoint has no paged walk

Prices arrive as JSON numbers and the client keeps them as `float`, so no `Decimal` can
be read off a row without going through a binary float first. The endpoint also declares
no `pagination` block, and both bounds plus `limit` are required.

`v1/trading/candles.py:20`:

```python
TradingCandlesResponse = list[list[float]]
```

`clients/bit2me/spec/endpoints/v1/trading/candles/endpoint.json` types the row as a
homogeneous `number` array (its own note defers `prefixItems`) and declares no
`pagination`.

- Kind: wrong-type (prices) and missing-endpoint (walk)
- Observed: `[1777593600000.0, 65085.1, 65293.5, 65074.7, 65167.4, 5.01206556]` for
  BTC/EUR, 60-minute, 2026-09-08 -- six floats per row, the epoch included
- Condition: always
- What the walk needs: `startTime`/`endTime` both required, `limit` required (maximum
  1000), `interval` in minutes, rows oldest first with the forming candle last; a `seek`
  on `[-1][0]` anchored at `start` with `limit` as size
- Blocks: `packages/impl/bit2me/pkg/.../market/spot_market.py` `candles`, which raises
  `NotImplementedError`; the sdk-dev market suite has no `bit2me` case
- Suggestion (unverified): `prefixItems` with `format: epoch-millis` on the first and
  `format: decimal-string`-equivalent parsing of the numbers on the rest, plus a
  `pagination` block

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
- Samples: `packages/impl/dydx/poc/market.py` `depth_stream('BTC-USD')`
- Blocks: `packages/impl/dydx/poc/market.py` cell 10 (`depth_stream`);
  `packages/impl/dydx/pkg/.../market/impl/depth.py` `depth_stream` is written against the
  real split and raises at runtime today
- Suggestion (unverified): add `reply_type`, wire each channel's `*ReplyContents`,
  parameterize `StreamManager`'s second argument

**Still open after this round, deliberately.** The reply resolves it by not validating the
reply at all: it returns raw into the `Any` slot `Stream[T, Any, Unsubscribed]` already
declares, which unblocks entering an order-book stream and leaves pushed-message validation
untouched. That is a workaround, not the fix -- the `*ReplyContents` types are generated and
still unreferenced, and typing them properly needs a `reply` schema on the stream spec
model, a generated `reply_type` and a parameterised second argument to `StreamManager`. The
reply asks whether we want that scheduled. Awaiting a decision here before we answer;
the entry stays open either way, since the generated types are still unused.

## typed-coinbase

### `products.public.candles` answers at most 300 candles for INTX perpetuals, dropping the oldest

The declaration and the venue's docs cap a request at 350 candles, and spot honours it:
a 349-candle window of `BTC-USD` answers 349 rows. An INTX product answers the newest
300 of the same window, whatever `limit` says, and drops the rest silently. With
`limit=350` the generated walk reads those 300 rows as a short page and stops, so a
349-candle window of `BTC-PERP-INTX` loses 49 candles without an error.

`app/advanced_trade/http/products/public/candles.py:65`:

```python
    cap: int | None = min(limit, 350) if limit is not None else 350
```

- Kind: wrong-type (the declared size maximum, on one product family)
- Observed: `BTC-PERP-INTX`, `ONE_HOUR`, 349-candle windows from 2026-05-01 and
  2026-08-01 with `limit` 350, 300 and omitted: 300 rows each time, the oldest missing;
  320-candle window: 300 rows. `BTC-USD` over the same windows: every candle
- Condition: INTX products (`*-PERP-INTX`); spot products answer the documented 350
- Blocks: nothing -- `pkg/.../coinbase/market/impl/candles.py` windows 299 candles with
  `limit=300` for every product
- Suggestion (unverified): declare the size maximum as 300, or per product family

### `Candle.open`/`high`/`low`/`close` are `str` beside a `Decimal` `volume`

`schemas.py:59-67`:

```python
  low: str
  high: str
  open: str
  close: str
  volume: Decimal
```

- Kind: wrong-type
- Observed: decimal strings on the wire (`'62930.17'`, `'63075'`), `BTC-USD` and
  `BTC-PERP-INTX`, 2026-09-08
- Condition: always
- Blocks: the `Decimal(...)` wraps in `pkg/.../coinbase/market/impl/candles.py`
  `parse_candle`
- Suggestion (unverified): `format: decimal-string`, as `volume` already has

## typed-hyperliquid

### `info.candle_snapshot` has no paged walk and types `t`/`T` as bare `int`

`info/candle_snapshot.py:8,38`:

```python
  T: int
  ...
  t: int
```

Both are documented "in milliseconds since epoch" but carry no `format: epoch-millis`,
so they render as bare ints rather than `TimestampMillis`.
`clients/hyperliquid/spec/endpoints/info/candle_snapshot/endpoint.json` declares no
`pagination` block; its note rules one out because no fixed `step` stays correct across
every `interval`.

- Kind: missing-endpoint (walk) and wrong-type (open and close time)
- Observed: verified against the declaration only
- Condition: always
- What the walk needs: no `step` at all -- the `seek` on `[-1].t` anchored at `start`
  that binance and mexc klines already use, with both bounds required (the venue
  includes any candle whose span overlaps the range, per the spec's own note), a size of
  5000 (the most one call answers, and the most the venue holds per interval), rows
  oldest first
- Blocks: `packages/impl/hyperliquid/pkg/.../market/spot_market.py` and
  `perps_market.py` `candles`, which raise `NotImplementedError`; the sdk-dev market
  suite has no `hyperliquid` case
- Suggestion (unverified): `format: epoch-millis` on `t`/`T` and a `seek` pagination
  block on `[-1].t`

## typed-mexc

### `spot.http.market.candles`' declared `limit` maximum of 1000 is 500 on the wire

MEXC documents `limit` as "Default 500; max 1000", and the declaration follows it, but
the venue answers 500 rows whatever `limit` says. The generated walk sizes a page by the
`limit` it sent, so with `limit=1000` it reads the 500-row page as short and stops after
one page, silently ending the sweep.

`spot/http/market/candles.py:60`:

```python
    cap: int | None = min(limit, 1000) if limit is not None else 500
```

- Kind: wrong-type (the declared size maximum)
- Observed: `BTCUSDT`, `60m`, a 1200-hour window from 2026-05-01: 500 rows with `limit`
  500, 600, 1000 and omitted; `candles_paged` with `limit=1000` over 1050 candles yielded
  one page of 500 and stopped, with `limit=500` three pages of 500, 499 and 51
- Condition: always
- Blocks: nothing -- `pkg/.../mexc/market/impl/candles.py` passes `limit=500`
- Suggestion (unverified): declare the size maximum as 500

### `spot.http.market.candles` rows keep decimal strings as `str`

`spot/http/market/candles.py:23`:

```python
Response = list[tuple[TimestampMillis, str, str, str, str, str, TimestampMillis, str]]
```

- Kind: wrong-type
- Observed: decimal strings on the wire (`'76348.07'`, `'157.78038937'`), `BTCUSDT`,
  2026-09-08
- Condition: always
- Blocks: the `Decimal(...)` wraps in `pkg/.../mexc/market/impl/candles.py`
  `parse_candle`
- Suggestion (unverified): `format: decimal-string` on the six price/volume positions
