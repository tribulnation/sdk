# Architecture Decision Records

[Developer documentation](../README.md)

ADRs preserve the reasoning behind public contracts, architecture, guarantees,
policy, and significant tradeoffs in the SDK and its development tools. They are
not a changelog or a substitute for API documentation and tests.

## Recording a decision

1. Copy [0000-template.md](0000-template.md), use the next four-digit number and a
   descriptive filename, and add a row to the index below.
2. Record the context, decision, alternatives, and consequences. Use `proposed`
   while a decision needs approval, and `accepted` once agreed. Acceptance does
   not assert that implementation, live verification, or release is complete.
3. Preserve accepted decisions and their rationale. A changed decision gets a new
   ADR; update the old record's status and the index with the superseding or
   amending link. Editorial corrections may clarify, but must not change the decision.
4. Link relevant records from implementation PRs and contributor documentation.
   Keep credentials, account records, and private operational details out of ADRs.

## Index

| Number | Decision | Status |
| --- | --- | --- |
| [0001](0001-public-rules-and-account-fees.md) | Separate public market rules from quoted account base fees | Superseded by 0002 |
| [0002](0002-combined-side-specific-fees.md) | Combined maker/taker and buy/sell rates, without optional payment discounts | Accepted |
| [0003](0003-local-consistency-release-evidence.md) | Local consistency checks and offline release evidence | Accepted |
