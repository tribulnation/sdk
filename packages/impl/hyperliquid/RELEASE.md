# tribulnation-hyperliquid 0.20.0

Requires SDK >=4.0.0 (`place_orders` results per order, `replace_order(s)` and `OrderNotFound`, [ADR 0059](../../../dev-docs/adr/0059-replace-orders-and-order-not-found.md)) and typed-hyperliquid >=2.6.0, unchanged. Upgrade the SDK and this adapter together: this adapter does not work with SDK 3.

Breaking and behaviour changes:

1. `Rules` carry the venue's 5-significant-figure grid (`sig_figs=5`), and `tick_size` is the documented finest step, `10^-(max decimals - szDecimals)`, without the old cap at 5 decimals: finer for prices below 0.1.
2. An order price off the grid (`Rules.valid_price`) raises `ValueError` before signing. It used to be rounded half-up silently; round with the market's `Rules`.
3. `replace_orders` sends `POST_ONLY` entries in one `batchModify`; other entries cancel, then place. An entry whose old order is gone is placed afresh; one refused after the cancel (`Error placing new order during modify:`) is `OrderRejected`; any other entry error is `ApiError`.
4. A cancel of a gone order raises `OrderNotFound`.

Every other method is unchanged.

Release qualification on 2026-11-03 passed the read suites and market consistency.
Committed evidence under `release-evidence/hyperliquid/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes. This adapter
release follows SDK 4.0.0 publication.
