# SDK 2.2.0 qualification blocker

On 2026-09-19, two fresh full consistency runs observed native `spot:A1X/USDC`
ticker bid/ask `0.0` against a one-sided depth book: bid absent, ask `0.0005999`.
Each run captured three timely, exact-ID brackets with the same discrepancy.
The committed consistency report retains the second run as a failed `mismatch`.
All Bit2Me read-suite cases passed.

[ADR 0014](../../dev-docs/adr/0014-bit2me-native-ticker-limitation.md) requires
positive, non-crossed two-sided books for its native-ticker exception. This
observation is outside that exception and blocks SDK 2.2.0 publication under the
current policy. Deribit public Market qualification passed independently.

The SDK preserves Bit2Me's native values. No ticker was derived from depth, no
sample was removed, no tolerance was widened, and no result was relabeled.
A future fresh run must satisfy the existing policy, or a separately reviewed
policy decision must address this new observation shape before release.
