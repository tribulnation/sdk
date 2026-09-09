"""MEXC's account history, as a stream of `HistoryRecord`s.

Four sources feed it: spot fills for discovered symbols, crypto deposits, crypto
withdrawals and futures funding settlements. MEXC unifies none of them: `myTrades` is
per symbol, the two capital ledgers are account-wide but capped at seven days per query,
and `funding_records` is page-based with no time filter, so each source walks the
window its own way and every row lands in its own record with an `ApiProvenance`.
"""

from typing_extensions import AsyncIterator, Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from tribulnation.sdk.reporting import (
  ApiProvenance,
  CryptoDeposit,
  CryptoWithdrawal,
  Fee,
  Funding,
  HistoryRecord,
  Observation,
  SpotTrade,
  source_id,
)

from typed_mexc.futures.http.account.funding_records import FundingRecordsItem
from typed_mexc.spot.http.account.trades import AccountTrade
from typed_mexc.spot.http.wallet.deposit_history import DepositHistoryItem
from typed_mexc.spot.http.wallet.withdraw_history import WithdrawHistoryItem

from tribulnation.mexc.core import Mixin, windows, wrap_exceptions

SERVICE = 'mexc'
"""`ApiProvenance.service` for every record this module emits."""

TRADES_WINDOW = timedelta(days=1)
"""One `myTrades` call per symbol per day: the endpoint has no cursor, so a window
must be narrow enough for `TRADES_LIMIT` fills to hold it."""

TRADES_LIMIT = 1000
"""The most fills one `myTrades` call answers, per MEXC's docs."""

TRADES_RETENTION = timedelta(days=30)
"""`myTrades` only serves the last month; older fills need the web export."""

CAPITAL_WINDOW = timedelta(days=7)
"""Widest accepted deposit/withdrawal query; the 90-day history horizon is separate.

References:
  - https://www.mexc.com/api-docs/spot-v3/wallet-endpoints/deposit-historysupporting-network
"""

CAPITAL_LIMIT = 1000
"""The most records one deposit or withdrawal history call answers."""

FUNDING_PAGE_SIZE = 100
"""Widest page `funding_records` serves."""

DEPOSIT_SUCCESS = '5'
"""`deposit_history`'s `status` for a credited deposit."""

WITHDRAWAL_SUCCESS = '7'
"""`withdraw_history`'s `status` for a completed withdrawal."""


def record(observation: Observation, *, id: str) -> HistoryRecord:
  """Wrap one observation in its own API-sourced record."""
  return HistoryRecord(
    observations=[observation],
    provenance=ApiProvenance(id=id, source='api', service=SERVICE),
  )


def parse_spot_trade(
  t: AccountTrade, *, base: str | None = None, quote: str | None = None
) -> SpotTrade:
  """Map one `myTrades` row onto a `SpotTrade`.

  Args:
    t: The fill as the endpoint reports it.
    base: The symbol's base asset, from exchange info; the row carries none.
    quote: The symbol's quote asset, likewise.
  """
  qty = t['qty']
  return SpotTrade(
    id=str(t['id']),
    time=t['time'],
    base=base,
    quote=quote,
    pair=t['symbol'],
    size=qty if t['isBuyer'] else -qty,
    price=t['price'],
    order_id=str(t['orderId']),
    # `commission` is required and already a `Decimal`; a zero commission is a real
    # fee (maker rebates and zero-fee promotions are common on MEXC), so it is
    # reported rather than guarded away as absent.
    fee=Fee(amount=t['commission'], asset=t['commissionAsset']),
    subaccount='spot',
  )


def parse_deposit(d: DepositHistoryItem) -> CryptoDeposit:
  """Map one credited `deposit_history` row onto a `CryptoDeposit`.

  The endpoint reports no deposit id, so the transaction hash doubles as one, and no
  fee field at all: MEXC charges nothing for a deposit.

  Raises:
    ValueError: the row names no coin or amount; the client types both optional, but
      a deposit without them cannot be accounted for and must not vanish silently.
  """
  coin, amount = d['coin'], d['amount']
  if coin is None or amount is None:
    raise ValueError(f'MEXC deposit row without coin or amount: {d.get("txId")}')
  return CryptoDeposit(
    id=d['txId'],
    time=d['insertTime'],
    amount=amount,
    asset=coin,
    network=d['network'],
    tx_id=d['txId'],
    dst_address=d['address'],
    subaccount='spot',
  )


def parse_withdrawal(w: WithdrawHistoryItem) -> CryptoWithdrawal:
  """Map one completed `withdraw_history` row onto a `CryptoWithdrawal`.

  `applyTime` is when the balance left the account; `updateTime` is when the venue
  last touched the row, which for a completed withdrawal is its confirmation.

  Raises:
    ValueError: the row names no coin or amount (see `parse_deposit`).
  """
  coin, amount = w['coin'], w['amount']
  if coin is None or amount is None:
    raise ValueError(f'MEXC withdrawal row without coin or amount: {w.get("id")}')
  fee = w['transactionFee']
  return CryptoWithdrawal(
    id=w['id'] or w['txId'],
    time=w['applyTime'] or w['updateTime'],
    amount=amount,
    asset=coin,
    network=w['network'],
    tx_id=w['txId'] or w['transHash'],
    dst_address=w['address'],
    # A `'0'` fee is a free withdrawal, not a missing one; only `null` is absent.
    fee=Fee(amount=fee, asset=coin) if fee is not None else None,
    subaccount='spot',
  )


def parse_funding(r: FundingRecordsItem, *, settle: str) -> Funding:
  """Map one `funding_records` row onto a `Funding` settlement.

  `funding` is signed the way MEXC signs it, taken as the balance change: positive
  credited, negative paid. The client hands it over as a `float` (MEXC sends a JSON
  number here), so it goes through `str` to keep the digits the venue sent.

  Args:
    r: The settlement as the endpoint reports it.
    settle: The contract's settlement coin, from contract info; the row carries none.
  """
  position_id = r.get('positionId')
  return Funding(
    id=str(r['id']),
    time=r['settleTime'],
    amount=Decimal(str(r['funding'])),
    asset=settle,
    instrument=r['symbol'],
    position_id=str(position_id) if position_id is not None else None,
    subaccount='futures',
  )


@wrap_exceptions
async def spot_trades(
  self: Mixin, symbols: Sequence[str], start: datetime, end: datetime
) -> AsyncIterator[HistoryRecord]:
  """Yield one record per spot fill in the window, for every discovered symbol."""
  for symbol in symbols:
    info = await self.cached_spot_market(symbol)
    for lower, upper in windows(start, end, TRADES_WINDOW):
      fills = await self.client.spot.http.account.trades(
        symbol=symbol,
        start_time=lower,
        end_time=upper,
        limit=TRADES_LIMIT,
        recv_window=self.recvWindow,
      )
      for t in fills:
        trade = parse_spot_trade(t, base=info['baseAsset'], quote=info['quoteAsset'])
        yield record(trade, id=f'spot-trade-{symbol}-{trade.id}')


@wrap_exceptions
async def deposits(
  self: Mixin, start: datetime, end: datetime
) -> AsyncIterator[HistoryRecord]:
  """Yield one record per credited on-chain deposit in the window."""
  for lower, upper in windows(start, end, CAPITAL_WINDOW):
    rows = await self.client.spot.http.wallet.deposit_history(
      status=DEPOSIT_SUCCESS, start_time=lower, end_time=upper, limit=CAPITAL_LIMIT
    )
    for d in rows:
      deposit = parse_deposit(d)
      id = f'deposit-{deposit.id}' if deposit.id else source_id(SERVICE)
      yield record(deposit, id=id)


@wrap_exceptions
async def withdrawals(
  self: Mixin, start: datetime, end: datetime
) -> AsyncIterator[HistoryRecord]:
  """Yield one record per completed withdrawal in the window."""
  for lower, upper in windows(start, end, CAPITAL_WINDOW):
    rows = await self.client.spot.http.wallet.withdraw_history(
      status=WITHDRAWAL_SUCCESS,
      start_time=lower,
      end_time=upper,
      limit=CAPITAL_LIMIT,
    )
    for w in rows:
      withdrawal = parse_withdrawal(w)
      id = f'withdrawal-{withdrawal.id}' if withdrawal.id else source_id(SERVICE)
      yield record(withdrawal, id=id)


@wrap_exceptions
async def funding(
  self: Mixin, start: datetime, end: datetime
) -> AsyncIterator[HistoryRecord]:
  """Yield one record per futures funding settlement in the window.

  The endpoint takes no time filter and documents no page order, so every page is
  read and the window is applied here; stopping at the first out-of-window page would
  only be safe under an ordering MEXC does not promise.
  """
  paging = self.client.futures.http.account.funding_records_paged(
    page_size=FUNDING_PAGE_SIZE
  )
  async for page in paging:
    for r in page:
      if not start <= r['settleTime'] <= end:
        continue
      spec = await self.cached_perp_market(r['symbol'])
      yield record(parse_funding(r, settle=spec['settleCoin']), id=f'funding-{r["id"]}')


async def history(
  self: Mixin,
  start: datetime | None = None,
  end: datetime | None = None,
) -> AsyncIterator[HistoryRecord]:
  """Stream spot fills, deposits, withdrawals and funding settlements in the window.

  Omitted bounds select the last 30 days. Spot symbols are discovered from exchange
  info, not inferred from current holdings. This may require many requests and
  cannot discover delisted symbols absent from the current catalogue.
  """
  end = end or datetime.now(timezone.utc)
  start = start or end - TRADES_RETENTION
  if start.utcoffset() is None or end.utcoffset() is None:
    raise ValueError('History bounds must be timezone-aware')
  if start > end:
    raise ValueError('History start must not follow end')
  info = await self.client.spot.http.market.exchange_info()
  self.cache.spot_markets = {row['symbol']: row for row in info['symbols']}
  async for r in spot_trades(self, list(self.cache.spot_markets), start, end):
    yield r
  async for r in deposits(self, start, end):
    yield r
  async for r in withdrawals(self, start, end):
    yield r
  async for r in funding(self, start, end):
    yield r
