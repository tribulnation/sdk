<!-- github-only -->
<table><tr>
<td align="center"><a href="../index.md">Docs</a></td>
<td align="center"><b>Market</b></td>
<td align="center"><a href="../earn/index.md">Earn</a></td>
<td align="center"><a href="../wallet/index.md">Wallet</a></td>
<td align="center"><a href="../report/index.md">Report</a></td>
<td align="center"><a href="../reference/index.md">Reference</a></td>
<td align="center"><a href="https://tribulnation.com/sdk/docs/support">Support matrix</a></td>
</tr></table>
<!-- /github-only -->

# Market Identifiers

A market is addressed by a colon-delimited string, parsed left-to-right, one segment per
scoping level:

```
<account_id>:<exchange_id>:<market_id>
     |             |            |
     |             |            +-- the venue-native instrument identifier, e.g. `BTCUSDT`
     |             |
     |             +-- the product category within the venue, e.g. `spot`, `perp`, `usdm`, etc.
     |
     +-- the account key you registered in `accounts`, e.g. `dydx-1`, `mexc_account1`
```

For example, say you have this `sdk.toml`:

```toml
[accounts.mexc_account1]
venue = "mexc"

[accounts.hl]
venue = "hyperliquid"

[accounts.binance] # already exists by default
venue = "binance"
```

Then the following are valid market identifiers:

- `hl:spot:HYPE/USDC:107`: a spot market on Hyperliquid
- `hl::BTC-USD`: a perpetual market on Hyperliquid's default DEX (`''`)
- `hl:xyz:xyz:CL`: a perpetual market on Hyperliquid's `xyz` DEX
- `mexc_account1:spot:BTCUSDT`: a spot market on MEXC (with a custom account name `mexc_account1`)
- `binance:usdm:ETHUSDC`: a USD-M perpetual market on Binance

See the [venue-specific guidance](implementations/index.md) for full details.

Venues, exchanges and markets report their own IDs, which round-trip through the SDK
that opened them (`(await sdk.market(market.id)).id == market.id`):

| Attribute | Example (account `hl`) | Meaning |
| --- | --- | --- |
| `market.id` | `hl::BTC-USD` | `<account_id>:<exchange_id>:<market_id>` |
| `exchange.id` | `hl:` | `<account_id>:<exchange_id>` |
| `venue.id` | `hl` | the account key |
| `account_id` | `hl` | the account key the object was opened under |
| `venue_id` | `hyperliquid` | the venue, the same for every account on that venue |

Two accounts on the same venue therefore report distinct IDs and the same
`venue_id`. A venue constructed directly from its package, outside `MarketSDK`, has
no account key: its `account_id` is its `venue_id`.

`venue_id` is a `VenueId` (`from tribulnation.sdk.impl.accounts import VenueId`): the
`venue` of the account the object was built from. Testnets are separate venues, so an
account with `venue = "hyperliquid_testnet"` reports `venue_id == 'hyperliquid_testnet'`.
Venue-specific `settings` stay keyed by the venue's package name
(`{'hyperliquid': {...}}`) and apply on its testnet too.

Shorter forms work once you have scoped down on a venue: let's see this next.

<!-- next -->

---

← [Market](index.md) · **Next:** [Hierarchy & Scoping](hierarchy.md) →

<!-- /next -->
