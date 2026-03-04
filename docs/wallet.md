# Wallet Interface

## Overview

`Wallet` provides deposit and withdrawal methods with per-network details.

## Types

`DepositMethod`
- `asset`
- `network`
- `fee`: `Fee | None`
- `contract_address`: `str | None`
- `min_confirmations`: `int | None`

`WithdrawalMethod`
- `asset`
- `network`
- `fee`: `Fee | None`
- `contract_address`: `str | None`

`Fee`
- `asset`
- `amount`

## Methods

`deposit_methods(assets: Sequence[str] | None = None) -> Sequence[DepositMethod]`
- Returns deposit methods. When `assets` is `None`, returns all.

`withdrawal_methods(assets: Sequence[str] | None = None, networks: Sequence[str] | None = None) -> Sequence[WithdrawalMethod]`
- Returns withdrawal methods. When `assets` or `networks` is `None`, no filtering is applied on that dimension.

## Notes

- `network` is the raw exchange network/chain string (no normalization).

## Related

- `sdk/src/trading_sdk/wallet/deposit_methods.py`
- `sdk/src/trading_sdk/wallet/withdrawal_methods.py`
