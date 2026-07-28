# Exchange Support Matrix

What is actually implemented in `impl/`. Every row below corresponds to a real package;
there are no Bybit, BingX or Kraken packages.

**Legend**

- ✅ — implemented, **public**: works with no credentials.
- 🔑 — implemented, **requires credentials**.
- ✅/🔑 — public market data works unauthenticated; account data and trading need credentials.
- ❌ — not implemented.
- \* — the module exists in the package but is **not** wired into the SDK router
  (`ReportSDK.venue()` raises `NotImplementedError`, or the venue has no `Account` type).
  Construct the class directly from its package.

| Exchange | Package | Market | Earn | Wallet | Snapshots | History |
| --- | --- | --- | --- | --- | --- | --- |
| Binance | `tribulnation-binance` | ❌ | 🔑 | 🔑 | ❌ | ❌ |
| Bit2Me | `tribulnation-bit2me` | ❌ | ❌ | ❌ | 🔑\* | ❌ |
| Bitget | `tribulnation-bitget` | ❌ | 🔑 | 🔑 | 🔑\* | 🔑\* |
| dYdX | `tribulnation-dydx` | ✅/🔑 | ❌ | ❌ | ✅ | ✅ |
| Ethereum (EVM) | `tribulnation-ethereum` | ❌ | ❌ | ❌ | ✅ | ✅ |
| Hyperliquid | `tribulnation-hyperliquid` | ✅/🔑 | ❌ | ❌ | ✅ | ✅ |
| MEXC | `tribulnation-mexc` | ✅/🔑 | ✅ | 🔑 | 🔑\* | ❌ |

## Notes per surface

**Market** — `MarketSDK` routes only `dydx`/`dydx_testnet`, `hyperliquid`/`hyperliquid_testnet`
and `mexc`; anything else raises `ValueError`. Its `DEFAULT_ACCOUNTS` are all `public=True`,
so order books, rules and (on perps) index/funding read fine with no keys. Positions,
balances and order placement need credentials.

**Earn** — `EarnSDK.venue()` supports `binance`, `bitget` and `mexc` only. Its
`DEFAULT_ACCOUNTS` is `{'mexc': Mexc()}`, and MEXC earn is the only public one
(`MexcEarn()` takes no credentials). Binance and Bitget earn require API keys.

**Wallet** — `WalletSDK.venue()` supports `binance`, `bitget` and `mexc` only, and its
`DEFAULT_ACCOUNTS` is empty: every wallet surface requires credentials, so you must pass an
account explicitly.

**Snapshots / History** — `ReportSDK.venue()` resolves the EVM networks
(`ethereum`, `arbitrum`, `polygon`, `bnb-chain`, `base`, `avalanche`, `optimism`),
`dydx`/`dydx_testnet` and `hyperliquid`/`hyperliquid_testnet`. Both are address-based and need no exchange credentials (EVM history
does need an RPC/explorer provider, configured via `ProvidersConfig`). The Binance, Bitget and
MEXC branches raise `NotImplementedError`, and Bit2Me has no `Account` type at all — use
`tribulnation.bitget.reporting.Reporting`, `tribulnation.mexc.reporting.Snapshots` or
`tribulnation.bit2me.report.Snapshots` directly.

Hyperliquid history reconstructs realized PnL by folding the account's complete fill
stream, so it always replays from the beginning and `start` filters the output rather than
the fetch. The venue serves only the 10000 most recent fills and caps TWAP slices at 2000,
so configure `cache` (a SQLAlchemy URL) to keep a durable archive — without one, an
account's early history becomes unreadable once it passes those limits.
