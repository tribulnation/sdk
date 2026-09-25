# Aster SDK implementation

`tribulnation-aster` connects the unified SDK to Aster's native spot and linear
perpetual markets through `typed-aster`. Install the SDK's `aster` extra, or install
this package and `tribulnation-sdk` together. From this repository:

```sh
uv pip install -e packages/sdk/pkg -e packages/impl/aster/pkg
```

## Usage

Public mainnet data is available through the default `aster` account:

```python
from tribulnation.sdk import MarketSDK

async with MarketSDK() as sdk:
  book = await sdk.depth('aster:perp:BTCUSDT', levels=5)
  spot = await sdk.market('aster:spot:ASTERUSDT')
  rules = await spot.rules()
```

Configure an authenticated testnet account in `sdk.toml`:

```toml
[accounts.aster_sandbox]
venue = "aster_testnet"
user = "$TEST_ASTER_USER"
signer = "$TEST_ASTER_SIGNER_PRIVATE_KEY"
```

`user` is the main wallet's public address; `signer` is the registered trading
agent's private key. The SDK never needs the main wallet's private key. With fields
omitted, mainnet resolves `ASTER_USER` / `ASTER_SIGNER_PRIVATE_KEY`, while testnet
resolves `TEST_ASTER_USER` / `TEST_ASTER_SIGNER_PRIVATE_KEY`. Testnet never falls back
to mainnet credentials. Set `public = true` for credential-free market reads.

```python
from tribulnation.sdk import MarketSDK

async with MarketSDK.load('sdk.toml') as sdk:
  market = await sdk.market('aster_sandbox:perp:ASTERUSDT')
  fees = await market.fees()
  async with market.trades_stream() as fills:
    async for fill in fills:
      print(fill)
```

Keep the root SDK context open while using its markets and streams. Subscribers
share one account listen key per exchange; removing one subscriber leaves the
others active. The last subscriber or root exit closes the socket, renewal task
and listen key. Separate SDK roots or external consumers of the same account's
listen key should not run competing lease lifecycles.

## Supported methods

1. Both exchanges: discovery, REST depth, shared depth streams (1–20 levels),
   tickers, public rules, authenticated fees, all six SDK candle intervals, order
   queries, open orders, live fills, placement and cancellation. Candle pages use
   half-open 500-bar windows and retry each failed request independently.
2. Perpetuals: native index, next funding, funding-rate history, one-way positions
   and cross-margin collateral. Hedge-mode positions and isolated available
   collateral are not qualified.
3. Orders: signed base quantities, `MARKET`, `LIMIT` (GTC) and `POST_ONLY` (GTX).
   Native market orders ignore the SDK `price` field. Batch placement uses the
   SDK's concurrent individual requests; cancellation splits into native batches
   of ten and preserves per-order failures. Spot order queries and cancel-all may
   lag placement/fill acknowledgements. Venue-specific settings are not implemented.
4. Report: native perpetual income and spot transaction cash records, exposed as
   `UnknownObservation` with distinct provenance for each asset/category leg.
   This is not a classified accounting ledger or complete position snapshot.
5. Spot balances/collateral, full trade history, bulk perpetual statistics,
   account-side capacity, aggregate leverage, funding payments, Report snapshots,
   Wallet and Earn remain explicit `NotImplementedError` methods. See the
   qualification gaps below and [support metadata](impl.toml).

Authenticated mappings were qualified on the dedicated **testnet** account.
Private mainnet behavior has not been exercised. Both networks keep native IDs
and typed response validation enabled. No blocked or empty PoC mapping is promoted
to advertised SDK support.

## PoC evidence

These percent-format notebooks exercise `typed-aster==0.1.0` against the SDK
interfaces. The 2026-09-25 runs used the generated, registered, faucet-funded
**testnet** wallet, including real orders and transfers explicitly authorized by
the user. The packaged implementation promotes the verified mappings below.

| Script | Verified | Empty | Blocked | Not supported |
|---|---:|---:|---:|---:|
| `poc/market/perp.py` | 20 | 1 | 2 | 2 |
| `poc/market/spot.py` | 14 | 0 | 3 | 1 |
| `poc/report.py` | 1 | 0 | 1 | 0 |
| `poc/wallet.py` | 0 | 0 | 2 | 0 |
| `poc/earn.py` | 0 | 0 | 0 | 1 |

All 48 SDK methods are accounted for: 35 verified, one empty, eight blocked and
four unsupported. There are no unattempted methods. Unavailable methods raise
explicitly; executing their rejection branches does not qualify venue support.

## Live trading evidence

1. Spot and perpetual MARKET and marketable LIMIT orders filled on both sides.
   POST_ONLY buys and sells rested and were cancelled. Query checks cover missing,
   resting, filled and cancelled orders, including signed quantities.
2. Single cancellation, eleven-order cancellation across the native ten-order
   batch boundary, empty batch input and cancel-all were exercised. Checks wait
   for REST confirmation because cancel-all acknowledgement can precede visibility.
3. Private streams received actual fills and their native fees. Perpetual fills
   matched a single REST page field-for-field. Spot sells matched; confirmed buys
   were missing from REST. Listen-key keepalive and cleanup were exercised.
4. Perpetual long, short and flat positions and entry prices were checked, together
   with native cross-margin collateral. Cleanup closed the test perpetual positions
   and cancelled resting orders. Spot round trips can leave sub-step ASTER dust.
5. All six candle intervals were read for BTCUSDT and ASTERUSDT on both venues.
   The one-minute test crosses the 500-row page boundary with 510 bars.
6. A 250 test USDT transfer funded spot. Both report cash ledgers now contain real
   activity. Spot transaction IDs repeat across asset/category legs, so report
   provenance includes both fields to preserve distinct records.

## Blockers and unsupported methods

1. [Typed-client defects](../../../typed-client-issues.md): bulk funding configuration
   rejects null fields; both trade-history paginators combine exclusive time/ID
   filters on continuation; documented deposit/withdrawal catalogues are missing.
2. [Testnet inconsistencies](testnet-issues.md): spot account information returns no
   balances despite successful funding and fills, and spot REST trade history omits
   confirmed buys. Spot position/collateral and the full report snapshot now refuse
   to return misleading empty data. The probes retain the conflicting native evidence.
3. Funding payments are still empty because the positions were closed before their
   scheduled settlement. Nonzero funding cashflows remain unverified.
4. The API does not publish the SDK's account-side buy/sell capacity or aggregate
   actual leverage. These are not reconstructed. Isolated collateral is unqualified;
   the verified collateral mapping covers the shared cross-margin bucket.
5. Earn has no testnet surface or published native instrument APR. Aster Chain's
   public transport uses mainnet even with `mainnet=False`, so it is not called.
6. Report history preserves native cash deltas as `UnknownObservation`, with raw
   categories in provenance. It does not classify trades/transfers or claim a
   complete position ledger. Fee-bearing spot cash legs need classification before
   treating their amounts as an additive economic ledger.

## Local testnet account

Keys remain in `poc/.env` (gitignored, mode `0600`). The agent is registered for
spot/perpetual trading with withdrawals disabled and a 30-day expiry. The official
[testnet faucet](https://www.asterdex-testnet.com/en/faucet) initially credited
1,000 test USDT and 1,000 test ASTER to futures. Trading moved 250 test USDT to spot.
The PoCs pass only `ASTER_USER` and `ASTER_SIGNER_PRIVATE_KEY`; the main-wallet key
is retained locally for account management and is not printed.

```dotenv
ASTER_USER=<testnet main-wallet address>
ASTER_SIGNER_PRIVATE_KEY=<testnet agent private key>
```

Every mutating PoC mapping checks the testnet transport before sending a request;
the packaged SDK uses the network explicitly selected by its account configuration.
The lifecycle cells are for this dedicated test account and create more test
activity on every run. Do not run concurrent lifecycle sessions on the same account:
one session owns each venue's account listen key.

## Run and validate

Use the SDK repository's `.venv` with `typed-aster`, the editable SDK and sdk-dev
packages, `ipykernel`, `pyright` and `ruff`. The complete runs include mutations and
explicit unavailable-method probes:

```sh
export PATH="$PWD/.venv/bin:$PATH"
sdk-dev poc run packages/impl/aster/poc/market/perp.py --cells 1-32
sdk-dev poc run packages/impl/aster/poc/market/spot.py --cells 1-24
sdk-dev poc run packages/impl/aster/poc/report.py --cells 1-6
sdk-dev poc run packages/impl/aster/poc/wallet.py --cells 1-7
sdk-dev poc run packages/impl/aster/poc/earn.py --cells 1-4
sdk-dev poc check aster
sdk-dev catalogue check
pytest packages/impl/aster/test
pyright packages/impl/aster/pkg
sdk-dev test market aster
ruff check --config .agents/tools/python/ruff.toml packages/impl/aster/poc
ruff format --check --config .agents/tools/python/ruff.toml packages/impl/aster/poc
```

All 73 code cells have matching local execution evidence. Paired `.ipynb` outputs
remain ignored. Passing checks mean the scripts are typed, executed and explicit
about gaps; they do not mean the blocked venue/client methods work.

The packaged SDK was also exercised on 2026-09-25: 28 Aster regression tests and
446 SDK/sdk-dev tests passed, along with 23 public market checks on each network.
The live suites explicitly skipped unsupported methods. Through `MarketSDK`, both
testnet exchanges passed concurrent placement, query and all cancellation paths,
plus real MARKET buys/sells delivered to two shared fill subscribers. Report
history returned 62 distinct native cash records. Final native account reads
confirmed no open orders on either exchange and no perpetual positions on any
symbol. Only public reads ran on mainnet. The wheel and source distribution build
successfully and include the typing marker and lazy-import stubs.

The sibling Catalogue additions cover 16 native asset symbols, 17 perpetuals and
three spot pairs. Synthetic `1000PEPE`/`1000SHIB` are instrument multipliers.
Unresolved spot identities remain `TESTUSDT`, `EVENT4_ALGERIA_WIN_YUSDT` and
`EVENT4_ALGERIA_WIN_NUSDT`; canonical identities are not fabricated.
