# ADR 0056: Market-kind-aware support declarations

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: proposed; implemented, not release-verified
2. Date: 2026-10-28
3. Builds on: [ADR 0051](0051-spot-perp-market-types-collateral-ids.md) (spot and
   margin market types)

## Context

`[support.<surface>] support = "full"` in a venue's `impl.toml` meant every method of
the surface's contract. ADR 0051 added methods that exist on one kind of market only:
`balances()` and `collateral_ids()` on spot markets, `collateral_id()` on margin
(perpetual) markets. Perpetual-only venues (dYdX, GRVT, Extended) implement every
method their markets can have, but a `full` declaration also counted them for the spot
methods. The published `support.json` listed them as serving `balances`, there were no
examples for them, and the landing site's docs test, which recomputes eligibility from
`support.json`, failed the deploy.

Two stopgaps existed. `sdk-dev docs` dropped a `full` venue from a kind-scoped method
when the contract had no example constants for it, which inferred support from example
data and was invisible to every other consumer. sdk#293 declared the three venues
`partial`, enumerating 27 methods, which is accurate but reads as a gap that does not
exist and has to be maintained by hand whenever a perpetual method is added.

The kind of each method was also stated in several places: `kind:` in
`docs/contract/market.yml` (only for the three ADR 0051 methods), and hardcoded sets in
the read-suite exclusion policy and evidence verifier.

## Decision

1. **Venues declare kinds.** `[support.<surface>]` takes an optional
   `kinds = ["spot", "perp"]`, the kinds of market the venue serves on that surface. It
   is non-empty and unique. Absent means every kind, which keeps every existing
   declaration's meaning and is what surfaces without kind-scoped methods need; on such
   a surface (everything but Market today) declaring `kinds` is an error. Every Market
   venue declares it explicitly anyway, so the matrix states it.
2. **Methods declare kinds, in the contract only.** A method's `kind` in
   `docs/contract/<surface>.yml` is the one source: `spot` for SpotMarket methods,
   `perp` for margin and perpetual ones, absent for methods every market has. Market
   now marks all margin and perpetual methods `perp` (`position`, `collateral`,
   `available_notional`, `leverage`, `perp_position`, `perp_collateral`,
   `collateral_id`, `index`, `next_funding`, `funding_rates`, `funding_payments`,
   `perp_stats`), matching ADR 0051's hierarchy.
3. **Eligibility.** A method applies to a venue when it has no `kind` or its kind is
   in the venue's `kinds`. `full` means every applicable method; `partial` means the
   applicable methods its `methods` list names. A `partial` list naming a method
   outside the venue's kinds contradicts the contract and fails `sdk-dev docs check`.
   `ImplSurfaceSupport.declares(method, kind)` is the one implementation, used by
   `method_universe` (docs rendering and the streaming table), the read-suite
   exclusion policy, the surface and read evidence inventories and the consistency
   scope. The example-constants inference is removed: a supported venue without
   constants fails, as for any other method.
4. **Publication.** `support.json` carries each venue's declared `kinds` (absent when
   not declared), and each rendered contract method carries its `kind`. The site
   recomputes eligibility from these declarations with the rule above, instead of
   `support.json` exporting per-method eligible venues. The site's docs test exists to
   check the rendered examples against the declarations independently; exporting the
   SDK's computed eligibility would make that check compare the SDK with itself. The
   declared kinds also let the support page say which methods do not apply to a venue
   rather than listing them as missing.
5. **Read-suite exclusion codes are unchanged.** A read whose kind differs from the
   reference market's exchange (`spot`, or margin for any other exchange ID) is still
   excluded as `perp_only` or `spot_only` before support is consulted, now from the
   contract's kinds. The kinded account reads are exactly the former hardcoded sets,
   so recorded evidence verifies as before; a test pins that equality.
6. dYdX, GRVT and Extended return to `support = "full"` with `kinds = ["perp"]`;
   Coinbase and Bit2Me declare `["spot"]`; every other Market venue `["spot", "perp"]`.

## Alternatives considered

1. Keep `partial` lists for perpetual-only venues (sdk#293). Accurate, but it reports
   inapplicable methods as unimplemented and needs every new perpetual method added
   to three lists.
2. A per-venue `exclude = [...]` list under `full`. It names methods rather than the
   reason, so a new spot method would again silently count perpetual-only venues.
3. Export per-method eligible venues in `support.json`. Simpler for the site, but the
   site's independent check would become a tautology and the support page could not
   tell "does not apply" from "not implemented".
4. Infer kinds from the adapter code (`SpotExchange` subclasses). Rejected for the
   same reason the matrix is declared at all: a venue can have code before it is ready
   to announce.
5. Default an absent `kinds` to an error on Market. Explicit, but it would break
   every out-of-tree `impl.toml` for no gain once every in-tree venue declares it.

## Consequences

1. `impl.toml` gains an optional key; existing files keep their meaning. Adding a
   kind-scoped method to a contract no longer requires touching perpetual-only or
   spot-only venues' declarations.
2. `support.json` and the rendered contract JSON gain optional fields. The site must
   apply the kind rule wherever it computes eligibility (landing's docs test and
   support page); until it does, its check disagrees with the SDK's universes.
3. A future option market needs a new kind value in both the contract and `kinds`.
4. Changing a venue's declaration changes its release scope as any `impl.toml` edit
   does (ADR 0033); the exclusion codes in its evidence are unchanged.
