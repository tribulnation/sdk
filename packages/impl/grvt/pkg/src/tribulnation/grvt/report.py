"""GRVT account snapshots, read with an API key (a read-only one suffices).

A funding (main) account owns a `FUNDING` wallet and links to trading sub-accounts,
each with a `FUTURES` and a `SPOT` wallet. `history()` is not supported: the Report
history surface is being retired.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import asyncio

from typing_extensions import AsyncContextManager, AsyncIterable, Collection, Iterable
from typed_grvt.schemas import SpotBalance
from typed_grvt.trading.account_summary import SubAccount
from tribulnation.sdk.reporting import (
  HistoryRecord,
  Position,
  Report as SDKReport,
  Snapshot,
  SnapshotRecord,
  SubaccountSnapshot,
)

from .core import Environment, Shared

FUNDING = 'funding'
"""The funding account's wallet; one main account per API key."""


def held(balances: list[SpotBalance]) -> dict[str, Decimal]:
  """Non-zero balances by currency code.

  Raises:
    NotImplementedError: A currency is borrowed: whether `balance` nets the borrow is
      unverified.
  """
  for b in balances:
    if b.get('borrowed_amount'):
      raise NotImplementedError(
        f'GRVT borrowed balances are not supported: {b["currency"]} is borrowed, and '
        'whether its balance nets the borrow is unverified'
      )
  return {b['currency']: b['balance'] for b in balances if b['balance']}


def positions(s: SubAccount) -> dict[str, Position]:
  """Open positions by instrument name, signed, at their entry price."""
  return {
    p['instrument']: Position(size=p['size'], avg_price=p['entry_price'])
    for p in s['positions']
    if p['size']
  }


def futures_wallet(id: str, s: SubAccount) -> SubaccountSnapshot:
  """A trading sub-account's futures wallet: its cash balances, without unrealized PnL
  (GRVT's `total_equity` is their index value plus `unrealized_pnl`), and positions.

  Raises:
    NotImplementedError: The sub-account is a vault, whose holdings belong to every
      investor; or a currency is borrowed.
  """
  if s.get('is_vault'):
    raise NotImplementedError(
      'GRVT vault sub-accounts are not supported: their holdings belong to every investor'
    )
  return SubaccountSnapshot(
    subaccount=f'{id}:futures',
    balances=held(s['spot_balances']),
    positions=positions(s),
  )


@dataclass(frozen=True, kw_only=True)
class Report(SDKReport):
  """Snapshots of the funding wallet and of every trading sub-account the API key can
  read: `funding`, `<sub_account_id>:futures` and `<sub_account_id>:spot`."""

  shared: Shared

  @classmethod
  def new(
    cls,
    *,
    api_key: str,
    env: Environment = 'prod',
    trading_account_id: str | None = None,
    validate: bool = True,
  ):
    """Create a report over a new client; the environment is never read.

    Args:
      api_key: API key; a read-only one suffices.
      env: GRVT deployment: `prod` (mainnet) or `testnet`.
      trading_account_id: The client's default trading sub-account; snapshots read
        every sub-account the key can access regardless.
      validate: Validate responses.
    """
    return cls(
      shared=Shared.new(
        env=env,
        api_key=api_key,
        trading_account_id=trading_account_id,
        validate=validate,
      )
    )

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    """Enter the shared owner through the SDK lifecycle."""
    yield self.shared

  async def wallets(self, id: str) -> list[SubaccountSnapshot]:
    """One trading sub-account's futures wallet, with its positions, and spot wallet."""
    trading = self.shared.client.trading
    futures, spot = await asyncio.gather(
      self.shared.call(lambda: trading.account_summary(id)),
      self.shared.call(lambda: trading.spot_account_summary(id)),
    )
    return [
      futures_wallet(id, futures),
      SubaccountSnapshot(subaccount=f'{id}:spot', balances=held(spot['spot_balances'])),
    ]

  async def snapshot(self, assets: Collection[str] | None = None) -> SnapshotRecord:
    """The funding wallet, and both wallets of every accessible sub-account.

    Args:
      assets: Ignored: the venue enumerates holdings.

    Raises:
      NotImplementedError: The funding account holds a vault investment (valued only
        in USD per LP token), a currency is borrowed, or a sub-account is a vault.
    """
    self.shared.require_session()
    trading = self.shared.client.trading
    funding, subs = await asyncio.gather(
      self.shared.call(trading.funding_account_summary),
      self.shared.call(trading.sub_accounts),
    )
    if funding['result']['vault_investments']:
      raise NotImplementedError(
        'GRVT vault investments are not supported: they are valued only in USD per LP token'
      )
    states = [
      SubaccountSnapshot(
        subaccount=FUNDING, balances=held(funding['result']['spot_balances'])
      )
    ]
    for wallets in await asyncio.gather(*map(self.wallets, subs['sub_account_ids'])):
      states.extend(wallets)
    snapshot = Snapshot(subaccounts=states)
    return SnapshotRecord(
      snapshot=snapshot,
      provenance={
        'source': 'api',
        'service': self.shared.venue_id,
        'id': snapshot.time.isoformat(),
      },
    )

  async def history(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterable[HistoryRecord]:
    """Unsupported: the Report history surface is being retired."""
    raise NotImplementedError('GRVT report history is not supported')
    yield
