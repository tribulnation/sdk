# ADR 0002: Combined side-specific trading fees

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted
2. Date: 2026-09-10
3. Supersedes: [ADR 0001](0001-public-rules-and-account-fees.md)

## Context

ADR 0001 separated public specifications from account fee lookup, but allowed
account base rates that omitted known charges. For example, Binance spot exposes
maker/taker and buyer/seller components across standard, tax and special
commissions. Returning only the standard maker/taker component understates costs
even before rates change or optional fee-token discounts apply.

The caller already knows whether it will buy or sell and make or take liquidity.
Four combined rates express that distinction without requiring every consumer to
reimplement venue fee arithmetic.

## Decision

1. Use one immutable `Fees` value with four required finite `Decimal` fields:
   `maker_buy`, `maker_sell`, `taker_buy`, and `taker_sell`. Values are fractions
   of trade notional, with zero preserved and negative rates representing rebates.
   They are combined rates for each case, not independently additive components.
2. `Rules.fees: Fees | None` describes the public standard non-VIP API schedule.
   `None` means the complete four-rate schedule is not reliably known. Remove the
   ambiguous `Rules.maker_fee` and `Rules.taker_fee` fields. Other rules remain
   available without a fee schedule, and rules never query personal fee tiers.
3. `Market.fees(refetch=False) -> Fees` describes the configured account's schedule
   for that market. Keep equivalent exchange, venue and root routers. No fallback
   to public fees, invented zeros, or incomplete components is permitted.
4. Include all applicable known unconditional charges and adjustments, including
   side-dependent, tax/special, and market-specific adjustments. For Binance spot,
   `taker_sell` sums each commission category's taker and seller components;
   the other three cases follow the corresponding maker/taker and buyer/seller
   combination. Symmetric venues return equal buy/sell values only when their
   schedule supports that equivalence.
5. Exclude optional fee-payment discounts: rates assume payment without selecting
   a discounted fee token or payment option. Account tier or market adjustments
   are not optional payment discounts and must not be silently omitted.
6. When the required schedule cannot be represented or established, public rules
   return `fees=None`; account `fees()` raises `NotImplementedError` for an explicit
   capability gap. Authentication, request and malformed-response failures remain
   failures, not unsupported success. Missing account rates never become zero.
7. `refetch=True` bypasses any fee cache; always-fetch implementations are allowed.
   These are current rates, not a guarantee about future fills, fee-asset conversion,
   rounding or a final cash amount. A market whose fees require additional inputs
   beyond these four cases is unsupported until a richer contract is agreed.

## Alternatives considered

1. Keep base rates and document exclusions. Rejected: known omissions are too easy
   to mistake for usable trading costs.
2. Return separate maker/taker and buyer/seller components. Rejected: this pushes
   composition onto consumers and cannot express every case-dependent adjustment.
3. Add an order/fee-payment simulator now. Deferred: four combined rates cover
   the agreed cases without adding order-size, leverage or payment-option inputs.

## Consequences

1. Preserve ADR 0001's public/personal separation, unknown-versus-zero distinction,
   evidence requirements, and prohibition on account-fee reads from rules.
2. Consumers must select the matching side and liquidity role. Book cost helpers
   must apply sell rates to bids and buy rates to asks, not a single rate to both.
3. Venue implementations require upstream investigation, not a mechanical rename
   of old components. Unknown public rates remain visible implementation gaps;
   the nullable contract does not excuse failing to investigate public schedules.
4. Tests cover four distinct rates, symmetric schedules, zeros and rebates,
   malformed/missing components, known adjustments, and failure without fallback.
   Local SDK/Catalogue consistency checks and fingerprinted release evidence remain
   separate obligations. Acceptance of this ADR does not approve a release.
