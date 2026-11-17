# ADR 0061: RISEx native candles pass through unordered, as an accepted venue limitation

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted; implemented, not release-verified
2. Date: 2026-11-17

## Context

The live candle suite (`sdk-dev test market`) requires every candle to satisfy
`low <= open <= high` and `low <= close <= high`. RISEx's own candles do not always: the
venue sends some with an `open` or `close` outside the candle's `[low, high]` range. On
mainnet, BTC (`market_id` 1) at 2026-11-13 16:00 UTC opened at `68880.4` with a high of
`68861.8`. Over hourly BTC candles from 2026-11-10 to 2026-11-17, 8 of 168 were
unordered on mainnet and 60 of 144 on testnet. The adapter maps the venue's fields one to
one, so the first mainnet run failed `test_candle_values_are_decimals_and_ordered` on
the venue's data, not on the mapping.

A second sample, the seven days of hourly BTC candles to 2026-11-17 15:00 UTC, found 10
of 168 unordered on mainnet and 59 of 147 on testnet, and in every one the `open`
equalled the previous candle's `close`: the venue appears to carry the open over from
the prior close while `high` and `low` cover only the interval's own trades. It
documents neither, so this is an observation, not a contract the adapter could rely on
to repair the candle.

## Decision

1. The RISEx adapter passes candles through unmodified: `open`, `high`, `low` and
   `close` are the venue's values as sent. It neither widens `[low, high]` to cover
   `open` and `close`, nor clamps `open` or `close` into the range, nor drops the
   candle.
2. This is an accepted upstream limitation, declared on the live suite's candle case
   (`CandleCase.unordered_ohlc`, `packages/sdk-dev/.../market/support.py`) for RISEx's
   `perp:1` case, which `risex` and `risex_testnet` share. With the flag set,
   `test_candle_values_are_decimals_and_ordered` skips only the two `open`/`close`
   bound assertions.
3. Every other candle check still applies to RISEx: Decimal prices, `low <= high`,
   Decimal or missing volumes, and the series checks (timezone, uniqueness, alignment,
   half-open bounds). An inverted `low`/`high` range is still a failure.
4. Every other venue keeps the full ordering check; a unit test pins the flag to RISEx
   alone, so extending it needs its own ADR.
5. The limitation is documented to callers on the RISEx Market page and in its
   `impl.toml` support note.

## Alternatives considered

1. Repair the candle in the adapter (widen `high`/`low`, or clamp `open`/`close`):
   invents a price the venue did not report, and the choice of which value to trust is
   a guess the venue gives no grounds for.
2. Drop unordered candles: leaves holes on a grid the venue does serve, and a caller
   aggregating volume would silently lose it.
3. Record the check as `xfail` or skip: the surface evidence counts either as a skip
   and refuses it, so RISEx could never qualify, and a skip reads as missing coverage
   rather than a reviewed limitation.

## Consequences

RISEx's candle suite passes on mainnet and testnet with the native data, and callers
see the venue's candles exactly as it publishes them; consumers that need ordered OHLC
must handle the unordered rows themselves. The flag is test-side metadata, so the
offline evidence verifiers are unchanged and no other venue's evidence is affected. If
RISEx fixes its candles, the flag should be removed so the full check guards the
regression. Acceptance is not release readiness.
