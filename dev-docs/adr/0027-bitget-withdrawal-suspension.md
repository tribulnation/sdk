# ADR 0027: Dated exclusion for Bitget's venue-wide withdrawal suspension

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted; implementation and release qualification remain separate.
2. Date: 2026-09-25
3. Amends: [ADR 0013](0013-all-read-suites-release-gate.md), for one Bitget check only.

## Context

Bitget suspended all withdrawals after detecting unauthorized transfers from some
of its wallets at 18:31 UTC on 2026-09-24
([notice](https://www.bitget.com/support/articles/12560603896025)). Deposits and
trading continue. No resumption date has been announced.

Bitget's credential-free `GET /api/v2/spot/public/coins` has since reported
`withdrawable: false` for every one of its 4,930 chains. The adapter correctly
omits non-withdrawable chains, so `withdrawal_methods()` returns an empty list and
`wallet.test_withdrawal_methods_not_empty` fails. That observation reflects the
venue's state, not an adapter defect. It blocks every core SDK release, including
changes that do not touch Bitget code.

## Decision

Exclude exactly `wallet.test_withdrawal_methods_not_empty` for venue `bitget`, with
the code `venue_withdrawals_suspended`, through 2026-10-09 UTC inclusive.

1. `wallet.test_withdrawal_methods_can_be_fetched` and every other Bitget read suite
   and Market consistency check remain required and must pass.
2. The excluded check is not executed and may not be recorded as passed, failed or
   skipped. Report summaries state the exclusion.
3. The exclusion lapses automatically after its last day: the verifier then requires
   the check again, so reports recorded with it stop verifying. Extending it needs
   a new ADR. Remove it once Bitget resumes withdrawals.
4. No other venue, surface or check is affected, and the verifier does not infer
   suspensions from observed data.

## Consequences

Core SDK releases can proceed during the suspension with visibly narrower Bitget
Wallet evidence. Bitget withdrawal-method coverage is unverified while the exclusion
applies. Because the verifier itself changed, all read-suite and consistency reports
must be recorded again against the new candidate.
