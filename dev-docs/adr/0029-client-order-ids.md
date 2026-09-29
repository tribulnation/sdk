# ADR 0029: Client order IDs on orders and fills

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted; unit fixtures verify the mappings, no live trading run does.
2. Date: 2026-09-29

## Context

A strategy that trades and follows fills on the same account, such as a hedger reacting
to its own fills, needs to know which order each fill executed. `Trade` carried neither
the order's ID nor any caller-chosen tag. Matching fills to orders therefore meant
reading `details`, venue by venue.

Most venues accept a caller-chosen client order ID when an order is placed and report it
on that order's fills. Their rules differ. Binance and Aster take up to 36 characters from
a fixed alphabet, Bybit takes 36, Hyperliquid wants a 16-byte hex string, and dYdX and
Lighter have no free-form field. On dYdX the protocol client ID is part of the SDK's order
ID, and on Lighter the client order index is the SDK's order ID.

## Decision

1. `Order` gains an optional `client_order_id`. It travels inside the order, not as
   a `place_order` argument, so `place_orders` tags each order separately and no method
   signature changes.
2. Venues with a native client order ID send the string unchanged: no validation,
   hashing, prefixing or truncation. The venue's format and uniqueness rules apply, and
   a value breaking them raises the venue's usual error.
3. Venues without one ignore the key. So do venues whose only such field is the SDK's own
   order ID (dYdX, Lighter). The ID does not change how an order executes, so ignoring it
   does not place a materially different order.
4. `Trade` gains `order_id` and `client_order_id`, both `str | None` and defaulting to
   `None`. `order_id` uses the representation of `OrderResponse.id` and `OrderState.id` on
   that venue. `client_order_id` is what the venue reports, including IDs it generated for
   orders placed without one. Either is `None` when the fill payload does not carry it.
5. Implementations fill both from the fill payload they already read. They make no extra
   requests per fill.
6. `Market.client_order_id()` is a sync method generating a fresh ID in the form that
   market's `place_order` sends, or returning `None` where the market ignores the IDs.
   `None` is the base class default, so only markets that send IDs override it. Each
   venue owns its form: 32 random hex digits on most, `0x` and 32 hex digits for
   Hyperliquid's `cloid`, a UUID on Coinbase.
7. `Order['client_order_id']` accepts `None`, meaning the same as leaving it out, so the
   generator's result goes into the order unchecked and portable code does not branch.
8. The generator lives on `Market` only. Neither the routing roots nor `Exchange` expose
   it; callers resolve the market first.

## Alternatives considered

- A `client_order_id` keyword on `place_order`: one ID per call. `place_orders` would need
  a parallel list, and every routing layer and venue signature would change.
- The name `user_id`: on a `Trade` it reads as the account or user that traded.
- SDK-side mapping onto restrictive formats, such as hashing into Hyperliquid's 16-byte
  `cloid`: fills would then report the mapped value rather than the caller's string, or
  the SDK would have to persist a mapping.
- Raising where a venue lacks client order IDs: this would make portable code branch per
  venue for an informational field. Callers see the missing support as `None` on fills and
  in the venue table.
- `OrderState.client_order_id`: not needed to attribute fills. It stays outside this
  decision.
- One universal generated form, such as `0x` plus 32 hex digits for every venue: it fits
  today's trading venues, but not Kraken's `cl_ord_id` (a UUID or at most 18 characters),
  and gives no way to tell which markets ignore the IDs.
- A format field on `Rules` (`'hex'`, `'0x-hex'` or `None`) with a generator method
  deriving the value from it: every new venue form, such as an integer ID, would extend a
  core `Literal` and need an SDK release. Formats belong to venues.
- An abstract generator on `Rules`: every venue would have to return a `Rules` subclass,
  and since `Rules` crosses JSON boundaries such as the engine gateway, the method would
  not survive a round trip.
- A default generator raising `NotImplementedError`: portable code would have to catch it,
  though ignoring an ID changes nothing about execution (decision 3).

## Consequences

Existing `Trade` and `Order` constructors keep working. Venue packages that set the new
fields need the SDK version containing them, so their floors rise when they are released.
The per-venue behaviour table in
[Your First Order](../../docs/market/first-order.md#tag-it-with-your-own-id) is
hand-maintained, since `impl.toml` does not describe it.

Read-only live suites place no orders, so they do not cover placement. A live round trip
per venue, from placement to a fill carrying both IDs, remains to be recorded.
