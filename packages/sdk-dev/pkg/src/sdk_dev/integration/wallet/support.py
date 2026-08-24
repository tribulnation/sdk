"""Support for wallet integration tests."""

from collections.abc import Sequence
from dataclasses import dataclass

from tribulnation.sdk.wallet.deposit_methods import DepositMethod
from tribulnation.sdk.wallet.withdrawal_methods import WithdrawalMethod


@dataclass(frozen=True, kw_only=True)
class WalletResult:
  """Results of fetching one account's wallet methods."""

  deposit_methods: Sequence[DepositMethod] | None = None
  deposit_failure: str | None = None
  withdrawal_methods: Sequence[WithdrawalMethod] | None = None
  withdrawal_failure: str | None = None
