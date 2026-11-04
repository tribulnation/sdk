# tribulnation-bitget 0.13.0

Requires SDK >=4.0.0 and typed-bitget >=0.4.1, unchanged. This adapter is read-only, so the SDK 4.0 order changes ([ADR 0059](../../../dev-docs/adr/0059-replace-orders-and-order-not-found.md)) do not change its behaviour; it is released with SDK 4.0 and its evidence.

New on Unified Trading Accounts (UTA), which used to raise `NotImplementedError`:

1. `deposit_methods()` and `withdrawal_methods()` read the public coin list (`/api/v2/spot/public/coins`), as on a Classic account: the endpoint serves both modes.
2. `instruments()` lists the open on-chain Elite products (`/api/v3/earn/elite-product`), the only earn products the UTA API lists: one `staking` instrument per subscription coin, with `yield_asset` the product's coin, `apr` its minimum APR (Bitget quotes a range), `min_qty` the coin's minimum subscription, `max_qty` its remaining quota and `id` the product ID. Sold-out products are left out. Classic accounts keep reading savings products.

Release evidence is now recorded with the UTA account ([ADR 0060](../../../dev-docs/adr/0060-bitget-qualifies-uta.md)).

Every other method is unchanged.
