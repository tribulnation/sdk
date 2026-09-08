"""USD-M futures history: fills and the account-wide income ledger."""

from typing_extensions import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from tribulnation.sdk.core import SDK
from tribulnation.sdk.reporting import (
  Bonus,
  FeeLeg,
  Funding,
  FutureTrade,
  HistoryRecord,
  InternalTransfer,
  Observation,
  RealizedPnl,
  UnknownObservation,
  Yield,
)
from typed_binance.usdm_futures.http.account.income import UsdMFuturesIncome

from tribulnation.binance.core import SdkMixin
from tribulnation.binance.util import windows
from ..util import nonzero_fee, record

SUBACCOUNT = 'usdm_futures'

TRADES_WINDOW = timedelta(days=7)
"""`userTrades` refuses a window wider than 7 days."""

INCOME_WINDOW = timedelta(days=7)
"""`income` serves the last 7 days when unbounded; kept as the sweep's page window."""

PAGE_SIZE = 1000
"""Rows per page, for both endpoints' own maximum."""

BONUS_TYPES = (
  'WELCOME_BONUS',
  'REFERRAL_KICKBACK',
  'COMMISSION_REBATE',
  'API_REBATE',
  'CONTEST_REWARD',
  'FEE_RETURN',
)
"""Income types that are promotional credits or rebates rather than trading flows."""


def parse_income(row: UsdMFuturesIncome) -> Observation:
  """Map one `fapi/v1/income` row onto the observation it carries.

  Every income type Binance can send is accounted for: the ones with a definite economic
  shape get their own observation, and the rest become an `UnknownObservation` rather
  than being dropped. `symbol` and `tradeId` are `''` rather than absent on account-level
  income, so both are read as "empty means none".
  """
  id = str(row['tranId'])
  time = row['time']
  asset = row['asset']
  amount = row['income']
  symbol = row['symbol'] or None
  trade_id = row['tradeId'] or None
  type = row['incomeType']
  if type == 'FUNDING_FEE':
    return Funding(
      id=id,
      time=time,
      asset=asset,
      amount=amount,
      instrument=symbol,
      subaccount=SUBACCOUNT,
    )
  if type == 'REALIZED_PNL':
    return RealizedPnl(
      id=id,
      time=time,
      asset=asset,
      amount=amount,
      instrument=symbol,
      trade_id=trade_id,
      subaccount=SUBACCOUNT,
    )
  if type == 'COMMISSION':
    return FeeLeg(
      id=id,
      time=time,
      asset=asset,
      amount=amount,
      event_type='future_trade',
      event_id=trade_id,
      subaccount=SUBACCOUNT,
    )
  if type in ('TRANSFER', 'INTERNAL_TRANSFER'):
    # Only this side of the move is reported; the counterpart compartment isn't on the
    # row. `tranId` matches the universal-transfer-history row for the same move, where
    # one exists, so the two can be reconciled.
    return InternalTransfer(
      id=id,
      time=time,
      asset=asset,
      amount=abs(amount),
      src_account=SUBACCOUNT if amount < 0 else None,
      dst_account=SUBACCOUNT if amount > 0 else None,
    )
  if type == 'BFUSD_REWARD':
    return Yield(id=id, time=time, asset=asset, amount=amount, subaccount=SUBACCOUNT)
  if type in BONUS_TYPES:
    return Bonus(
      id=id,
      time=time,
      asset=asset,
      amount=amount,
      category=type,
      subaccount=SUBACCOUNT,
    )
  return UnknownObservation(
    id=id, time=time, asset=asset, amount=amount, subaccount=SUBACCOUNT
  )


@dataclass
class UsdmHistory(SdkMixin):
  """Binance USD-M futures history sources.

  Both need the API key's Futures permission; without it Binance answers every call with
  `401 -2015`, which surfaces as an `AuthError` and is treated as a capability gap by
  the aggregate `history()`.
  """

  usdm_markets: Sequence[str] = ()
  """USD-M perpetual symbols to sweep for fills.

  `userTrades` is per symbol with no account-wide equivalent, so the caller names the
  markets to look at. Each symbol costs one call per 7 days of the window. Empty means no
  fills are reported -- the income ledger below still covers realized PnL, funding and
  commissions account-wide.
  """

  @SDK.method
  async def future_trades(
    self, start: datetime, end: datetime, *, id: str
  ) -> AsyncIterator[HistoryRecord]:
    """Fetch USD-M futures fills for every configured market."""
    for symbol in self.usdm_markets:
      for window_start, window_end in windows(start, end, TRADES_WINDOW):
        fills = await self.call_binance(
          lambda: self.client.usdm_futures.http.trading.user_trades(
            symbol=symbol,
            start_time=window_start,
            end_time=window_end,
            limit=PAGE_SIZE,
          )
        )
        for fill in fills:
          size = fill['qty']
          yield record(
            FutureTrade(
              id=str(fill['id']),
              time=fill['time'],
              instrument=fill['symbol'],
              # COIN-M's settlement asset, absent from the USD-M response.
              settle=fill.get('marginAsset'),
              size=size if fill['side'] == 'BUY' else -size,
              price=fill['price'],
              realized_pnl=fill['realizedPnl'],
              order_id=str(fill['orderId']),
              fee=nonzero_fee(fill['commission'], fill['commissionAsset']),
              subaccount=SUBACCOUNT,
            ),
            id=id,
          )

  @SDK.method
  async def income(
    self, start: datetime, end: datetime, *, id: str
  ) -> AsyncIterator[HistoryRecord]:
    """Fetch the account-wide USD-M income ledger.

    One endpoint carries realized PnL, funding, commissions, transfers and every
    promotional credit, for all symbols at once.
    """
    for window_start, window_end in windows(start, end, INCOME_WINDOW):
      paging = self.client.usdm_futures.http.account.income_paged(
        start_time=window_start,
        end_time=window_end,
        limit=PAGE_SIZE,
      ).via(self.call_binance)
      async for rows in paging:
        for row in rows:
          yield record(parse_income(row), id=id)
