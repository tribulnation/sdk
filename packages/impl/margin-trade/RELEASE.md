# tribulnation-margin-trade 0.1.0

Requires SDK >=2.18.0 (account routing needs the SDK release carrying the
`margin-trade` accounts) and typed-margin-trade >=0.1.0.

New:

1. Market: spot (`PRL/USDC`) and USDC-margined perpetuals, public data, account reads by
   address, and trading with the master's or an approved agent's key (verified on
   testnet).
2. Report: perp and spot wallet snapshots; history of fills, funding and transfers.
