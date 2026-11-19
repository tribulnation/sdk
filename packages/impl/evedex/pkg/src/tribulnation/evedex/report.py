"""EVEDEX account snapshots, with an API key or the wallet's private key.

An account holds two balances: the trading balance positions are margined against, and
the smart-account wallet that deposits land in before they are moved to trading.
`history()` is not supported: the Report history surface is out of SDK scope (ADR 0016).
"""

from dataclasses import dataclass
from datetime import datetime
import asyncio
import warnings

from typing_extensions import AsyncIterable, Awaitable, Collection
from typed_evedex.exchange.account.balance import WalletBalance
from tribulnation.sdk.reporting import (
  HistoryRecord,
  Position,
  Report as SDKReport,
  Snapshot,
  SnapshotRecord,
  SubaccountSnapshot,
)

from .core import Shared
from .market.common import Public, signed

TRADING = 'trading'
"""The subaccount of the trading balance and the positions."""
WALLET = 'wallet'
"""The subaccount of the smart-account wallet."""


@dataclass(frozen=True, kw_only=True)
class Report(Public, SDKReport):
  """Snapshots of one account: its trading balance and positions, and its wallet."""

  @classmethod
  def new(
    cls,
    *,
    private_key: str | None = None,
    api_key: str | None = None,
    validate: bool = True,
    account_id: str | None = None,
  ):
    """Build a report; it never signs, so an API key is enough.

    Args:
      private_key: The wallet's private key, hex.
      api_key: An API key.
      validate: Validate responses.
      account_id: Root SDK account key; defaults to the venue ID.

    Raises:
      ValueError: Neither key is given.
    """
    if private_key is None and api_key is None:
      raise ValueError('An EVEDEX report needs an API key or the wallet private key')
    return cls(
      shared=Shared.new(
        private_key=private_key,
        api_key=api_key,
        validate=validate,
        account_id=account_id,
      )
    )

  async def snapshot(self, assets: Collection[str] | None = None) -> SnapshotRecord:
    """The trading balance (`funding`, without unrealized PnL) and open positions by
    instrument at their average entry price, as `trading`, and the smart-account
    wallet's balances (`balance`, deprecated upstream for the Auth service's, which
    needs the wallet's session) as `wallet`. Coins are the venue's (`usdt`); zero
    balances are left out.

    Args:
      assets: Ignored: the account holds USDT only.
    """
    self.shared.require_account()
    exchange = self.shared.client.exchange

    def wallet_request() -> Awaitable[list[WalletBalance]]:
      """Start the wallet read, without its upstream deprecation warning."""
      with warnings.catch_warnings():
        warnings.simplefilter('ignore', DeprecationWarning)
        return exchange.account.balance()

    trading, wallet, positions = await asyncio.gather(
      self.shared.call(exchange.account.funding),
      self.shared.call(wallet_request),
      self.shared.call(exchange.positions.list),
    )
    snapshot = Snapshot(
      subaccounts=[
        SubaccountSnapshot(
          subaccount=TRADING,
          balances={b['coin']: b['quantity'] for b in trading if b['quantity']},
          positions={
            p['instrument']: Position(
              size=signed(p['side'], p['quantity']), avg_price=p['avgPrice']
            )
            for p in positions['list']
            if p['quantity']
          },
        ),
        SubaccountSnapshot(
          subaccount=WALLET,
          balances={b['currency']: b['balance'] for b in wallet if b['balance']},
        ),
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
    raise NotImplementedError('EVEDEX report history is not supported')
    yield
