"""USD-M futures history: fills and the account-wide income ledger."""

from typing_extensions import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

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


def parse_income(row: UsdMFuturesIncome) -> Observation | None:
  """Map one `fapi/v1/income` row onto the observation it carries.

  Every income type Binance can send is accounted for: the ones with a definite economic
  shape get their own observation, and the rest become an `UnknownObservation` rather
  than being dropped.
  """
  asset = row.get('asset')
  income = row.get('income')
  if asset is None or income is None:
    return None
  id = str(tran_id) if (tran_id := row.get('tranId')) is not None else None
  time = row.get('time')
  amount = Decimal(income)
  type = row.get('incomeType')
  if type == 'FUNDING_FEE':
    return Funding(
      id=id,
      time=time,
      asset=asset,
      amount=amount,
      instrument=row.get('symbol'),
      subaccount=SUBACCOUNT,
    )
  if type == 'REALIZED_PNL':
    return RealizedPnl(
      id=id,
      time=time,
      asset=asset,
      amount=amount,
      instrument=row.get('symbol'),
      trade_id=row.get('tradeId'),
      subaccount=SUBACCOUNT,
    )
  if type == 'COMMISSION':
    return FeeLeg(
      id=id,
      time=time,
      asset=asset,
      amount=amount,
      event_type='future_trade',
      event_id=row.get('tradeId'),
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
          trade_id = fill.get('id')
          price = fill.get('price')
          qty = fill.get('qty')
          if trade_id is None or price is None or qty is None:
            continue
          size = Decimal(qty)
          realized_pnl = fill.get('realizedPnl')
          order_id = fill.get('orderId')
          commission = fill.get('commission')
          commission_asset = fill.get('commissionAsset')
          yield record(
            FutureTrade(
              id=str(trade_id),
              time=fill.get('time'),
              instrument=fill.get('symbol') or symbol,
              settle=fill.get('marginAsset'),
              size=size if fill.get('side') == 'BUY' else -size,
              price=Decimal(price),
              realized_pnl=Decimal(realized_pnl) if realized_pnl is not None else None,
              order_id=str(order_id) if order_id is not None else None,
              fee=nonzero_fee(Decimal(commission), commission_asset)
              if commission is not None and commission_asset is not None
              else None,
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
      page = 1
      while True:
        rows = await self.call_binance(
          lambda: self.client.usdm_futures.http.account.income(
            start_time=window_start,
            end_time=window_end,
            page=page,
            limit=PAGE_SIZE,
          )
        )
        for row in rows:
          if (observation := parse_income(row)) is not None:
            yield record(observation, id=id)
        if len(rows) < PAGE_SIZE:
          break
        page += 1
