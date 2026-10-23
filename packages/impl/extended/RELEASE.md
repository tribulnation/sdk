# tribulnation-extended 0.1.0

Requires SDK >=2.20.0 (the release carrying `accounts.Extended` and the `extended`
Market/Report routing) and typed-extended >=0.2.0.

New:

1. Market: USD-collateral perpetuals, market ids by name (`BTC-USD`). Public data,
   account reads with a sub-account's API key, and trading with its Stark private key
   and vault (verified on testnet). Orders on RFQ markets go through the venue's RFQ
   endpoint; resting orders last until the network's longest expiry; off-grid prices or
   sizes raise before signing; coded refusals raise `OrderRejected` (ADR 0043).
   `cancel_open_orders` cancels exactly what `open_orders` lists (open `LIMIT` orders),
   leaving conditional, TP/SL and TWAP orders in place. Funding payments are
   received-positive (verified on testnet).
2. On RFQ markets `depth` and `depth_stream` are the tradable RFQ quotes, while ticker
   bid and ask are the venue's indicative book (ADR 0048).
3. Report: snapshots and history of the API key's own sub-account: balances, the `USD`
   collateral and open positions; transfers between sub-accounts, deposits,
   withdrawals, testnet faucet claims, fills, closed positions and funding. History
   raises `NotImplementedError` for a borrow-interest payment or a fill with a builder
   fee, whose semantics are not yet observed.

Caution: Extended does not keep client order ids unique, and every `place_order` signs a
fresh nonce, so resubmitting an order after an uncertain failure can place it twice.
The SDK never retries order placement; check `open_orders` or `query_order` before
resending.

Release qualification uses the read-only mainnet API key (`private` mode); the evidence
is under `release-evidence/extended/`. This adapter release follows SDK 2.20.0
publication.
