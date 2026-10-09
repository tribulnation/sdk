# Local SDK evidence: binance

Run completed: 2026-10-09T19:59:31.072815+00:00

This records a trusted local run, not cryptographic proof. Release policy must separately validate required check coverage and statuses.

Waived account reads: declared reads the qualification account cannot observe, recorded as skips that do not block release. A waived read that passed means its waiver may be stale. See impl.toml and ADR 0042.

- `market.test_account_read["usdm:BTCUSDT", "fees"]`: waived:credential_scope, skipped
