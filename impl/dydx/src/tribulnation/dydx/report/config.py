"""dYdX reporting configuration types."""

from typing_extensions import Literal, TypedDict

class DydxNodeConfig(TypedDict, total=False):
  """dYdX mainnet node endpoint configuration."""
  comet_base_url: str
  """Default: `DYDX_COMET_RPC_URL` or the bundled archive RPC URL.
  - Used for Comet RPC history, transaction search, and block queries."""
  grpc_host: str
  """Default: `DYDX_GRPC_HOST` or the bundled archive gRPC host.
  - Used for Cosmos module queries such as bank, staking, and distribution."""
  grpc_port: int
  """Default: `443`.
  - gRPC port for the selected dYdX node."""
  grpc_ssl: bool
  """Default: `True`.
  - Enables TLS for gRPC connections."""
  validate: bool
  """Default: `True`.
  - Enables typed-dydx response validation."""

class DydxHistorySourcesConfig(TypedDict, total=False):
  """Source selection for each dYdX history bucket."""
  fills: Literal['indexer']
  """Default: `indexer`.
  - `indexer`: Seconds, free. Preferred user-facing fill source."""
  subaccount_transfers: Literal['indexer', 'node', 'bigquery']
  """Default: `indexer`.
  - `indexer`: Seconds, free. Preferred subaccount transfer source.
  - `node`: Direct deposit, withdrawal, and create-transfer Comet event queries.
  - `bigquery`: About `1.8s`, `$0.001` via deposit, withdrawal, and transfer tables."""
  funding: Literal['node', 'bigquery']
  """Default: `node`.
  - `node`: About `5.8s` via `settled_funding.subaccount`.
  - `bigquery`: About `2.4s`, `$0.03` via `dydx_settled_funding`."""
  chain_fees: Literal['node']
  """Default: `node`.
  - `node`: About `1.1s` via `tx.fee_payer`."""
  staking: Literal['node', 'bigquery']
  """Default: `node`.
  - `node`: About `0.4s` to `1.1s` via signed wallet and staking event queries.
  - `bigquery`: About `1.9s`, `$0.0003` via `dydx_delegate`, `dydx_undelegate`, and `dydx_message_events`."""
  trading_rewards: Literal['bigquery']
  """Default: `bigquery`.
  - `bigquery`: About `2.0s`, `$0.08` via `dydx_reward_distribution`."""
  community_treasury_distributions: Literal['governance', 'bigquery', 'disabled']
  """Default: `governance`.
  - `governance`: Governance proposal REST plus archive confirmation.
  - `bigquery`: Broad raw scan, about `$1.1`.
  - `disabled`: Skip community treasury distributions."""
  megavault: Literal['node', 'bigquery', 'disabled']
  """Default: `node`.
  - `node`: Less than `1.4s` via signed wallet transactions or Megavault action queries.
  - `bigquery`: About `1.4s`, `$0.6` via `dydx_message_events`.
  - `disabled`: Skip Megavault transfers."""
  ibc_wallet_transfers: Literal['node', 'bigquery', 'disabled']
  """Default: `node`.
  - `node`: Outbound via `tx.fee_payer`; inbound via `fungible_token_packet.receiver`.
  - `bigquery`: About `1.7s`, `$0.7` via `dydx_message_events`.
  - `disabled`: Skip IBC wallet transfers."""
  wallet_transfers: Literal['bigquery', 'disabled']
  """Default: `bigquery`.
  - `bigquery`: Generic unmatched wallet-level transfer events via `dydx_message_events`.
  - `disabled`: Skip unmatched wallet transfer fallback records."""

class DydxConfig(TypedDict, total=False):
  """dYdX reporting configuration."""
  node: DydxNodeConfig
  """dYdX mainnet node endpoint configuration."""
  sources: DydxHistorySourcesConfig
  """History source configuration by data bucket."""
