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

| Bucket | Indexer | Node | Node Cost | BigQuery | BigQuery Cost |
|---|---:|---|---:|---|---:|
| Fills | `7.0s` | n/a | n/a | n/a | n/a |
| Subaccount transfers | `5.4s` | `tx.fee_payer='<address>'` | `1.1s` | `dydx_deposit`, `dydx_withdrawal`, `dydx_transfer` by address | `1.8s`, `$0.001` |
| Funding | n/a | `settled_funding.subaccount='<address>'` | `5.8s` | `dydx_settled_funding` by subaccount | `2.4s`, `$0.03` |
| Chain fees | n/a | `tx.fee_payer='<address>'` | `1.1s` | n/a | n/a |
| Staking | n/a | `tx.fee_payer='<address>'`, `delegate.delegator='<address>'`, `unbond.delegator='<address>'` | `0.4s` to `1.1s` | `dydx_delegate`, `dydx_undelegate` by sender | `1.9s`, `$0.0003` |
| Trading rewards | n/a | n/a | n/a | `dydx_reward_distribution` by recipient | `2.0s`, `$0.08` |
| Community treasury distributions | n/a | governance proposal REST; `block_results` at derived heights | `0.6s` to `1.2s` per proposal | `dydx_block_events` by recipient and treasury sender | broad scan, `$1.1` |
| Megavault | n/a | `tx.fee_payer='<address>'` or `message.sender='<address>' AND message.action='<megavault action>'` | `<1.4s` | `dydx_tx_messages` by message type and address | `1.4s`, `$0.6` |
| IBC wallet transfers | n/a | outbound via `tx.fee_payer='<address>'`; inbound via `transfer.recipient='<address>'` | `107.9s` | `dydx_tx_messages` filtered to IBC receive/send messages | `1.7s`, `$0.7` |

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
