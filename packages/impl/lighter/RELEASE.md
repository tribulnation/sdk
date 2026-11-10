# tribulnation-lighter 0.13.1

Requires SDK >=4.0.0 and typed-lighter >=0.3.0, unchanged.

New:

1. The remaining volume quota of a Premium account, which every `sendTx` and `sendTxBatch` reply reports (`volume_quota_remaining`), is logged on the `tribulnation.lighter.quota` logger as `Lighter volume quota remaining: <n> (<account>)`. It logs at INFO the first time, then every 10 minutes or once it moved by 500. Below 2,000 it logs at WARNING (`..., below 2000)`) as soon as it drops there, then at most once a minute. Replies without a quota (the free transaction every 15 seconds) are ignored. Order replies through the batcher and the perpetual `cancel_open_orders` count. `tribulnation.lighter.quota` holds the defaults.

Every method is unchanged.

Release qualification on 2026-11-10 passed the read suites and market consistency.
Committed evidence under `release-evidence/lighter/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes.
