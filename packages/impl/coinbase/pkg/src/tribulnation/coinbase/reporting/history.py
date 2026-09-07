"""Transaction history for one Coinbase account.

Two sources, merged. The v2 per-account transaction stream
(`app.accounts.transactions`) is the broad one: sends, fiat rails, trades and the
account's passive staking program all appear there. Advanced Trade fills
(`orders.historical.fills`) are the precise one for spot trades specifically, carrying
a real product id, side, price, per-fill commission and a maker/taker indicator that
the v2 `advanced_trade_fill` sub-blob does not. Where both describe the same order the
fill wins, and the matching v2 row is dropped rather than double-counted.

Rows that carry only one signed leg with no paired asset or price -- `trade`, `buy`,
`sell` from the legacy Simple UI, `staking_transfer`, `staking_reward`, `earn_payout`,
`incentives_rewards_payout`, `transfer` -- become `UnknownObservation`s rather than a
`SpotTrade`/`Conversion` shape the source does not actually support.
"""

from typing_extensions import AsyncIterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from tribulnation.sdk.core import SDK
from tribulnation.sdk.reporting import (
  CryptoDeposit,
  CryptoWithdrawal,
  Fee,
  FiatDeposit,
  FiatWithdrawal,
  History as _History,
  HistoryRecord,
  Observation,
  SpotTrade,
  UnknownObservation,
  source_id,
)

from typed_coinbase.app.accounts.transactions.list import Transaction
from typed_coinbase.app.advanced_trade.http.orders.historical.fills import Fill

from tribulnation.coinbase.core import Mixin

SERVICE = 'coinbase'


def parse_transaction(tx: Transaction) -> Observation:
  """Map one v2 transaction row onto the observation it actually supports."""
  time = tx['created_at']
  amount = tx['amount']['amount']
  asset = tx['amount']['currency']
  kind = tx['type']
  network = tx.get('network')
  if kind == 'send' and network is not None:
    # v2 types onchain transfers both ways as `send`; the sign of `amount` is what
    # separates them (verified live: a positive `send` row with no `to` is an inbound
    # deposit, the negative ones are withdrawals).
    if amount > 0:
      return CryptoDeposit(
        id=tx['id'],
        time=time,
        asset=asset,
        amount=amount,
        network=network.get('network_name'),
        tx_id=network.get('hash'),
      )
    return CryptoWithdrawal(
      id=tx['id'],
      time=time,
      asset=asset,
      amount=amount,
      network=network.get('network_name'),
      tx_id=network.get('hash'),
      dst_address=(tx.get('to') or {}).get('address'),
    )
  if kind == 'receive' and network is not None:
    return CryptoDeposit(
      id=tx['id'],
      time=time,
      asset=asset,
      amount=amount,
      network=network.get('network_name'),
      tx_id=network.get('hash'),
    )
  if kind == 'fiat_deposit':
    return FiatDeposit(id=tx['id'], time=time, asset=asset, amount=amount)
  if kind == 'fiat_withdrawal':
    return FiatWithdrawal(id=tx['id'], time=time, asset=asset, amount=amount)
  return UnknownObservation(id=tx['id'], time=time, asset=asset, amount=amount)


def parse_fill(fill: Fill) -> SpotTrade | None:
  """Map one Advanced Trade fill onto a `SpotTrade`, keyed by its order.

  Returns `None` for a fill naming neither a product nor an order: without both there
  is nothing to reconcile it against the v2 row it duplicates.
  """
  product_id = fill.get('product_id')
  order_id = fill.get('order_id')
  if not product_id or not order_id:
    return None
  base, _, quote = product_id.partition('-')
  size = fill.get('size')
  if size is not None and fill.get('side') == 'SELL':
    size = -size
  commission = fill.get('commission')
  return SpotTrade(
    id=fill.get('trade_id'),
    time=fill.get('trade_time'),
    base=base,
    quote=quote,
    pair=product_id,
    size=size,
    price=fill.get('price'),
    order_id=order_id,
    fee=Fee(amount=commission, asset=quote)
    if commission is not None and commission != 0
    else None,
  )


@dataclass(frozen=True, kw_only=True)
class History(Mixin, _History):
  """Transaction history for one Coinbase account."""

  @SDK.method
  async def accounts(self) -> list[str]:
    """List every v2 account id, sweeping the catalogue page by page."""
    accounts = await self.app.accounts.list_paged().via(self.call_app)
    return [account['id'] for account in accounts]

  @SDK.method
  async def transactions(self, account_id: str, /) -> list[Transaction]:
    """Sweep one account's v2 transaction stream."""
    paging = self.app.accounts.transactions.list_paged(account_id=account_id)
    return list(await paging.via(self.call_app))

  @SDK.method
  async def fills(self, start: datetime, end: datetime) -> dict[str, SpotTrade]:
    """Sweep the Advanced Trade spot fills in a window, keyed by order id."""
    paging = self.app.advanced_trade.http.orders.historical.fills_paged(
      start_sequence_timestamp=start,
      end_sequence_timestamp=end,
      product_types=['SPOT'],
    )
    out: dict[str, SpotTrade] = {}
    for fill in await paging.via(self.call_app):
      trade = parse_fill(fill)
      if trade is not None and trade.order_id is not None:
        out[trade.order_id] = trade
    return out

  def record(self, observations: Sequence[Observation]) -> HistoryRecord:
    """Wrap observations in a record carrying this venue's provenance."""
    return HistoryRecord(
      observations=observations,
      provenance={'source': 'api', 'service': SERVICE, 'id': source_id(SERVICE)},
    )

  async def history(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterable[HistoryRecord]:
    """Stream the account's history over the given window."""
    end = end or datetime.now(timezone.utc)
    start = start or datetime.fromtimestamp(0, timezone.utc)
    fills = await self.fills(start, end)
    emitted: set[str] = set()

    for account_id in await self.accounts():
      for tx in await self.transactions(account_id):
        time = tx['created_at']
        if not start <= time <= end:
          continue
        order_id = (tx.get('advanced_trade_fill') or {}).get('order_id')
        if order_id is None:
          yield self.record([parse_transaction(tx)])
          continue
        trade = fills.get(order_id)
        # No matching fill row, or one already emitted: skip rather than guess a
        # trade shape out of the v2 sub-blob, which carries no maker/taker flag.
        if trade is not None and order_id not in emitted:
          emitted.add(order_id)
          yield self.record([trade])
