"""Account rows in SDK terms: spot balances, futures positions, collateral and fees."""

from decimal import Decimal
from typing_extensions import Sequence

from typed_kucoin.account.futures_account import FuturesAccountOverview
from typed_kucoin.account.spot_accounts import SpotAccountEntry
from typed_kucoin.account.trade_fee.actual_fee import ActualFee
from typed_kucoin.account.trade_fee.actual_fee_futures import FuturesActualFee
from typed_kucoin.schemas import PositionDetail
from tribulnation.sdk.core import MissingData
from tribulnation.sdk.market import Balance, Fees, PerpCollateral, PerpPosition

ZERO = Decimal(0)


def dec(x: float | int) -> Decimal:
  """A JSON number as the decimal it was written as."""
  return Decimal(str(x))


def spot_balance(rows: Sequence[SpotAccountEntry], asset: str) -> Balance:
  """One asset of the spot `trade` account; zero when the account holds none."""
  total = sum((r['balance'] for r in rows if r['currency'] == asset), ZERO)
  free = sum((r['available'] for r in rows if r['currency'] == asset), ZERO)
  return Balance(total=total, free=free)


def position_row(rows: Sequence[PositionDetail], symbol: str) -> PositionDetail | None:
  """The symbol's one-way position row, `None` when the account lists none (flat)."""
  for row in rows:
    if row['symbol'] == symbol:
      return row


def perp_position(row: PositionDetail | None, multiplier: Decimal) -> PerpPosition:
  """A one-way position in base units; a missing row or a zero quantity is flat.

  `liquidationPrice` is `0` where KuCoin names none, which the SDK reports as `None`.
  """
  if row is not None and row['currentQty'] != 0:
    liquidation = dec(row['liquidationPrice'])
    return PerpPosition(
      size=row['currentQty'] * multiplier,
      entry_price=dec(row['avgEntryPrice']),
      liquidation_price=liquidation if liquidation > 0 else None,
    )
  else:
    return PerpPosition()


def maintenance(row: PositionDetail) -> Decimal:
  """A position's maintenance margin, `posMaint`.

  Raises:
    MissingData: An open position's row omits `posMaint`.
  """
  if (value := row.get('posMaint')) is not None:
    return dec(value)
  else:
    raise MissingData(
      'KuCoin position omits its maintenance margin',
      market_id=row['symbol'],
      field='posMaint',
    )


def leverage_of(notional: Decimal, equity: Decimal) -> Decimal:
  """Notional over equity; zero without positive equity."""
  return notional / equity if equity > 0 else ZERO


def cross_collateral(
  account: FuturesAccountOverview, rows: Sequence[PositionDetail]
) -> PerpCollateral:
  """The cross pool of one settlement currency.

  Equity and free collateral are the overview's `accountEquity` and `availableBalance`;
  initial margin its position plus order margin. Maintenance margin and leverage sum the
  open cross positions settled in the currency (`posMaint`, `|markValue|`).
  """
  currency = account['currency']
  open_rows = [
    r
    for r in rows
    if r['crossMode'] and r['settleCurrency'] == currency and r['currentQty'] != 0
  ]
  equity = dec(account['accountEquity'])
  notional = sum((abs(dec(r['markValue'])) for r in open_rows), ZERO)
  return PerpCollateral(
    equity=equity,
    free_collateral=dec(account['availableBalance']),
    initial_margin=dec(account['positionMargin']) + dec(account['orderMargin']),
    maintenance_margin=sum((maintenance(r) for r in open_rows), ZERO),
    leverage=leverage_of(notional, equity),
    margin_mode='cross',
  )


def isolated_collateral(row: PositionDetail) -> PerpCollateral:
  """An isolated position's own bucket: its margin plus unrealized PnL."""
  equity = dec(row['posMargin']) + dec(row['unrealisedPnl'])
  initial = dec(row['posInit'])
  return PerpCollateral(
    equity=equity,
    free_collateral=max(equity - initial, ZERO),
    initial_margin=initial,
    maintenance_margin=maintenance(row),
    leverage=leverage_of(abs(dec(row['markValue'])), equity),
    margin_mode='isolated',
  )


def spot_fees(row: ActualFee) -> Fees:
  """Account rates of a spot pair, each side with its tax rate where one applies.

  Negative maker rates (market-maker rebates) pass through unchanged.
  """
  buy_tax = row.get('buyTaxRate') or ZERO
  sell_tax = row.get('sellTaxRate') or ZERO
  return Fees(
    maker_buy=row['makerFeeRate'] + buy_tax,
    maker_sell=row['makerFeeRate'] + sell_tax,
    taker_buy=row['takerFeeRate'] + buy_tax,
    taker_sell=row['takerFeeRate'] + sell_tax,
  )


def perp_fees(row: FuturesActualFee) -> Fees:
  """Account rates of a contract, with its tax rate where one applies.

  Negative maker rates (market-maker rebates) pass through unchanged.
  """
  tax = row.get('feeTaxRate') or ZERO
  return Fees.symmetric(
    maker=row['makerFeeRate'] + tax, taker=row['takerFeeRate'] + tax
  )
