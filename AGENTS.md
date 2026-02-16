# AGENTS.md – SDK and exchange implementations

Guidance for AI agents and developers working on this repo.

---

## Repo layout

- **`sdk/`** – Abstract SDK (package **trading-sdk**, import as `trading_sdk`). Defines protocols, dataclasses, and types; no exchange-specific code.
- **`impl/`** – Exchange implementations. Each `impl/<exchange>/` is a separate package (e.g. **bitget-trading-sdk**, **binance-trading-sdk**, **mexc-trading-sdk**) that depends on **trading-sdk** and a typed exchange client (e.g. **typed-bitget**, **typed-binance**, **typed-mexc**).
- **`.cursor/repl.py`** – MCP Python REPL server. `restart_environment` clears user-loaded modules from `sys.modules` so the next run imports fresh code from disk.

Implementations live under `impl/<name>/src/<name>_sdk/` (e.g. `impl/bitget/src/bitget_sdk/`). The top-level class (e.g. `Bitget`, `Binance`, `MEXC`) is a dataclass that composes `earn`, `wallet`, and optionally `reporting` / `spot` / `futures` via `__post_init__`.

---

## SDK surface (relevant to impls)

### Earn – `trading_sdk.earn.instruments`

- **Types**: `Instrument = Flexible | Fixed`, `InstrumentType = Literal['flexible', 'fixed']`.
- **BaseInstrument**: `type`, `asset`, `apr` (Decimal), `yield_asset`, `min_qty`, `max_qty`, `url`.
- **Flexible**: same, `type: Literal['flexible']`.
- **Fixed**: same + `duration: timedelta`.
- **Protocol**: `async def instruments(self, *, types: Sequence[InstrumentType] | None = None, assets: Sequence[str] | None = None) -> Sequence[Instrument]`.
- **Filtering**: When `types` or `assets` is `None`, return all; otherwise filter in memory (or at API level when the API supports it).

### Wallet – deposit methods

- **DepositMethod**: `asset`, `network: str`, `fee: Fee | None`, `contract_address: str | None`, `min_confirmations: int | None`.  
  **Fee**: `asset`, `amount: Decimal`.
- **Protocol**: `async def deposit_methods(self, *, assets: Sequence[str] | None = None) -> Sequence[DepositMethod]`.
- **Network**: Use the **raw network/chain string** from the exchange (e.g. `"ETH"`, `"TRC20"`). No normalization to a shared `Network` type here; that can live in another layer.

### Wallet – withdrawal methods

- **WithdrawalMethod**: `asset`, `contract_address: str | None`, `network: str`, `fee: Fee | None`.
- **Protocol**: `async def withdrawal_methods(self, *, assets: Sequence[str] | None = None, networks: Sequence[str] | None = None) -> Sequence[WithdrawalMethod]`.
- **Networks**: Again raw strings from the exchange; filter by `networks` when provided.

---

## Implementation patterns

### Core / client

- Each impl has a **core** (e.g. `bitget_sdk/core.py`, `binance_sdk/core.py`) defining **SdkMixin**: holds the underlying client (e.g. `Bitget`, `Binance`), `validate`, and `new(...)` (and optionally `__aenter__` / `__aexit__`).
- No exchange-specific `parse_network` or network enums in the wallet layer; pass through API chain/network strings.

### Earn instruments

- **Bitget**: `client.earn.savings.products()` (or equivalent in typed-bitget). One product can have multiple **APY tiers**; map **one instrument per tier** with that tier’s `minStepVal`/`maxStepVal` and `currentApy`. Filter by `types` and `assets` after parsing.
- **Binance**: `client.simple_earn.flexible.list_paged()` and `client.simple_earn.fixed.list_paged()`. One product → one instrument; use `latestAnnualPercentageRate` for flexible and `detail.apr` (or 0) for fixed; `duration` from `fixedInvestPeriodCount` (days). Filter by `types`/`assets` (optionally only call the list(s) needed by `types`).
- **MEXC**: Earn is **not** on the standard API. Use the **public** endpoint `GET https://www.mexc.com/api/financialactivity/financial/products/list/V2`. Fetch with **httpx**, define **TypedDicts** for the response shape and **Pydantic** models for validation, then map to `Flexible`/`Fixed`. Filter by `types` and `assets`.

### Wallet deposit_methods

- **Bitget**: `client.spot.market.coins()` (or `spot.public.coins()`). Per-coin `chains`; include only chains with deposit enabled; one method per (coin, chain). `network` = raw `chain` string; `contract_address` from chain; `min_confirmations` from chain; fee = 0 for deposits.
- **Binance**: `client.wallet.capital.coins()`. Same idea: `networkList` per coin, keep `depositEnable`; `network` = raw `net["network"]`; `contract_address`, `min_confirmations` from network.
- **MEXC**: `client.spot.currency_info()` (or equivalent). Per-coin `networkList`; keep `depositEnable`; `network` = `m["netWork"]` (note typo in API), `contract_address` = `m.get("contract")`, fee = 0.

### Wallet withdrawal_methods

- Same data sources as deposit (coins/currency info). Use **withdraw**-enabled networks only; `fee` from the API (e.g. `withdrawFee`). Apply `assets` and `networks` filters; when possible, filter **before** heavy work (e.g. before calling deposit-address per (coin, chain) if that were used).

### Parsing and filtering

- Normalize numeric API fields to `Decimal` where the SDK expects it (e.g. `_to_decimal(...)`).
- Prefer filtering **inside** the parsing loop (by `assets` / `networks` / `types`) so expensive steps (e.g. many HTTP calls) are only done for requested assets/networks.
- When the API returns tiers (e.g. Bitget earn), emit **one instrument per tier** with tier-specific min/max and APR.

---

## Testing and REPL

- **Python REPL MCP** (project-0-sdk-python-repl): run code with `execute_python`. For async code, use a **new event loop in a thread** (e.g. `asyncio.new_event_loop(); loop.run_until_complete(coro)`) because `asyncio.run()` cannot be used inside an already-running loop.
- **restart_environment**: Clears the REPL namespace and **removes user-loaded modules from `sys.modules`** (keeps stdlib and MCP/dotenv). Always use it when you need the next import to see the latest code from disk (e.g. after editing an impl).
- When testing an impl, set `sys.path` so the impl’s `src` and the SDK’s `src` are on the path (e.g. `impl/bitget/src`, `sdk/src`), then import the wrapper (e.g. `from bitget_sdk import Bitget`) and the underlying client will be used from the impl’s dependencies.

---

## MEXC earn – public API and validation

- **URL**: `https://www.mexc.com/api/financialactivity/financial/products/list/V2`.
- **Fetch**: Use **httpx** (async GET). No auth.
- **Schema**: Response has `data: list[CurrencyGroup]`, each with `currency`, `financialProductList`. Each product has `financialType` / `investPeriodType` (FLEXIBLE | FIXED | BLC_EARN), `baseApr` / `showApr`, `profitCurrency`, `minPledgeQuantity`, `perPledgeMaxQuantity` (`"-1"` = no max), `fixedInvestPeriodCount` (days for fixed), `shareUrl`, etc.
- **Validation**: Define **TypedDicts** for the raw API shape and **Pydantic** models (e.g. `FinancialProduct`, `CurrencyGroup`, `FinancialProductsListV2Response`) and use `model_validate(response.json())` so the rest of the code works with validated, typed objects.

---

## Conventions

- **Imports**: Impls import SDK types from `trading_sdk` (e.g. `trading_sdk.earn.instruments`, `trading_sdk.wallet.deposit_methods`). Some code may still reference `sdk` if the package is installed or the path is set to the SDK’s public package name.
- **Naming**: Wallet modules: `deposit_methods.py`, `withdrawal_methods.py`. Earn: `earn/instruments.py`. Optional private helpers (e.g. fetch + schema) in `_financial_products.py`.
- **Errors**: MEXC uses `@wrap_exceptions` from `mexc_sdk.core` for consistent error handling; other impls may use similar decorators or plain try/except.

---

## Quick reference – data sources

| Area              | Bitget                    | Binance                          | MEXC                                      |
|-------------------|---------------------------|----------------------------------|-------------------------------------------|
| Earn instruments  | `earn.savings.products()`  | `simple_earn.flexible/fixed.list_paged()` | Public URL (httpx) + Pydantic            |
| Deposit methods   | `spot.market.coins()`     | `wallet.capital.coins()`         | `spot.currency_info()`                    |
| Withdrawal methods| same coins response       | same capital.coins()             | same currency_info()                      |
| Network field     | Raw `chain`               | Raw `network`                    | Raw `netWork`                             |

Use this plus the SDK types above to add or adjust any exchange impl consistently.
