<!-- github-only -->
<table><tr>
<td align="center"><a href="../../index.md">Docs</a></td>
<td align="center"><b>Market</b></td>
<td align="center"><a href="../../earn/index.md">Earn</a></td>
<td align="center"><a href="../../wallet/index.md">Wallet</a></td>
<td align="center"><a href="../../report/index.md">Report</a></td>
<td align="center"><a href="../../reference/index.md">Reference</a></td>
<td align="center"><a href="https://tribulnation.com/sdk/docs/support">Support matrix</a></td>
</tr></table>
<!-- /github-only -->

# Lighter Market

> Perpetuals and spot. `tribulnation-lighter`, venue names `lighter` and `lighter_testnet`.

See the [generic market interface](../index.md) for the shared method surface. This page
covers only what is Lighter-specific.

## Account

The built-in `lighter` account is public: market data works without credentials.
Account and trading methods need an API key registered for the account.

```toml
[accounts.lighter]
venue = "lighter"          # or "lighter_testnet"
account_index = "$LIGHTER_ACCOUNT_INDEX"
api_key_index = "$LIGHTER_API_KEY_INDEX"
api_private_key = "$LIGHTER_API_PRIVATE_KEY"
```

With the fields omitted, `lighter` reads `LIGHTER_ACCOUNT_INDEX`, `LIGHTER_API_KEY_INDEX`
and `LIGHTER_API_PRIVATE_KEY`, and `lighter_testnet` the same names prefixed
`LIGHTER_TESTNET_`. Testnet never falls back to mainnet variables. `validate` toggles
response validation.

## Exchange & ID conventions

- Exchanges are `perp` and `spot`. Market ids are the venue's numeric `market_id`, the
  id orders are signed with: `lighter:perp:1` (BTC), `lighter:spot:2048` (ETH/USDC).
  Symbols are API metadata only. Ids differ between mainnet and testnet.
- Asset ids are the venue's numeric `asset_id` (`3` is USDC).
- `Rules.fee_asset` is USDC on perpetuals and `None` on spot, whose fees are charged in
  the asset each fill delivers (the base asset on a buy, the quote asset on a sell).
  `Trade.fee` names it. Rules carry the standard account's rates, which are zero.

## Venue-specific semantics

- `fees()` reads the account's fee ticks, in parts per million, the same for buys and
  sells, perpetuals and spot. Trade fees are the tick of the account's role times the
  amount it pays on.
- REST depth sums the top 250 resting orders per side (about 200 levels on busy books);
  a side at the limit drops its possibly partial last level. Depth streams maintain the
  full book, shared per market, and fail on a sequence gap.
- Tickers carry no best-level sizes.
- Candles support all six SDK intervals, walked in 500-candle windows.
- Orders: `LIMIT` rests good-till-time (28 days), `POST_ONLY` is rejected rather than
  taking liquidity, `MARKET` is the venue's market order bounded by `price`. Prices and
  sizes off the market's grid raise before signing. `settings={'lighter': {'reduce_only':
  True}}` places reduce-only orders.
- Order ids are client order indexes. `query_order` finds inactive orders for 24 hours,
  and misses a just-cancelled order for a few seconds while the venue indexes it.
- Spot `cancel_open_orders` cancels order by order: the venue's market-scoped cancel-all
  rejects spot markets.
- Trade times are the trade's block timestamp, a few seconds before execution.
- Perpetual collateral: the exchange bucket is cross margin; a market held in isolated
  margin reports its own bucket. Spot collateral supports unified accounts only; classic
  accounts raise `ApiError`.
- Funding settles hourly. Funding-rate history is signed by the paying side (positive
  when longs pay); funding payments are positive when paid.
- Public reads are verified on mainnet. Account and trading methods are verified on
  testnet only.

<!-- next -->

---

← [Deribit Market](deribit.md) · **Next:** [Earn](../../earn/index.md) →

<!-- /next -->
