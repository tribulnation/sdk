# Open typed-client issues

## typed-aster

### `FundingInfo` configuration fields are null on some testnet response rows

`futures.market.funding_info()` fails validation on `typed-aster==0.1.0` against
`https://fapi.asterdex-testnet.com/fapi/v3/fundingInfo` (2026-09-25). The unfiltered
response includes symbols absent from testnet exchange information, with null
configuration fields. No validation override or alternate mapping is used.

`futures/market/funding_info.py:17`:

```python
  fundingIntervalHours: int
  """Funding interval in hours."""
  fundingFeeCap: float
  """Maximum funding rate."""
  fundingFeeFloor: float
```

1. Kind: absent-under-condition
2. Observed: `null` for all three fields in 501 of 758 rows, producing 1,503
   validation errors. All 501 affected symbols were absent from the testnet
   `exchange_info().symbols` response. Absence alone is not established as a
   sufficient condition; other symbols outside that list have numeric values.
3. Samples: `SUSHIUSDT` and `SHIELDAMZNUSDT` return `null` for all three fields.
   `BTCUSDT` returns `8`, `0.003`, `-0.003`; `ASTERUSDT` returns `4`, `0.02`, `-0.02`.
   The symbol-specific typed calls for BTC and ASTER validate successfully.
4. Blocks: `packages/impl/aster/poc/market/perp.py` cell 22 (`perp_stats`);
   cell 30 reproduces the validation failure and valid symbol-specific responses.
5. Reference: [official funding configuration endpoint](https://asterdex.github.io/aster-api-website/futures-v3/market-data/#get-funding-rate-config).

### `Aster` lacks the documented deposit and withdrawal asset catalogues

The official wallet API documents public asset/network catalogues. Enumerating
`sdk-dev poc surface aster` and inspecting the root declaration found no BAPI
client exposing either route. A deposit address or account withdrawal balance is
not a substitute for the complete supported-asset catalogue.

`main.py:11`:

```python
class Aster(AsterBase):
```

Its children are `chain`, `futures`, `prediction` and `spot`; none exposes these
documented BAPI methods.

1. Kind: missing-endpoint
2. Missing: `GET /bapi/futures/v1/public/future/aster/deposit/assets` and
   `GET /bapi/futures/v1/public/future/aster/withdraw/assets`.
3. Parameters: `chainIds`, `accountType`, optional `networks`.
4. References: [deposit assets](https://asterdex.github.io/aster-api-website/futures-v3/deposit&withdrawal/#get-all-deposit-assets),
   [withdrawal assets](https://asterdex.github.io/aster-api-website/futures-v3/deposit&withdrawal/#get-all-withdraw-assets).
5. Blocks: `packages/impl/aster/poc/wallet.py` cells 3 (`deposit_methods`) and
   4 (`withdrawal_methods`). The existing testnet `futures.wallet.withdraw_info`
   also returns code `-1000`; cell 6 records that separate venue limitation.

### `UserTrades.user_trades_paged` combines exclusive time and ID filters

A real continuation of both futures and spot `trade.user_trades_paged` fails on page two.
The first page validates and returns two fills. The paginator then adds `fromId`
while retaining both caller-supplied time filters. Aster rejects that combination:
`{'code': -1106, 'msg': "Parameter 'startTime and endTime' sent when not required."}`.

`futures/trade/user_trades.py:110` (also `spot/trade/user_trades.py:73`):

```python
      response = await self.user_trades(
        symbol,
        order_id=order_id,
        start_time=start_time,
        end_time=end_time,
        from_id=pos,
        limit=limit,
        validate=validate,
      )
```

1. Observed on testnet, `typed-aster==0.1.0`, 2026-09-25: `ASTERUSDT`, an explicit
   one-hour range containing eight real fills, and `limit=2`. The first page
   returned IDs `36327403` and `36327404`; its continuation raised `BadRequest`.
   A single native page with `limit=1000` returns the fills and reconciles with
   the WebSocket. The large page does not qualify the broken pagination path.
2. The endpoint itself documents that `fromId` cannot be combined with time
   filters. This is request-construction behavior, not a response schema failure.
   No alternative paginator or validation override is used in the PoC.
3. Blocks: `packages/impl/aster/poc/market/perp.py` cell 12 (`trades_history`).
   Cell 31 reproduces the continuation error using real account fills.
   Spot cell 23 reproduces the same error after two real sell fills. Spot cell 12
   is additionally blocked by the venue's missing buy fills in `dev-docs/aster-market.md`.
4. Reference: [account trade list](https://asterdex.github.io/aster-api-website/futures-v3/account&trades/#account-trade-list-user_data).
