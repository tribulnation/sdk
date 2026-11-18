# tribulnation-sdk 4.1.0

A minor release: leverage setting, position-limit reads and typed position-limit
refusals, exact decimal order inputs, and two new venues (Nado and RISEx). Nothing is
removed; upgrade the adapters released with it together (see the end of these notes).

New:

1. `MarginMarket.set_leverage(leverage)` sets the account's leverage on a perpetual
   market, keeping its margin mode, and `leverage()` raises `LeverageNotSet` (also a
   `ValueError`) where the venue reports none until one is set
   ([ADR 0066](../../dev-docs/adr/0066-set-leverage-and-leverage-not-set.md)). The SDK
   never calls it on its own. `Markets`, `Exchange`, `TradingVenue` and the gateway
   route it; unsupported venues raise `NotImplementedError`.
2. `MarginMarket.remaining_position_limit(*, ttl=None) -> RemainingPositionLimit(long,
   short)`: per direction, the notional by which a position may still grow under the
   venue's position limits (static maximum, leverage tiers, open-interest caps), free
   collateral left out; `None` where no limit is known, which is the default
   ([ADR 0062](../../dev-docs/adr/0062-remaining-position-limit-and-limit-refusals.md)).
   `RemainingPositionLimit.capped(...)` builds one from a cap and a position.
3. `PositionLimitExceeded(OrderRejected)` and its subclass `OpenInterestCapped` in
   `tribulnation.sdk.core`: an order refused for taking a position past a limit, or
   for a market at its open-interest cap. The gateway carries both and
   `LeverageNotSet`.
4. `to_decimal(x)` and `whole_leverage(x)` in `tribulnation.sdk.util`: `to_decimal`
   reads a `float` by its shortest repr (`0.1` is `Decimal('0.1')`); `fmt_num` builds on
   it.
5. Nado and RISEx accounts (`nado`, `nado_testnet`, `risex`, `risex_testnet`), wired into
   `MarketSDK`, `ReportSDK` and `Settings`, with `nado` and `risex` extras.
6. Kraken accounts take `futures_api_key` and `futures_private_key` (defaulting to
   `$KRAKEN_FUTURES_API_KEY`/`$KRAKEN_FUTURES_PRIVATE_KEY`) and a `margin_schedule`, plus
   a `kraken_testnet` Futures demo account
   ([ADR 0065](../../dev-docs/adr/0065-kraken-futures-and-spot-trading.md)). `Settings`
   gains the `bitget`, `grvt`, `kraken` and `nado` keys.

Behaviour changes in the adapters released with this version (see each package's
notes):

1. Every adapter's order quantity and price go through `to_decimal`: a `float` input
   keeps its decimal digits instead of becoming its binary expansion.
2. Bitget trades USDT-M perpetuals on a Unified Trading Account
   ([ADR 0064](../../dev-docs/adr/0064-bitget-uta-perpetual-trading.md)); Kraken trades
   Futures perpetuals with a Futures API key and Spot pairs with the Spot key (ADR 0065).
3. `set_leverage` on Aster, Bybit, Extended, GRVT, Hyperliquid, Lighter, margin.trade and
   RISEx; `remaining_position_limit` on Aster, Extended, GRVT, Hyperliquid, Lighter, Nado
   and RISEx, with Aster and Hyperliquid raising `PositionLimitExceeded`/
   `OpenInterestCapped`.

This release goes with tribulnation-aster 0.15.0, -bit2me 0.10.1, -bitget 0.14.0,
-bybit 0.10.0, -coinbase 0.6.1, -dydx 0.21.1, -extended 0.4.0, -grvt 0.4.0,
-hyperliquid 0.21.0, -kraken 0.9.0, -lighter 0.14.0, -margin-trade 0.4.0, -mexc 3.0.1 and
the first releases of -nado 0.1.0 and -risex 0.1.0, which require SDK >=4.1.0. Binance,
Deribit, Ethereum and KuCoin keep their current releases and floors.
