# tribulnation-nado 0.1.0

First release. Requires SDK >=4.1.0, typed-nado >=0.1.0 and typed-core >=0.14.

1. Market: Nado's USDT0-settled perpetual and spot markets (support `partial`): reference data, books and streams, rules, tickers, funding and candles, and account reads keyed by the owner's `address` alone (Nado's reads are public). With the EIP-712 `private_key` (the owner's or a linked signer's) it also places and cancels orders.
2. `remaining_position_limit()` reads `max_open_interest_x18` less the gateway's open interest.
3. Report: `snapshot()` from the subaccount's address.
4. Accounts `nado` and `nado_testnet` in the SDK (`NADO_ADDRESS`, `NADO_PRIVATE_KEY`, `NADO_SUBACCOUNT`).
