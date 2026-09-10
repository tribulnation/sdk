# ADR 0001: Separate public market rules from quoted account base fees

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: superseded by [ADR 0002](0002-combined-side-specific-fees.md)
2. Date: 2026-09-10

## Context

`rules()` combined instrument specifications with trading fees, but those fees
had different meanings across implementations. Some came from public schedules;
others required an account-specific fee query. Consequently, reading market
specifications could require personal credentials, and a caller could not tell
whether a fee was standard or account-specific. Missing rates sometimes became
zero, incorrectly implying free trading.

Market and Catalogue consistency checks need instrument specifications without
depending on personal fee tiers. Trading consumers also need an explicit way to
request their account's quoted rates. Neither a public schedule nor a pair of
account maker/taker rates fully describes every possible charge on a future fill:
side-dependent commissions, fee-payment options, and market-specific adjustments
can matter.

## Decision

### `rules()`: instrument specifications and public standard rates

1. `rules()` returns the instrument's native base/quote identifiers, increments,
   limits, API-trading availability, and standard non-VIP API trading rates where
   those rates are reliably known. It must not query personal fee tiers or change
   the fee schedule according to the configured account.
2. `Rules.maker_fee` and `Rules.taker_fee` are `Decimal | None`, expressed as
   fractions of notional. `None` means unknown, zero means a genuinely zero rate,
   and a negative rate means a rebate. Missing or ambiguous rates must not be
   replaced with zero or inferred from another product's schedule.
3. A web/app rate is not assumed to apply to API trading. Public rates need a
   traceable source and product scope; a documented static schedule also needs its
   verification date. Fee uncertainty alone does not prevent returning otherwise
   valid market specifications. Request failures and malformed specifications are
   not converted into successful results.
4. Public semantics do not promise credential-free transport on every venue.
   For example, a venue may require authentication to read product metadata;
   removing personal fee queries does not remove that requirement.

### `fees()`: quoted account base rates, not effective execution costs

1. `Market.fees(refetch=False)` returns `Fees(maker_fee=..., taker_fee=...)` for
   the configured account. Exchange, venue, and root market routers expose the
   same operation for a selected market ID and forward `refetch`.
2. Both rates are finite `Decimal` fractions of notional. Preserve genuine zeros
   and rebates. Missing account rates and authentication/request failures propagate;
   there is no fallback to `rules()`, a public standard schedule, or invented zero.
   An unsupported implementation raises `NotImplementedError`.
3. The values are the venue's quoted account **base** maker/taker rates. Any tier
   adjustment already reflected in the returned base rate is retained. This
   contract does not calculate an all-in rate by order side or fee-payment option.
4. Implementations must document exclusions concretely. Binance spot's quoted
   `standardCommission.maker`/`.taker` components exclude separate buyer/seller,
   tax, special-commission, and conditional fee-token adjustments. Hyperliquid's
   account base rates do not apply market-specific HIP-3 deployer/growth or
   quote-token adjustments, or separate referral adjustments. These exclusions
   must not be hidden behind a claim of effective per-market fees.
5. `refetch=True` bypasses an implementation's fee cache; an implementation may
   instead always fetch. No rate is a guarantee about the charge on a future fill.

## Alternatives considered

1. Keep personal fees inside `rules()`. Rejected because it couples specifications
   to account access and leaves fee semantics inconsistent across venues.
2. Return standard fees when personal fees cannot be read, or zero when no rate is
   available. Rejected because callers would mistake an estimate or unknown for
   an account-specific answer.
3. Make `fees()` an effective-fee calculator with side and payment options now.
   Deferred: those inputs and venue-specific adjustments require a richer
   contract. The current decision intentionally exposes quoted base rates with
   explicit exclusions rather than claiming that two numbers encode every charge.

## Consequences

1. Public market checks can validate rules independently of personal fee lookup.
   Unknown standard fees are valid metadata, not evidence that the venue is free
   or that its instrument identifiers cannot be tested.
2. Consumers previously using `rules()` for personal fees must migrate to
   `fees()`. Cost estimates based on those rates remain base-rate estimates;
   execution systems needing all-in costs must account for exclusions separately.
3. This changes the meaning and optionality of existing rule fields. Release notes,
   type annotations, examples, and adapter tests must communicate the change.
4. Regression tests must cover absence of personal reads in rules, unknown versus
   zero, finite rates and rebates, routing/refresh behavior, and failure without
   fallback. Applicable live checks remain necessary before release.
5. This record accepts the contract, not the completion of its rollout. It does not
   attest live venue behavior, passing fingerprinted reports, a working release
   gate, or release approval.
