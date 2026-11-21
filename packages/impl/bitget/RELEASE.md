# tribulnation-bitget 0.15.0

Requires SDK >=4.3.0 (was >=4.1.0: `MarginExchange`, the `margin` market kind and `InterestPayment`, [ADR 0073](../../../dev-docs/adr/0073-spot-margin-market-kind.md)) and typed-bitget >=0.6.2, unchanged.

Added:

1. A `margin` exchange: UTA cross spot margin (category `MARGIN`), e.g. `bitget:margin:LITUSDT`, a `MarginMarket` of kind `'margin'`. `exchanges()` lists it as `{'id': 'margin', 'type': 'margin'}`; its `markets()` are the public `MARGIN` instrument catalogue. Book, tickers and candles are the spot pair's; `rules()` reads the `MARGIN` instrument rows.
2. Trading on `margin`: `LIMIT`, `POST_ONLY` and `MARKET` orders, cancel, cancel-all, `query_order`, open orders, fills history and the fills stream. A sell of more base than the pool holds auto-borrows the rest at placement and buys repay debt first. Bitget takes no `reduceOnly` on margin, so `settings['bitget']['reduce_only']` raises `NotImplementedError`; `replace_order` always cancels and places anew.
3. `margin` account reads: `position()`/`delta()` are the pool's net holding of the base coin (`balance + locked`, negative when borrowed and sold, accrued interest included), the same figure on every margin pair of the coin; `collateral()` is the unified pool and `collateral_id()` `<account>:usdt`; `leverage()` is the pair's cross `MARGIN` setting, else 1.
4. `interest_payments(start, end)` on `margin` markets: the borrow interest on the base coin, from the UTA ledger's `INTEREST_SETTLEMENT_OUT` rows (every category, deduplicated by ID, 30-day windows), negative and in the coin's units. One pair per coin reports it (the USDT-quoted one, else the first symbol). `MarginExchange.interest_payments(None, start, end)` lists every coin the pool owes, USDT included.

Changed:

1. On a UTA, `spot` markets' `position()` is what the pool owns of the coin, `balance + locked + debt` (behaviour change): a borrowed-and-sold short reads 0 on spot instead of minus its size, so it is not counted on both `spot` and `margin`, and coins locked in resting orders now count, as on Classic.

Known limitation:

1. `interest_payments` is not verified live. On 2026-11-21 a 548.2 LIT margin short's debt grew by its hourly interest, yet Bitget's ledger showed no `INTEREST_SETTLEMENT_OUT` (nor any other) row, so the read answered empty. Bitget may book the settlement later (daily, or on repayment) or not at all; until a row is seen, `interest_payments` may answer empty while interest accrues into the debt, and the debt (`position()`) is the only record.
2. Classic accounts raise `NotImplementedError` on every `margin` account read and order. The gateway does not carry `interest_payments` (SDK 4.3.0).

Every other method is unchanged.
