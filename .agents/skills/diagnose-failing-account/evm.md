<!-- vendored from workspace/.agents/skills/diagnose-failing-account/evm.md — do not edit; run `python scripts/sync.py agents` -->
# evm: diagnosing a failing address

Repo `litmus-tax/evm`, DB `litmus_evm`. Spec: `specs/docs/policies/03-unit-contract/units/evm/index.md`
(Rule 15 discovery and nonce gaps, Rule 19 rebasing, Rule 20 residuals; subpages `discovery.md`,
`verification.md`, `catalogue.md`, `spam.md`).

## Where the audit lives

1. **Account → resources.** One account = one address = **one resource per network**. Check every
   network; one failing network fails the account.
   - API: `GET /v1/portfolio/portfolios/{p}/accounts/{account}` (resources + coverage),
     `GET /v1/evm/resources` (`name`, `binding.address`, `binding.network`).
   - DB: `litmus_portfolio`: `SELECT account, resource_id, network FROM account_resources WHERE unit='evm'`;
     `litmus_evm`: `SELECT name, resource_id, binding, version, synced_at FROM litmus_resources`.
     Bindings may be EIP-55 checksummed; working tables key the address lower-case.
2. **Served audit** `GET /v1/evm/resources/{r}/verification`. Checkpoints are per
   `(wallet|debt:<pool>|…, <network>:asset:<native|contract>)`, tolerance `0` (balances at height are
   exact). `detail`: `discovery.{families, failed}`, `history_complete`, `unrecomputable_checkpoints`,
   `head_height`, `accrual_schedule`, `evidence_levels`.
   An interval is:
   1. `failed` if one of its checkpoints failed;
   2. `unassessable` if a checkpoint was unreadable, discovery could not attest the range, or a
      `discovery_gap` item falls inside it.
3. **Items** `GET /v1/evm/resources/{r}/items`. The ones that matter: `evm.discovery_gap` (error),
   `evm.verification_mismatch` (error), `evm.unknown_leg`, `evm.unknown_record`, `evm.unknown_kind`,
   `evm.partial_match`, `evm.unexplained`, `evm.budget_exceeded`. Ignore `evm.spam`/`evm.unsolicited`
   (info) unless a real token is judged spam.
4. **Working tables (DB only)**: `source.checkpoints.content` (`verdict`, `mismatches`,
   `compared[{expected_raw, actual_raw, outcome}]`, `unattested`, `rebasing`), `source.items`,
   `source.evidence` (kinds `tx`, `balance:…`; no address column — join through the resource),
   `source.address_txs`, `source.discovery` (per feed/provider status).
   A working checkpoint `verdict=failed` with "N open classification items" is **internal**, not
   served: report its items as classification residuals, not as an audit failure.

```sql
-- sent txs of a resource (nonce, type, block, authorizations)
SELECT e.content->>'nonce', e.content->>'type', e.content->>'blockNumber', e.content->>'hash',
       e.content->'authorizationList'
FROM source.evidence e JOIN litmus_resources r USING (tenant_id, resource_id)
WHERE r.name = :'res' AND e.kind = 'tx' AND lower(e.content->>'from') = lower(r.binding->>'address');

-- discovery feeds
SELECT network, feed, provider, content->>'status', left(content->>'error', 200), count(*)
FROM source.discovery GROUP BY 1, 2, 3, 4, 5;

-- all retained txs, for offline replay of a fix
SELECT json_build_object('name', r.name, 'address', lower(r.binding->>'address'), 'height', a.height, 'tx', e.content)
FROM source.address_txs a JOIN litmus_resources r USING (tenant_id, resource_id)
JOIN source.evidence e ON e.tenant_id = a.tenant_id AND e.resource_id = a.resource_id
  AND e.kind = 'tx' AND e.content->>'hash' = a.tx;
```

## Signatures

| Signature | Cause | Class | Action |
|---|---|---|---|
| `unassessable`, `evm.discovery_gap` for nonce `n`, address has 7702 code (`eth_getCode` = `0xef0100…`) | An EIP-7702 **authorization** consumed the nonce (own type-4 tx: auth nonce = tx nonce + 1; or a relayer's type-4 tx) | 1 (fixed evm#44; spec specs#45) | A fetching sync (`POST …/sync {}`) runs `nonce-scan` over every open gap window and fetches what it finds (verified 2026-09-29: all gaps of ethereum1-3 closed, base's two reverted self-calls retained) |
| Native `delta` **negative and constant** across checkpoints, equal to a sum of fees | Missed **sent** txs, usually **reverted** self-calls (transfer feeds skip reverted txs) | 1 if the unit could find them (`nonce-scan`, evm#44); 4 if only an explorer key would | Nonce-bisect the gap, match fees to the delta exactly |
| Native `delta` positive | Missed inflows: internal ETH with no working internal-transfer feed (`trace_filter` failing on range caps), bridge claims | 1 (feed config) or 4 (provider) | Check `source.discovery` for the native family |
| Native `delta` negative on an OP-stack chain, ≈ small per tx | `l1Fee` not included in fees | 1 | Check `classify.tx_fee` against the receipt |
| Token `delta` grows over time | Undeclared rebasing (stETH not supported), fee-on-transfer | 2/3 or by design (Rule 19.3) | Read `detail.accrual_schedule`, spec rebasing rule |
| Token `delta` negative, `evm.spam` with `source: lookalike` on a real holding | Spam/poisoning filter dropped real value | 4 (edit) | `asset_verdict mine` |
| `unassessable` with `detail.discovery.failed` covering a whole family (tokens: `logs`, `transfers:erc*`; native: `trace_filter`, `transfers:external|internal`, `node-scan`) | No answering feed for the range | 4 (provider key/budget) or 1 (config) | `source.discovery` errors |
| `crosscheck:etherscan` failed "ETHERSCAN_API_KEY is not set" | Owner config; does not block by itself, but it is the feed that lists reverted txs | 4 | Owner sets the key |
| `crosscheck:etherscan` failed "Free API access is not supported for this chain" | The Etherscan free plan covers ethereum, arbitrum, polygon and hyperevm, but not base (8453), optimism (10), avalanche (43114) or bnb (56) | 4 | Paid plan if those chains need the crosscheck; not blocking |
| `evm.budget_exceeded` | Provider budget exhausted | 4 | Raise budget / resync |
| `evm.unknown_kind` on a known protocol contract; value booked as plain `transfer` | Uncatalogued contract instance (e.g. Skip Go Fast on avalanche, evm#45; Aster `AstherusVault`, Relay `RelayDepository`, ZkLighter, Lighter FastCCTP catalogued by evm#51) | 1 | Add catalogue instance + real-tx fixture |
| `partial_match`/`unexplained` on a self-sent tx, selector `0xe9ae5c53` | ERC-7821 batch through a 7702 delegate (wallet swap) | 1 (decoder/catalogue gap) | — |
| `evm.unknown_leg` of exactly 1 base unit on loans (Aave v3) | Protocol ray rounding | 3 (spec issue on Rule 20) | — |
| `/unmatched`: a bridge initiate on one network and its claim on another, **same account**, the only reason `same_account` | One evm account is one address on every network, but policy 01 portfolio Rule 1 links only different accounts, and no single evm resource sees both sides (no `counterpart`). 74 pairs on `personal` (2026-09-30) | 2 (specs#65) | None until the rule changes; a record received and re-sent on the **same** network is not such a pair |
| Small USDC `evm.transfer` out to `0xe3478b0B…1964`, in a tx the address did not send: a relayer (`0xB42F812A…`, `0xC066ac5D…`) calling MetaMask `DelegationManager` `0xdb9B1e94…` `redeemDelegations`; the address's code is `EIP7702StatelessDeleGator` | MetaMask gasless transaction: the address pays the relayer's gas in a token. Served as a transfer, so it is an unmatched withdrawal | 3 (specs#66) | Not a transfer; leave it until the rule lands (or `classify_boundary`) |
| CCTP v2 `evm.bridge_claim` with `endpoints.source` / portfolio `src_network` null outside hyperevm | v2 MessageTransmitter `0x81d40f21…` not catalogued there, and its `MessageReceived` had no decoder | 1 (evm#57) | Re-derive after deploy |

## Ground truth

1. **Balances**: the retained `balance:` evidence is the chain read at height. Re-read it through a
   public RPC (`eth_getBalance` / `balanceOf` via `eth_call` at the height) or Blockscout
   (`coin_balance`, `block_number_balance_updated_at`).
2. **Sent txs**: Blockscout `https://<chain>.blockscout.com/api/v2/addresses/<addr>/transactions`
   (`nonce`, `status`, `fee.value`, `proxy_type`). Missing nonces there + a 7702 proxy type → relayed
   authorizations.
3. **Who consumed nonce `n`**: `scripts/nonce_bisect.py <rpc> <address> <n> <lo> <hi>` bisects
   `eth_getTransactionCount` and prints the block's txs from the address or carrying an
   authorization. Cost ≈ log2(hi−lo) archive reads.
4. **Authority of an authorization**: `ecrecover(keccak(0x05 || rlp([chainId, delegate, nonce])),
   yParity, r, s)`, or `litmus.evm.domain.delegation.authority` (evm ≥ #44).
5. **Contract identity**: Blockscout/routescan `/api/v2/addresses/<c>` (`name`, `implementations`),
   4byte.directory for selectors.
6. **Where a claim came from**: the claim tx's `MessageReceived` (CCTP) gives `sourceDomain`
   (6 base, 3 arbitrum, 0 ethereum, 19 hyperevm) and the message body the burn token, amount and
   `messageSender` (a router such as the Skip Go entrypoint `0x7e07a914…`). The burn itself is a
   tx to that router on the source chain a minute earlier: Blockscout's Etherscan-style
   `api?module=account&action=txlist&address=<router or owner>&startblock=&endblock=` lists it
   (Base ≈ 2 s per block).
7. **A Lighter `transfer` in from account 508431**: that account's `l1_address` is
   `0xf70da978…dbEF`, Relay's solver (`https://mainnet.zklighter.elliot.ai/api/v1/account?by=index&value=<i>`).
   It is Relay filling a deposit the owner made into `RelayDepository` on some chain seconds
   before; the evm side is a `bridge_initiate` with a null destination (evm#51), and the pair links
   by `bridge_transfers` at 1 min once both are synced. Proof: `https://api.relay.link/requests/v2?hash=<deposit tx>`
   gives `inTxs` and `outTxs` (Lighter is chain `3586256`; its out tx hash is the Lighter record's
   `reference`). Looking up `?id=` with the `RelayErc20Deposit` event's `id` returned nothing
   (2026-09-30; v2 is deprecated for v3, sunset 2026-11-24).
8. **Divergence height**: `litmus-evm debug bisect` (CLI, needs provider keys; never against the
   owner's stack).

## Costs and limits

1. Keyless archive RPCs that answered: `https://mainnet.base.org`,
   `https://arbitrum.gateway.tenderly.co`, and for ethereum `https://eth.drpc.org` (historical
   `eth_call`/`eth_getBalance`). `ethereum-rpc.publicnode.com` is latest-state only, and
   `eth.llamarpc.com` refused. A balance at a wall-clock time: bisect `eth_getBlockByNumber` on
   `timestamp` (~20 reads), then read at that block. An aToken's balance changes every block, so a
   base-unit match also pins a record's timestamp.
2. Aave v3 token addresses: `Pool.getReserveData(asset)` (`0x35ea6a75`), words 8 (aToken) and 10
   (variable debt token); ethereum Pool `0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2`.
3. Rebasing balances between checkpoints: the replay (`…/state?at=`) excludes pending accrual
   (Rule 19), so compare aTokens and debt tokens with the chain, not with the replay.
4. `rediscover` (`POST /v1/evm/resources/{r}/rediscover`, admin) over a window uses `node-scan`,
   capped at 5,000 blocks; the `nonce-scan` feed (evm#44) has no width cap.
5. Offline validation of a fix: export retained txs (query above) and run the new pure functions
   from the worktree (`PYTHONPATH=<worktree>/pkg/src ../platform/.venv/bin/python`), before/after.
