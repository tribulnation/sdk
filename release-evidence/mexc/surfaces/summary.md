# Local SDK evidence: mexc

Run completed: 2026-10-08T18:21:32.698762+00:00

This records a trusted local run, not cryptographic proof. Release policy must separately validate required check coverage and statuses.

Waived account reads: declared reads the qualification account cannot observe, recorded as skips that do not block release. A waived read that passed means its waiver may be stale. See impl.toml and ADR 0042.

- `market.test_account_read["spot:BTCUSDT", "fees"]`: waived:account_setting, skipped
