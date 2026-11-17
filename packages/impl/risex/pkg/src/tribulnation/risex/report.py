"""RISEx account snapshots, read by address (every account read is public).

An account is one address: one USDC collateral balance and its perpetual positions.
`history()` is not supported: the Report history surface is out of SDK scope (ADR 0016).
"""

from dataclasses import dataclass
from datetime import datetime
import asyncio

from typing_extensions import AsyncIterable, Collection
from typed_risex.core.networks import Network
from tribulnation.sdk.reporting import (
  HistoryRecord,
  Position,
  Report as SDKReport,
  Snapshot,
  SnapshotRecord,
  SubaccountSnapshot,
)

from .core import COLLATERAL, Shared, wad
from .market.account import ISOLATED, ISOLATED_UNOBSERVED, fetch_positions
from .market.common import Public


@dataclass(frozen=True, kw_only=True)
class Report(Public, SDKReport):
  """Snapshots of one account, labelled by its address."""

  @classmethod
  def new(
    cls,
    *,
    address: str | None = None,
    account_key: str | None = None,
    signer_key: str | None = None,
    network: Network = 'mainnet',
    validate: bool = True,
    account_id: str | None = None,
  ):
    """Build a report; the environment is never read, and the report never signs.

    Args:
      address: The account's address; enough on its own.
      account_key: The account's key, when no address is given (its address is used).
      signer_key: A signer key, with `address`; unused for reads.
      network: `mainnet` or `testnet`.
      validate: Validate responses.
      account_id: Root SDK account key; defaults to the venue ID.

    Raises:
      ValueError: Neither an address nor an account key is given.
    """
    if address is None and account_key is None:
      raise ValueError('A RISEx report needs the account address')
    return cls(
      shared=Shared.new(
        network=network,
        account_key=account_key,
        signer_key=signer_key if address else None,
        address=address,
        validate=validate,
        account_id=account_id,
      )
    )

  async def snapshot(self, assets: Collection[str] | None = None) -> SnapshotRecord:
    """The account's settled USDC balance and open positions by `market_id`.

    The balance is the portfolio summary's `usdc_balance`, without unrealized PnL. An
    open position's opening fees and accrued funding sit in its quote amount until the
    position changes, and only then reach the balance (testnet, 2026-11-17: a 0.0001
    BTC long carried its `0.001275078` fee in `quote_amount` while `usdc_balance` was
    unchanged).

    Args:
      assets: Ignored: the account holds USDC only.

    Raises:
      NotImplementedError: The account holds an isolated position.
    """
    account = self.shared.require_account()
    details, rows = await asyncio.gather(
      self.shared.call(lambda: self.shared.client.portfolio.details(account)),
      fetch_positions(self.shared, account),
    )
    if any(p['margin_mode'] == ISOLATED for p in rows):
      raise NotImplementedError(ISOLATED_UNOBSERVED)
    usdc = details['summary']['usdc_balance']
    snapshot = Snapshot(
      subaccounts=[
        SubaccountSnapshot(
          subaccount=account,
          balances={COLLATERAL: usdc} if usdc else {},
          positions={
            str(p['market_id']): Position(
              size=wad(p['size']), avg_price=wad(p['avg_entry_price'])
            )
            for p in rows
          },
        )
      ]
    )
    return SnapshotRecord(
      snapshot=snapshot,
      provenance={
        'source': 'api',
        'service': self.venue_id,
        'id': snapshot.time.isoformat(),
      },
    )

  async def history(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterable[HistoryRecord]:
    """Unsupported: the Report history surface is being retired."""
    raise NotImplementedError('RISEx report history is not supported')
    yield
