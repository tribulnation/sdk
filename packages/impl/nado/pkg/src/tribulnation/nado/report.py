"""Nado account snapshots of one wallet, read with its address (Nado's reads are public).

A wallet owns cross-margin subaccounts (`default`, and any it named), each one unified
account of spot balances and perpetual positions, and an isolated subaccount per
isolated position. `history()` is not supported: the Report history surface is being
retired.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import asyncio

from typing_extensions import AsyncContextManager, AsyncIterable, Collection, Iterable
from typed_nado.archive.positions import Position
from typed_nado.archive.subaccounts import Subaccount
from typed_nado.schemas import SubaccountInfo
from tribulnation.sdk import reporting
from tribulnation.sdk.reporting import (
  HistoryRecord,
  Snapshot,
  SnapshotRecord,
  SubaccountSnapshot,
)

from .core import QUOTE_ASSET, Network, Shared, x18
from .market.account import entry_price, held_isolated


@dataclass(frozen=True, kw_only=True)
class Report(reporting.Report):
  """Snapshots of every cross-margin subaccount of one wallet, named by subaccount
  name (`default`)."""

  shared: Shared

  @classmethod
  def new(
    cls,
    *,
    address: str | None = None,
    private_key: str | None = None,
    subaccount: str | None = None,
    network: Network = 'mainnet',
    validate: bool = True,
  ):
    """Create a report over a new client; the environment is never read.

    Args:
      address: The wallet whose subaccounts to snapshot.
      private_key: A signing key whose address is the wallet, when no `address` is
        given; the report never signs.
      subaccount: Ignored beyond validation: every cross subaccount of the wallet is
        snapshotted.
      network: Nado deployment: `mainnet` (Ink) or `testnet` (Ink Sepolia).
      validate: Validate responses.

    Raises:
      ValueError: Neither an address nor a key is given.
    """
    if address is None and private_key is None:
      raise ValueError('A Nado report needs the wallet address')
    return cls(
      shared=Shared.new(
        network=network,
        address=address,
        private_key=private_key,
        subaccount=subaccount,
        validate=validate,
      )
    )

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    """Enter the shared owner through the SDK lifecycle."""
    yield self.shared

  async def subaccounts(self) -> list[Subaccount]:
    """Every subaccount of the wallet, isolated ones included."""
    owner = self.shared.owner
    if owner is None:
      raise ValueError('A Nado report needs the wallet address')
    rows = await self.shared.call(
      lambda: self.shared.client.archive.subaccounts(address=owner)
    )
    return rows['subaccounts']

  async def windows(self, sender: str) -> list[Position]:
    """The archive's open cross position windows of a subaccount."""
    reply = await self.shared.call(
      lambda: self.shared.client.archive.positions(sender, isolated=False, open=True)
    )
    return reply['positions']

  async def subaccount(self, row: Subaccount) -> SubaccountSnapshot:
    """One cross subaccount: its non-zero spot balances (negative when borrowed) and
    its perpetual positions at their average entry price.

    A position's value is `amount * price + v_quote_balance`; of it,
    `amount * (price - entry)` is the position's unrealized PnL, so the rest,
    `v_quote_balance + amount * entry` (funding and realized PnL not yet settled into
    USDT0), is added to the USDT0 balance. A position just closed keeps its
    `v_quote_balance` until the venue settles it (seconds, after a mainnet round trip on
    2026-11-17), and it is added the same way.

    Raises:
      ApiError: The archive has not indexed a position yet (no open window of its
        side and size), so its entry price is unknown.
    """
    sender = row['subaccount']
    info: SubaccountInfo = await self.shared.call(
      lambda: self.shared.client.gateway.subaccount_info(subaccount=sender)
    )
    balances: dict[str, Decimal] = {}
    for b in info['spot_balances']:
      amount = x18(b['balance']['amount'])
      if amount:
        asset = await self.shared.asset_of(b['product_id'])
        balances[asset or str(b['product_id'])] = amount
    open_perps = {
      b['product_id']: b['balance']
      for b in info['perp_balances']
      if int(b['balance']['amount'])
    }
    for b in info['perp_balances']:
      if not int(b['balance']['amount']) and int(b['balance']['v_quote_balance']):
        settling = x18(b['balance']['v_quote_balance'])
        balances[QUOTE_ASSET] = balances.get(QUOTE_ASSET, Decimal(0)) + settling
    positions: dict[str, reporting.Position] = {}
    if open_perps:
      windows = await self.windows(sender)
      for pid, balance in open_perps.items():
        amount = x18(balance['amount'])
        entry = entry_price(windows, pid, amount)
        symbol = await self.shared.symbol_of(pid) or str(pid)
        positions[symbol] = reporting.Position(size=amount, avg_price=entry)
        unsettled = x18(balance['v_quote_balance']) + amount * entry
        balances[QUOTE_ASSET] = balances.get(QUOTE_ASSET, Decimal(0)) + unsettled
    return SubaccountSnapshot(
      subaccount=row['subaccount_name'], balances=balances, positions=positions
    )

  async def snapshot(self, assets: Collection[str] | None = None) -> SnapshotRecord:
    """Every cross subaccount of the wallet.

    Args:
      assets: Ignored: the venue enumerates holdings.

    Raises:
      NotImplementedError: The wallet holds an isolated position.
    """
    rows = await self.subaccounts()
    cross = [r for r in rows if not r['isolated']]
    if any(r['isolated'] for r in rows):
      for parent in cross:
        held = await self.shared.call(
          lambda: self.shared.client.gateway.isolated_positions(parent['subaccount'])
        )
        if held_isolated(held):
          raise NotImplementedError(
            'Nado isolated positions are not supported: '
            f'{parent["subaccount_name"]} holds one'
          )
    states = await asyncio.gather(*map(self.subaccount, cross))
    snapshot = Snapshot(subaccounts=list(states))
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
    raise NotImplementedError('Nado report history is not supported')
    yield
