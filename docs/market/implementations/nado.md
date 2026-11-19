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

# Nado Market

> USDT0-settled perpetuals and spot on one unified account. `tribulnation-nado`, venue names `nado` and `nado_testnet`.

See the [generic market interface](../index.md) for the shared method surface. This page
covers only what is Nado-specific.

## Account

Nado has no API keys: every account read is public, and every write is an EIP-712
signature. Three credential modes, by what the account configures:

| Method | Public | Address | Private key |
| --- | --- | --- | --- |
| Market data | yes | yes | yes |
| `fees`, `query_order`, `open_orders`, `trades_history`, `trades_stream`, `position`, `collateral`, `balances`, `perp_position`, `perp_collateral`, `leverage`, `available_notional`, `remaining_position_limit`, `funding_payments` | no | yes | yes |
| `place_order`, `place_orders`, `replace_order`, `cancel_order`, `cancel_orders`, `cancel_open_orders` | no | no | yes |

```toml
[accounts.nado]           # trading: the owner's key, or its linked signer's
venue = "nado"            # or "nado_testnet"
private_key = "$NADO_PRIVATE_KEY"

[accounts.nado_readonly]  # every account read
venue = "nado"
address = "$NADO_ADDRESS"

[accounts.nado_public]    # market data only
venue = "nado"
public = true
```

`address` is the wallet owning the subaccount; it defaults to the private key's own
address, so set it only when the key is a linked signer. `subaccount` names the
subaccount (`default`, the one the app creates, when unset). With the fields omitted,
`nado` reads `NADO_PRIVATE_KEY`, `NADO_ADDRESS` and `NADO_SUBACCOUNT`, and
`nado_testnet` the same names prefixed `NADO_TESTNET_`. Methods outside the account's
mode raise `AuthError` naming what is missing. `validate` toggles response validation.

## Exchange & ID conventions

- Two exchanges, `perp` and `spot`. Market ids are product symbols: `nado:perp:BTC-PERP`,
  `nado:spot:KBTC`. Untradable products stay listed; `rules().api` says whether one
  takes every order type (`live`).
- Asset ids are spot symbols (`KBTC`, `WETH`, `USDC`), and `USDT0` for product 0, the
  quote of every market. Fees, margin and funding are in USDT0.
- The subaccount is one unified cross-margin account: its spot balances and perpetual
  positions are margined together. Every perpetual's `collateral_id()` is
  `<account>:spot:USDT0`, the same id spot markets' buys reserve on.
- Order ids are digests.

`settings={'nado': {'spot_leverage': True}}` lets a spot order borrow; without it spot
orders never borrow, and one that would is refused (`2017`).
`settings={'nado': {'reduce_only': True}}` makes an order reduce-only.

## Venue-specific semantics

- Orders: `LIMIT` rests until cancelled, `POST_ONLY` is post-only; both are signed with
  a 2100-01-01 expiration, Nado's way of resting indefinitely. Nado has no market order:
  `MARKET` is an immediate-or-cancel limit at `price`, the worst acceptable.
  `Order['client_order_id']` must be a decimal integer below `2^64`; it is sent as the
  order's `id`, which open orders and the fills stream report but the archive does not.
  `random_client_order_id()` draws one below `2^63`.
- `place_order` raises `OrderRejected` for every coded refusal: an off-tick price
  (`2000`), a notional below the 100 USDT0 minimum (`2094`), an IOC that does not cross
  (`2056`), a spot borrow (`2017`), health and post-only checks. `place_orders` is one
  request validated whole: one invalid order refuses every order of the batch.
- `replace_order` is the atomic `cancel_and_place`: a refused replacement leaves the
  original resting and raises `BadRequest`, not `OrderRejected`. Replacing an id no
  longer on the book still places the new order.
- `cancel_order` raises `OrderNotFound` when the venue removed nothing.
- `query_order` reads a resting order from the book, else from the archive, which
  indexes only orders that filled at least once: an order cancelled unfilled is `None`.
- Resting orders hold nothing: Nado checks health when an order is placed and when it
  fills. Spot `free` is the balance (never negative); USDT0's is further capped at the
  initial health.
- `perp_collateral()` is the whole subaccount: equity is the unweighted health, the
  margins are its distance to the initial and maintenance healths, free collateral is
  the initial health. `leverage` is what the product's initial risk weights allow (cross
  margin has no per-account leverage setting), and `available_notional` free collateral
  times it, which matched the venue's own `max_order_size`. A market holding an isolated
  position raises `NotImplementedError` from its account reads.
- `remaining_position_limit` (ADR 0062) is the room left under the product's
  `max_open_interest_x18`, a notional cap (`null`: uncapped, `None` both ways), for both
  directions, as a new position on either side can raise open interest. Nado publishes
  no per-account cap. The cap is held against the gateway's open interest at the mark,
  which counts both sides; which figure Nado compares is undocumented, so the room may
  be half the venue's, never more. The cap comes from the cached `symbols`; the open
  interest (`all_products`) and every perpetual's mark (`perp_prices`) from one request
  each, shared by all markets for `ttl` (30 s by default, ADR 0069). An uncapped product
  reads nothing.
- `rules().fees` are the products' default rates; `fees()` reads the subaccount's
  per-product rates. Nado's fixed sequencer fee is not a rate and is not included.
- REST `depth` returns at most 100 levels per side. Depth streams apply the `book_depth`
  diffs to a 100-level snapshot, shared per market, and fail on a lost diff; they keep
  at most 100 levels per side.
- `tickers` carry the last price and 24h volumes, which the venue sends as JSON floats,
  and the best bid and ask without sizes.
- Funding settles hourly. Nado quotes funding as a 24-hour rate; `next_funding`,
  `perp_stats` funding and `funding_rates` are per hourly settlement, positive when
  longs pay. Funding payments are positive when received.
- A closed position's PnL reaches the USDT0 balance a few seconds later, when Nado
  settles it; until then USDT0's `free` (capped at the initial health) already reflects
  it, and `Report` counts it.
- Public and account reads, the order lifecycle with post-only orders that could not
  fill, and one taker round trip on BTC-PERP (a `MARKET` buy and a reduce-only `MARKET`
  sell, costing exactly the two taker fees and the spread) are verified on mainnet.

<!-- next -->

---

← [margin.trade Market](margin-trade.md) · **Next:** [RISEx Market](risex.md) →

<!-- /next -->
