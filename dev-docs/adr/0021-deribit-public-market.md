# ADR 0021: Deribit public spot and linear perpetual Market support

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted; implementation qualification and release approval are separate.
2. Date: 2026-09-19

## Context

SDK #33 separates public market expansion from Deribit's existing Wallet/Earn/Report
package. The old prototype mixed public mainnet with private testnet reads and
contained obsolete fee fields, inverse quantity errors and fabricated funding times.
Validated mainnet probes establish a narrower public implementation.

## Decision

1. Expose `spot` and `perp`, preserving native instrument names and currency symbols.
   Discover active spot and futures classified as linear, perpetual, and settled in
   their quote asset. Exclude inverse, dated, option and combination contracts.
   Native metadata may include tokenized/RWA products; this is not a crypto-only filter.
2. Construct a credential-free mainnet client even when other surfaces have private
   credentials. Reject `deribit_testnet` in MarketSDK rather than relabeling its data.
   Private Market methods and trading remain unsupported.
3. Map native base-unit book quantities, summary volume and linear open interest
   directly, without multiplying them by contract size. Request product-scoped
   summaries; broad BTC summaries currently fail typed validation on null estimated
   delivery prices. Read index and mark directly from native tickers, pacing shared
   ticker requests to at most ten per second.
4. Support REST depth 1–100 and full-snapshot public streams 1–20, defaulting to 20.
   Share one upstream per instrument with bounded subscriber queues and independently
   owned mutable books. Public streams need no trade activity to satisfy snapshot
   qualification; subsequent messages depend on book updates.
5. Support native trade candles at `1m`, `5m`, `15m`, and `1h`, using validated public
   WebSocket calls and 1000-open time windows. Preserve aware half-open bounds,
   native order, optional volumes and empty windows. Check parallel-array lengths
   and remove repeated opening timestamps. Do not synthesize candles.
6. Coinbase-routed spot instruments expose no candle intervals, based on native
   `is_csr`/`is_cbe_routed` metadata. No external Coinbase series is substituted.
   Deribit has no native `4h` resolution. Its native daily candles open at 08:00 UTC,
   outside the SDK's current epoch-aligned interval checks, so `1d` is also excluded.
   Unsupported intervals follow the SDK's `ValueError` contract before a request.
7. Keep rules and fees unsupported: spot fee denomination and a general quantity-step
   fallback have not been qualified. Minimum order amount is not automatically an
   increment, and `lot_size` is explicitly not a quantity constraint.
8. Keep scheduled funding methods and optional funding statistics unsupported.
   Deribit continuously accrues funding and transfers it to cash at daily settlement;
   hourly `interest_1h`/`interest_8h` observations do not by themselves establish the
   SDK's discrete payment-time series or a forecast. No timestamps/rates are invented.

## Alternatives and consequences

Promoting the old prototype would preserve known wrong semantics. It is replaced by
an independently executable public PoC; its private experiments remain in git history.
Inverse quantities/rules, native daily grids, and continuous-funding representation
need separate qualification or contract decisions. Historical API samples do not
establish archive completeness.

The existing Catalogue has no Deribit spot/perpetual entries. Native discovery works,
but canonical market mappings remain a separate Catalogue task. A passing consistency
policy check does not establish mappings that do not exist. New versions and complete
release evidence are required before publication; Terminal rollout is separate.

References:

- [Qualification and version handoff](../deribit-public-market.md)
- [Linear perpetual units and funding](https://support.deribit.com/hc/en-us/articles/31424969384605-Linear-Perpetual)
- [Native quantity fields](https://support.deribit.com/hc/en-us/articles/38507223482781-API-guidance)
- [Spot routing](https://docs.deribit.com/articles/spot-trading-venues)
