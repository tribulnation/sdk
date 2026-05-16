# dYdX Report

## History

dYdX history combines several sources because the indexer, chain node,
governance API, and BigQuery expose different slices of account state. The
report should keep these buckets separate instead of treating every event as a
generic wallet transfer.

### Buckets

- **Fills**: perpetual futures trades
- **Funding**: perpetual funding payments
- **Subaccount Transfers**: deposits to subaccounts, withdrawals from subaccounts, and subaccount-to-subaccount transfers.
- **Chain Fees**: on-chain transaction fees from Comet `tx` events.
- **Staking**: delegate, undelegate, unbond completion, and reward-withdrawal activity.
- **Trading Rewards**: regular DYDX reward distributions.
- **Community Treasury Distributions**: governance-executed `MsgSendFromModuleToAccount` messages.
- **Megavault**: deposits and withdrawals between subaccounts and the Megavault.
- **IBC Wallet Transfers**: wallet-level USDC movements between dYdX and external chains.

### Source Options

| Bucket | Indexer | Archive node | BigQuery | BigQuery cost |
|---|---:|---:|---:|---:|
| Fills | `7.0s` | n/a | n/a | n/a |
| Subaccount transfers | `5.4s` | `tx.fee_payer`, shared signed-wallet scan, `1.1s` | `1.8s` | `$0.001` |
| Funding | n/a | `settled_funding.subaccount`, `5.8s` | `2.4s` | `$0.03` |
| Chain fees | n/a | `tx.fee_payer`, shared signed-wallet scan, `1.1s` | n/a | n/a |
| Staking | n/a | `tx.fee_payer` shared scan, plus `delegate.delegator` / `unbond.delegator` direct checks, `0.4s` to `1.1s` | `1.9s` | `$0.0003` |
| Trading rewards | n/a | n/a | `2.0s` | `$0.08` |
| Community treasury distributions | n/a | governance proposal REST, `0.6s` to `1.2s` per proposal; `block_results` at derived heights | possible through raw events | `$1.1` broad scan |
| Megavault | n/a | `tx.fee_payer` shared scan or `message.sender + message.action`, `<1.4s` | `1.4s` | `$0.6` |
| IBC wallet transfers | n/a | outbound via `tx.fee_payer`; inbound via `transfer.recipient`, `107.9s` | `1.7s` IBC-only, `5.6s` full wallet events | `$0.7` IBC-only, `$0.8` full wallet events |

## Defaults

Prefer the cheapest semantic source per bucket:

1. Use indexer fills and transfers for trading and subaccount movement.
2. Use BigQuery `dydx_settled_funding` for funding.
3. Use archive node `tx.fee_payer` for chain fees and signed wallet activity.
4. Use BigQuery `dydx_reward_distribution` for trading rewards.
5. Use governance REST plus archive confirmation for community treasury distributions.
6. Use archive node `message.sender + message.action` for Megavault.
7. Keep IBC wallet transfers configurable because archive discovery is slow and BigQuery is faster but paid.

Avoid broad raw event scans as defaults. `dydx_block_events` can contain duplicate
raw ingestion rows, and generic transfer-like events overlap with fees, deposits,
withdrawals, `coin_spent`, and `coin_received`.

When archive-node sources overlap, fetch each discovery query once and route
transactions by event type. Deduplicate records by the stable transaction hash
plus event index, not by the source query that found the transaction.
