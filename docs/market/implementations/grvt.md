<!-- github-only -->
<table><tr>
<td align="center"><a href="../../index.md">Docs</a></td>
<td align="center"><b>Market</b></td>
<td align="center"><a href="../../earn/index.md">Earn</a></td>
<td align="center"><a href="../../wallet/index.md">Wallet</a></td>
<td align="center"><a href="../../report/index.md">Report</a></td>
<td align="center"><a href="../../reference/index.md">Reference</a></td>
<td align="center"><a href="https://tribulnation.com/sdk/docs/support">Support matrix</a></td>
</tr></table>
<!-- /github-only -->

# GRVT Market

> USDT-margined perpetuals. `tribulnation-grvt`, venue names `grvt` and `grvt_testnet`.

See the [generic market interface](../index.md) for the shared method surface. This page
covers only what is GRVT-specific.

## Account

Three credential modes, by what the account configures:

| Method | Public | API key | API key and private key |
| --- | --- | --- | --- |
| Market data | yes | yes | yes |
| `fees`, `query_order`, `open_orders`, `trades_history`, `trades_stream`, `position`, `collateral`, `perp_position`, `perp_collateral`, `leverage`, `available_notional`, `funding_payments` | no | yes | yes |
| `cancel_order`, `cancel_orders`, `cancel_open_orders` | no | yes (unsigned; the venue checks the key's permissions) | yes |
| `place_order`, `place_orders` | no | no | yes |

```toml
[accounts.grvt]          # trading: the API key and its signer's private key
venue = "grvt"           # or "grvt_testnet"
api_key = "$GRVT_API_KEY"
private_key = "$GRVT_PRIVATE_KEY"

[accounts.grvt_readonly] # every account read; a read-only API key suffices
venue = "grvt"
api_key = "$GRVT_API_KEY"

[accounts.grvt_public]   # market data only
venue = "grvt"
public = true
```

`trading_account_id` selects the trading sub-account the account reads and orders use;
unset, it is the one the API key is scoped to. With the fields omitted, `grvt` reads
`GRVT_API_KEY`, `GRVT_PRIVATE_KEY` and `GRVT_TRADING_ACCOUNT_ID`, and `grvt_testnet` the
same names prefixed `GRVT_TESTNET_`. Testnet never falls back to mainnet variables.
Methods outside the account's mode raise `AuthError` naming what is missing. `validate`
toggles response validation.

## Exchange & ID conventions

- One exchange, `perp`. Market ids are instrument names, the same on mainnet and
  testnet: `grvt:perp:BTC_USDT_Perp`. Delisted instruments stay listed; `rules().api`
  says whether one trades.
- Asset ids are currency codes (`USDT`, `USDC`). Fees, margin and funding are in USDT.

No `settings` are read.

## Venue-specific semantics

- `rules().fees` is tier 1 of GRVT's published schedule (maker -0.0001%, taker
  0.0450%), which the API also reports as tier 1. `fees()` reads the account's tier, the
  same for every perpetual and both sides.
- `rules()`: `step_size` and `fixed_min_qty` are the instrument's `min_size`, and
  `min_value` its minimum notional. The position-size cap stays in `details`.
- REST `depth` asks for the smallest venue depth (10, 50, 100 or 500 levels per side)
  covering `levels`. Depth streams maintain the full book from a snapshot and 50 ms
  deltas, shared per market, and fail on a sequence gap.
- GRVT has no bulk ticker: `tickers` and `perp_stats` send one `ticker` request per
  market, concurrently. Prices of an empty book side are `None`; 24h volumes are taker
  buys plus taker sells.
- Order ids are client order ids. `place_order` sends `Order['client_order_id']`
  unchanged (GRVT takes integers, and reserves `[2^63, 2^64)` for API clients), else
  `random_client_order_id()`'s; fills report it as both `order_id` and
  `client_order_id`. `query_order` finds filled and cancelled orders too.
- Orders: `MARKET` is the venue's immediate-or-cancel market order, which takes no limit
  price, so `price` is not sent. `LIMIT` rests good-till-time and `POST_ONLY` is a
  post-only good-till-time order; both expire 29 days after signing, since GRVT caps a
  signature at 30 days.
- `place_order` raises `OrderRejected` when the venue refuses the order before accepting
  it: an off-tick price (`2064`), a size off the step (`2065`), a notional below the
  minimum (`2066`), a margin or reduce-only check. A client order id already in use
  (`2012`) stays `BadRequest`, since that order may be the caller's own earlier attempt.
  The reply is the order as accepted (`PENDING`), so `OrderResponse.filled_qty` is
  `None`; a refusal after acceptance, such as a post-only order that would cross, shows
  as a `REJECTED` order state.
- The venue acknowledges a cancellation of any id, known or not; read the outcome with
  `query_order`.
- Trade history trails the fills stream by a few seconds.
- Funding settles every 4 or 8 hours, by instrument. `next_funding` is the indicative
  rate of the current interval, positive when longs pay, with no premium. Funding-rate
  history drops the rows GRVT recorded every minute before mid-October 2025, which are
  not settlements; a walk without `start` still reads through them. Funding payments are
  positive when received.
- History bounds are inclusive, applied to the venue's nanosecond times.
- `perp_collateral` is the trading sub-account's cross bucket. A market holding an
  isolated position raises `NotImplementedError`: that bucket is unverified.
  `leverage` is the account's initial leverage on the market (10 unless changed).
  `available_notional` is the free cross collateral times it, without GRVT's
  position-size cap or risk brackets.
- Public and account reads are verified on mainnet; trading on testnet only.

<!-- next -->

---

← [Deribit Market](deribit.md) · **Next:** [Lighter Market](lighter.md) →

<!-- /next -->
