"""Spot-wallet history: fills, on-chain deposits/withdrawals, internal transfers."""

from typing_extensions import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from tribulnation.sdk.core import SDK
from tribulnation.sdk.reporting import (
  CryptoDeposit,
  CryptoWithdrawal,
  HistoryRecord,
  InternalTransfer,
  SpotTrade,
)
from typed_binance.schemas import UniversalTransferType

from tribulnation.binance.core import SdkMixin
from tribulnation.binance.util import windows
from ..util import nonzero_fee, record, split_transfer_type

CAPITAL_WINDOW = timedelta(days=90) - timedelta(milliseconds=1)
"""Deposit and withdrawal history refuse a window wider than 90 days."""

PAGE_SIZE = 100
"""Rows per page for the transfer-history cursor (its documented maximum)."""

CAPITAL_PAGE_SIZE = 1000
"""Rows per page for deposit/withdrawal history (their documented maximum)."""

DEPOSIT_SUCCESS = 1
"""`DepositRecord.status` for a credited deposit."""

WITHDRAWAL_COMPLETED = 6
"""`WithdrawRecord.status` for a completed withdrawal."""

TRANSFER_TYPES: Sequence[UniversalTransferType] = ['MAIN_FUNDING', 'FUNDING_MAIN']
"""Only movements between the supported Spot and Funding compartments are queried."""


@dataclass
class SpotHistory(SdkMixin):
  """Binance spot-wallet history sources."""

  @SDK.method
  async def spot_trades(
    self, start: datetime | None, end: datetime, *, id: str
  ) -> AsyncIterator[HistoryRecord]:
    """Discover all listed symbols and walk their retained fill IDs.

    The ID cursor avoids one empty request per symbol per day. Date filtering is
    local because Binance forbids combining `fromId` with time bounds. Symbols
    removed from exchange information remain a best-effort coverage limitation.
    """
    info = await self.call_binance(self.client.spot.http.market.exchange_info)
    for market in info['symbols']:
      symbol = market['symbol']
      cursor = 0
      while True:
        fills = await self.call_binance(
          lambda: self.client.spot.http.account.my_trades(
            symbol=symbol,
            from_id=cursor,
            limit=1000,
          )
        )
        for fill in fills:
          if (
            fill['id'] < cursor
            or fill['time'] > end
            or (start is not None and fill['time'] < start)
          ):
            continue
          yield record(
            SpotTrade(
              id=str(fill['id']),
              time=fill['time'],
              pair=fill['symbol'],
              size=fill['qty'] if fill['isBuyer'] else -fill['qty'],
              price=fill['price'],
              order_id=str(fill['orderId']),
              fee=nonzero_fee(fill['commission'], fill['commissionAsset']),
              subaccount='spot',
            ),
            id=id,
          )
        if not fills or len(fills) < 1000 or max(fill['time'] for fill in fills) > end:
          break
        following = max(fill['id'] for fill in fills) + 1
        if following <= cursor:
          break
        cursor = following

  @SDK.method
  async def crypto_deposits(
    self, start: datetime, end: datetime, *, id: str
  ) -> AsyncIterator[HistoryRecord]:
    """Fetch credited on-chain deposits.

    Binance charges nothing for a deposit, and the endpoint carries no fee field.
    """
    for window_start, window_end in windows(start, end, CAPITAL_WINDOW):
      paging = self.client.spot.http.wallet.capital.deposit.history_paged(
        start_time=window_start,
        end_time=window_end,
        status=DEPOSIT_SUCCESS,
        limit=CAPITAL_PAGE_SIZE,
      ).via(self.call_binance)
      async for rows in paging:
        for deposit in rows:
          yield record(
            CryptoDeposit(
              id=deposit['id'],
              time=deposit['insertTime'],
              asset=deposit['coin'],
              amount=deposit['amount'],
              network=deposit['network'] or None,
              tx_id=deposit['txId'] or None,
              dst_address=deposit['address'] or None,
              subaccount='funding' if deposit['walletType'] == 1 else 'spot',
            ),
            id=id,
          )

  @SDK.method
  async def crypto_withdrawals(
    self, start: datetime, end: datetime, *, id: str
  ) -> AsyncIterator[HistoryRecord]:
    """Fetch completed on-chain withdrawals.

    `transferType == 1` rows are Binance-to-Binance sends, which never touch a chain;
    they are skipped rather than reported as on-chain withdrawals.
    """
    for window_start, window_end in windows(start, end, CAPITAL_WINDOW):
      paging = self.client.spot.http.wallet.capital.withdraw.history_paged(
        start_time=window_start,
        end_time=window_end,
        status=WITHDRAWAL_COMPLETED,
        limit=CAPITAL_PAGE_SIZE,
      ).via(self.call_binance)
      async for rows in paging:
        for withdrawal in rows:
          if withdrawal['transferType'] == 1:
            continue
          yield record(
            CryptoWithdrawal(
              id=withdrawal['id'],
              time=withdrawal['applyTime'],
              asset=withdrawal['coin'],
              amount=-withdrawal['amount'],
              network=withdrawal.get('network') or None,
              tx_id=withdrawal['txId'] or None,
              dst_address=withdrawal['address'] or None,
              fee=nonzero_fee(withdrawal['transactionFee'], withdrawal['coin']),
              subaccount='funding' if withdrawal['walletType'] == 1 else 'spot',
            ),
            id=id,
          )

  @SDK.method
  async def internal_transfers(
    self, start: datetime, end: datetime, *, id: str
  ) -> AsyncIterator[HistoryRecord]:
    """Fetch transfers between this account's own wallet compartments."""
    for type in TRANSFER_TYPES:
      src, dst = split_transfer_type(type)
      paging = self.client.spot.http.wallet.asset.transfer.history_paged(
        type, start_time=start, end_time=end, size=PAGE_SIZE
      ).via(self.call_binance)
      async for chunk in paging:
        for transfer in chunk:
          yield record(
            InternalTransfer(
              id=str(transfer['tranId']),
              time=transfer['timestamp'],
              asset=transfer['asset'],
              amount=abs(transfer['amount']),
              src_account=src,
              dst_account=dst,
            ),
            id=id,
          )
