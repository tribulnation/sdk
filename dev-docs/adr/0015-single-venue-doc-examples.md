# ADR 0015: Linear per-venue documentation examples

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted
2. Date: 2026-09-12

## Context

The docs wizard pre-rendered every nonempty selection of venues. That requires
2^N - 1 scripts and highlighted results per method, making complete venue coverage
unnecessarily expensive to generate, download and render. Filtering supported venues
by existing example constants also silently hid incomplete documentation.

## Decision

1. Method venue eligibility comes exclusively from implementation support metadata.
   Missing example constants for an eligible venue are a validation error.
2. Render one standalone script, result and optional Catalogue example per eligible
   venue. Templates receive `accounts = [venue]`. The existing JSON `subsets` field
   remains, but its keys are single venue slugs only, never comma-joined selections.
3. The frontend may retain multiple selected venues for installation/configuration.
   An active selected-venue tab displays that venue's complete pre-rendered example.
   It does not assemble Python or evaluate templates in the browser.
4. Example calls must target the active venue rather than enumerate all configured
   accounts. Initial selection must contain only eligible venues.

## Alternatives considered

1. All combinations preserve combined scripts but grow exponentially.
2. Restricting example venues conceals available implementations.
3. Client-side code synthesis duplicates SDK template logic and makes validation harder.

## Consequences

Generation and payload size grow linearly with venue count. SDK sync and Landing's
consumer must be updated together; the internal docs JSON representation changes, not
the public SDK runtime contract. Regression tests cover singleton contexts, linear
cardinality, complete eligibility and invalid defaults. Live method support and
example values remain distinct: illustrative output is not live release evidence.
