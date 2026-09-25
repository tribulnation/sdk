# Aster testnet inconsistencies

Observed on 2026-09-25 through `typed-aster==0.1.0` with response validation enabled.
These responses validate against the typed declarations; they are recorded separately
from the typed-client schema and pagination defects in `../../../typed-client-issues.md`.

## Spot account information omits funded balances

1. `futures.wallet.transfer(250 USDT, kind_type='FUTURE_SPOT')` succeeded with
   transfer ID `2209013`. The spot cash ledger confirms the 250 USDT credit, and
   the futures USDT balance decreased by the same amount.
2. Spot orders were accepted and filled. For example, order `1349336727` bought
   13.98 ASTER; the ledger reports `TRADE_SOURCE=-10.210992 USDT`,
   `TRADE_TARGET=13.966719 ASTER` and `COMMISSION=-0.013281 ASTER`.
3. `spot.account.info()` nevertheless returned `balances=[]` repeatedly, including
   after new buys and sells and several minutes later. The native WebSocket emits
   nonzero `outboundAccountPosition.B` balances during these same operations.
4. Blocks: `poc/market/spot.py` cells 14 (`position`) and 15 (`collateral`), and
   `poc/report.py` cell 3 (`snapshot`). Returning zero or a partial snapshot would
   hide known holdings. No balance is reconstructed from trade or cash history.
5. Reproduce using spot lifecycle cell 21; its local output includes
   `account_after_buy`, `account_after` and the validated fill events. The report
   snapshot cell also contrasts the empty balance list with the transfer receipt.

## Spot trade history omits confirmed buy fills

1. The buy above has native trade ID `30454527`. It is present in the execution
   stream and commission ledger but absent from `spot.trade.user_trades`, even
   when queried by its order ID, an explicit time range, or an earlier `from_id`.
2. The subsequent sell, trade `30454644`, is returned. Repeating the lifecycle
   produced buy `30454725` and sell `30454727`: only the sell appeared in REST
   history after twenty checks over ten seconds. The account information remained
   empty as well. This is an observed buy/sell correlation, not an established cause.
3. Blocks: `poc/market/spot.py` cell 12 (`trades_history`). Cell 21 retains each
   streamed fill and lists missing REST IDs. It checks all mapped fields against
   REST for the fills that are returned; it does not replace missing history with
   a local WebSocket cache.
4. Spot cell 23 independently reproduces the typed paginator's exclusive-filter
   error after two sell fills. Fixing pagination alone will not restore the missing buys.

## Other testnet limits

1. `futures.wallet.withdraw_info()` returns venue error `-1000` or a gateway
   timeout. `poc/wallet.py` cell 6 retains the current narrowed response.
2. Funding payments remain empty: the test positions were closed before their
   scheduled funding settlement. The endpoint was called, but a nonzero payment
   has not been verified.
3. Standard rules use the documented default fee asset. Actual fill fees retain
   the native asset: futures fees were paid in ASTER; spot buy fees in ASTER and
   sell fees in USDT. Tests compare those fields directly instead of assuming USDT.
4. Spot order queries can briefly return not-found or stale state immediately
   after placement or a confirmed streamed fill. During SDK qualification, one
   filled order became visible after three 200 ms polling intervals. Tests wait
   for native REST confirmation; the SDK returns each actual query result without
   caching or inventing an order state.
