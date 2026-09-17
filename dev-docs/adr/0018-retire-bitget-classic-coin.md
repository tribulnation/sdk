# ADR 0018: Retire Bitget Classic coin-margined markets

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted
2. Date: 2026-09-17
3. Amends [ADR 0008](0008-bitget-classic-and-uta-coin.md) and
   [ADR 0010](0010-defer-bitget-uta-coin.md).

## Context

Bitget retired its nine remaining Classic coin-margined perpetuals on September 17,
2026 at 07:00 UTC. Its Classic `COIN-FUTURES` listing now returns no contracts.
[Bitget's announcement](https://www.bitget.com/support/articles/12560603893788)
confirms retirement; this is not an inference from an empty book or a transient error.
The user approved fixing the delisting before continuing patch releases.

## Decision

1. Advertise only `spot`, `usdt`, and `usdc` from Bitget market discovery. Explicit
   `coin-classic` requests raise `NotImplementedError` with the retirement date,
   without contacting retired endpoints or aliasing to another product.
2. Preserve historical Classic Catalogue records and IDs, marking the nine confirmed
   contracts delisted and removing any trading URLs. Do not rename them to UTA IDs.
3. Remove retired Classic live reference cases and their product routing. Active
   Catalogue rows from an unknown exchange still block qualification; no blanket
   `coin-classic` exemption is added. Qualification relies on reviewed delisting data.
4. UTA `coin` remains explicitly unsupported under ADR 0010. Its active Catalogue
   records and native `*_CM` IDs are unchanged. No migration or trading is included.
5. Keep historical reporting code independent of current market discovery.

## Alternatives considered

- Retain an empty advertised exchange: promises unavailable data and fails reference
  checks against contracts the venue no longer serves.
- Route Classic IDs to UTA: silently changes contract identity and quantity semantics.
- Skip failing checks without delisting evidence: weakens qualification for active
  products and hides an actual support-contract change.

## Consequences

Consumers can no longer discover or request live Classic coin markets. Historical
IDs remain resolvable in the Catalogue as delisted instruments. Spot, USDT, USDC,
and the existing UTA deferral retain their contracts.

The changed qualification inventory requires fresh release evidence; prior evidence
cannot be relabeled as current. Tests cover explicit retirement without requests,
remaining product routing, and rejection of undeclared missing exchanges until their
Catalogue records are explicitly delisted.
