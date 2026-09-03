<!-- github-only -->
<table><tr>
<td align="center"><a href="../../index.md">Docs</a></td>
<td align="center"><a href="../../market/index.md">Market</a></td>
<td align="center"><a href="../../earn/index.md">Earn</a></td>
<td align="center"><a href="../../wallet/index.md">Wallet</a></td>
<td align="center"><b>Report</b></td>
<td align="center"><a href="../../reference/index.md">Reference</a></td>
<td align="center"><a href="https://tribulnation.com/sdk/docs/support">Support matrix</a></td>
</tr></table>
<!-- /github-only -->

# Ethereum Report

HyperEVM mainnet uses the `hyperevm` network id and chain id `999`. Its default
history provider is Etherscan and its default snapshot provider is Alchemy. Set
`HYPEREVM_RPC_URL` to override the RPC used for transaction and receipt lookups.

## Snapshots

- `node`: requires passing assets, otherwise only returns native balance
- `alchemy`: supports native and all ERC-20 balances, including HyperEVM

## History

- `etherscan`: free for Ethereum, Arbitrum, Polygon and HyperEVM
- `alchemy`: only supports internal transactions for Ethereum and Polygon (others work but may be incomplete if you have internal transactions)
- `moralis`: supports all networks

<!-- next -->

---

← [dYdX Report](dydx.md) · **Next:** [Reference](../../reference/index.md) →

<!-- /next -->
