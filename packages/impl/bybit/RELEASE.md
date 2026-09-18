# tribulnation-bybit 0.2.2

Bybit earn instruments now leave the optional `id` unset (`None`). Native
`productId` values are reused across savings and staking products, including
different fixed terms, and cannot serve as unique SDK instrument identifiers.
All other product fields remain unchanged.

Consumers should handle absent IDs using their own product identity policy.
Consumers that persisted the previous IDs should reconcile their existing keys
when upgrading to avoid retaining stale rows.

Requires tribulnation-sdk >=2.0.2. See SDK issue #67.
