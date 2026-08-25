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
| Bit2Me | `tribulnation-bit2me` | ❌ | ❌ | ❌ | 🔑 | ❌ |
| Bitget | `tribulnation-bitget` | ❌ | 🔑 | 🔑 | 🔑\* | 🔑\* |
| dYdX | `tribulnation-dydx` | ✅/🔑 | ❌ | ❌ | ✅ | ✅ |
| Ethereum (EVM) | `tribulnation-ethereum` | ❌ | ❌ | ❌ | ✅ | ✅ |
| Hyperliquid | `tribulnation-hyperliquid` | ✅/🔑 | ❌ | ❌ | ✅ | ✅ |
| MEXC | `tribulnation-mexc` | ✅/🔑 | ✅ | 🔑 | 🔑 | ❌ |

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

Bit2Me has no Wallet implementation, deliberately: its only asset/network catalogue
(`v2/currency/assets`) lists a single display network per asset (e.g. USDC shows
`ETHEREUM (ERC20)`), but deposit addresses for that same asset can be minted on other
networks too — confirmed live, `v2/wallet/pocket/{id}/{network}/address` happily mints USDC
addresses on `polygon` and `solana` as well. There is no endpoint that enumerates the full
network set for an asset, so `deposit_methods()`/`withdrawal_methods()` built on the
catalogue would silently under-report networks for any multi-chain asset. Per-transaction
withdrawal fees have the same shape of problem: `POST /v1/wallet/transaction/proforma` does
return a real fee, but only as a live quote for one already-funded pocket and destination,
not as a listable table — so there's no accurate way to answer either "which networks" or
"what fee" in bulk. Left unimplemented rather than shipped incomplete.

**Snapshots / History** — `ReportSDK.venue()` resolves the EVM networks
(`ethereum`, `arbitrum`, `polygon`, `bnb-chain`, `base`, `avalanche`, `optimism`, `hyperevm`),
`dydx`/`dydx_testnet`, `hyperliquid`/`hyperliquid_testnet`, plus the three CEXs
`bit2me`, `bitget` and `mexc`. The chain-based venues are address-based and need no exchange
credentials (EVM history does need an RPC/explorer provider, configured via
`ProvidersConfig`); the CEXs all require API keys.

HyperEVM uses the `hyperevm` EVM venue id. The `hyperliquid` venue id remains the
separate HyperCore account and report implementation.

The CEX branches return a per-venue `Report` (`tribulnation.bit2me.report.Report`,
`tribulnation.mexc.reporting.Report`) that subclasses the venue's own `Snapshots`, so it
serves `snapshot()` directly and raises `NotImplementedError` from `history()` — eagerly, at
call time, not on first iteration.

The Bitget and Binance branches both raise `NotImplementedError`. Binance has no reporting
module at all. Bitget has a full `Reporting` (`Snapshots` **and** `History`), but it targets
the classic-account endpoints that the unified trading account (UTA) does not support, so it
is deliberately left out of the router pending a reimplementation; it stays importable as
`tribulnation.bitget.reporting.Reporting` for callers still on a classic account.

CEX credentials are read from the account's env vars — `BIT2ME_API_KEY`/`BIT2ME_SECRET_KEY`
(note the asymmetric naming), `BITGET_ACCESS_KEY`/`BITGET_SECRET_KEY`/`BITGET_PASSPHRASE`,
`MEXC_API_KEY`/`MEXC_API_SECRET` — and are passed to the venue client explicitly. Note that
`public=True` does *not* make a CEX report usable without credentials: every endpoint is
authenticated, and the underlying clients read `os.environ[...]`, so a missing variable
surfaces as a `KeyError`. This matches `WalletSDK`/`EarnSDK`.

Hyperliquid history reconstructs realized PnL by folding the account's complete fill
stream, so it always replays from the beginning and `start` filters the output rather than
the fetch. The venue serves only the 10000 most recent fills and caps TWAP slices at 2000,
so configure `cache` (a SQLAlchemy URL) to keep a durable archive — without one, an
account's early history becomes unreadable once it passes those limits.
