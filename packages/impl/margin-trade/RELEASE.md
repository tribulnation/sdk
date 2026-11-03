# tribulnation-margin-trade 0.3.0

Requires SDK >=4.0.0 (`place_orders` results per order, `replace_order(s)` and `OrderNotFound`, [ADR 0059](../../../dev-docs/adr/0059-replace-orders-and-order-not-found.md)) and typed-margin-trade >=0.1.1, unchanged. Upgrade the SDK and this adapter together: this adapter does not work with SDK 3.

Breaking and behaviour changes:

1. `Rules` carry the venue's 5-significant-figure grid (`sig_figs=5`) and a finer `tick_size`; an off-grid order price raises `ValueError` before signing instead of being rounded half-up.
2. `cancel_orders` returns, per order, the acknowledgement or its error: `OrderNotFound` for a gone order (`order not found`), else an `ApiError` subclass. `cancel_order` of a gone order raises `OrderNotFound`.
3. `replace_orders` sends one `batchModify`; each entry gets a new order ID. An entry whose old order is gone is placed afresh; a post-only replacement that would cross (`Canceled due to post only`) is `OrderRejected`; any other entry error is `ApiError`.
4. Entering a signed venue reads `getUser`'s `masterAccount`: a configured address that is not it raises `AuthError`, an omitted one becomes it.
5. New setting `settings['margin-trade'] = {'limit_tif': 'Gtc' | 'Ioc' | 'Alo'}` sets a `LIMIT` order's time in force (default `Gtc`); `MARKET` and `POST_ONLY` ignore it.

Every other method is unchanged.

Release qualification on 2026-11-03 passed the read suites and market consistency.
Committed evidence under `release-evidence/margin-trade/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes. This adapter
release follows SDK 4.0.0 publication.
