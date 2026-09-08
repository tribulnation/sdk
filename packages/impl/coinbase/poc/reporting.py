# %%
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing_extensions import AsyncIterable

from typed_coinbase import Coinbase
from typed_coinbase.app.accounts.transactions.list import Transaction
from dotenv import load_dotenv

from tribulnation.sdk.reporting import (
  CryptoDeposit,
  CryptoWithdrawal,
  Fee,
  FiatDeposit,
  FiatWithdrawal,
  HistoryRecord,
  Observation,
  Position,
  Snapshot,
  SnapshotRecord,
  SpotTrade,
  SubaccountSnapshot,
  UnknownObservation,
  source_id,
)

load_dotenv()

client = await Coinbase.new().__aenter__()

# How far back to page v2 account transaction history for this exploration.
LOOKBACK = timedelta(days=180)


# %% [markdown]
# ## `Report` — history

# %% [markdown]
# The richest history source is `app.accounts.transactions.list` (v2), one page per
# account, with a `type` enum covering trades, sends/receives, fiat rails, and this
# account's passive staking program (see `earn.ipynb`). Not every `type` carries enough
# structure to map into a specific `Observation` confidently:
#
# - `send` -> `CryptoWithdrawal` or `CryptoDeposit`, by the sign of `amount`: v2 types
#   onchain transfers in *both* directions as `send` (this account's one inbound transfer,
#   +10 USDC over arbitrum, is a `send` row with no `to`), so the type alone doesn't say
#   which way the value moved. `receive` -> `CryptoDeposit` for venues that do emit it;
#   this account has no `receive` row in any of its twelve wallets.
# - `fiat_deposit`/`fiat_withdrawal` -> `FiatDeposit`/`FiatWithdrawal`.
# - `advanced_trade_fill` carries a real `product_id`/`fill_price`/`order_side` sub-object
#   and maps to `SpotTrade` directly from this endpoint.
# - Everything else (`trade`/`buy`/`sell` from the legacy Simple UI, `staking_transfer`,
#   `staking_reward`, `earn_payout`, `incentives_rewards_payout`, `transfer`, ...) only
#   gives one signed leg in `amount` with no paired asset/price -- these fall back to
#   `UnknownObservation` rather than guessing a `SpotTrade`/`Conversion` shape the source
#   doesn't actually support.
#
# `app.advanced_trade.http.orders.historical.fills` is a second, richer source for spot
# trades specifically (real `product_id`, `side`, `price`, per-fill `commission`, and a
# `liquidity_indicator` for maker/taker) — preferred over `advanced_trade_fill` sub-blobs
# when both are available, so `SpotTrade`s from it are emitted instead of (not in addition
# to) the matching `advanced_trade_fill` transaction rows, deduplicated by `order_id`.
#
# `Transaction.type` covers every row kind this account produces, `staking_reward` included, so
# every wallet's page validates as-is.

# %%
def transaction_to_observations(tx: Transaction, time: datetime) -> list[Observation]:
  """Map one `app.accounts.transactions` row to an `Observation`, for row kinds not
  better covered by `orders.historical.fills` (see `fills_as_trades` below)."""
  kind = tx['type']
  amount = Decimal(tx['amount']['amount'])
  asset = tx['amount']['currency']

  if kind == 'send' and 'network' in tx:
    # v2 types onchain transfers both ways as `send`; the sign of `amount` is what
    # separates them (verified live: a +10 USDC arbitrum `send` row with no `to` is an
    # inbound deposit, the negative ones are withdrawals).
    if amount > 0:
      return [
        CryptoDeposit(
          id=tx['id'],
          time=time,
          asset=asset,
          amount=amount,
          network=tx['network'].get('network_name'),
          tx_id=tx['network'].get('hash'),
        )
      ]
    return [
      CryptoWithdrawal(
        id=tx['id'],
        time=time,
        asset=asset,
        amount=amount,
        network=tx['network'].get('network_name'),
        tx_id=tx['network'].get('hash'),
        dst_address=(tx.get('to') or {}).get('address'),
      )
    ]
  if kind == 'receive' and 'network' in tx:
    return [
      CryptoDeposit(
        id=tx['id'],
        time=time,
        asset=asset,
        amount=amount,
        network=tx['network'].get('network_name'),
        tx_id=tx['network'].get('hash'),
      )
    ]
  if kind == 'fiat_deposit':
    return [FiatDeposit(id=tx['id'], time=time, asset=asset, amount=amount)]
  if kind == 'fiat_withdrawal':
    return [FiatWithdrawal(id=tx['id'], time=time, asset=asset, amount=amount)]
  # transfer / trade / buy / sell / staking_transfer / staking_reward / earn_payout /
  # incentives_rewards_payout / tx / ... -- no reliable paired-asset structure on this
  # endpoint (see markdown above).
  return [UnknownObservation(id=tx['id'], time=time, asset=asset, amount=amount)]


async def fills_as_trades(start: datetime, end: datetime) -> dict[str, SpotTrade]:
  """`SpotTrade`s from Advanced Trade fills, keyed by order id (the richer source)."""
  out: dict[str, SpotTrade] = {}
  fills = await client.app.advanced_trade.http.orders.historical.fills(
    start_sequence_timestamp=start,
    end_sequence_timestamp=end,
    product_types=['SPOT'],
    limit=250,
  )
  for fill in fills['fills']:
    product_id = fill.get('product_id')
    order_id = fill.get('order_id')
    if not product_id or not order_id:
      continue
    base, _, quote = product_id.partition('-')
    size_raw = fill.get('size')
    size = Decimal(size_raw) if size_raw else None
    if size is not None and fill.get('side') == 'SELL':
      size = -size
    commission = fill.get('commission')
    fee = None
    if commission and Decimal(commission) != 0:
      fee = Fee(amount=Decimal(commission), asset=quote)
    price = fill.get('price')
    out[order_id] = SpotTrade(
      id=fill.get('trade_id'),
      time=fill.get('trade_time'),
      base=base,
      quote=quote,
      pair=product_id,
      size=size,
      price=Decimal(price) if price else None,
      order_id=order_id,
      fee=fee,
    )
  return out


async def history(
  start: datetime | None = None,
  end: datetime | None = None,
) -> AsyncIterable[HistoryRecord]:
  """Coinbase App reporting history: v2 transactions per account, with Advanced Trade
  fills substituted in for richer `SpotTrade`s where an `order_id` overlaps."""
  end = end or datetime.now(timezone.utc)
  start = start or (end - LOOKBACK)
  fills_by_order = await fills_as_trades(start, end)
  seen_orders: set[str] = set()

  accounts_page = await client.app.accounts.list(limit=100)
  for account in accounts_page['data']:
    page = await client.app.accounts.transactions.list(
      account_id=account['id'],
      limit=100,
    )
    for tx in page['data']:
      time = tx['created_at']
      if not (start <= time <= end):
        continue
      order_id = (tx.get('advanced_trade_fill') or {}).get('order_id')
      if order_id:
        trade = fills_by_order.get(order_id)
        if trade is None or order_id in seen_orders:
          continue  # no matching fill row (or already emitted) -- skip rather than guess
        seen_orders.add(order_id)
        observations = [trade]
      else:
        observations = transaction_to_observations(tx, time)
      yield HistoryRecord(
        observations=observations,
        provenance={
          'source': 'api',
          'service': 'coinbase',
          'id': source_id('coinbase'),
        },
      )


[record async for record in history()][:20]


# %% [markdown]
# **Coverage**: partially supported, live-tested above. `CryptoDeposit`, `CryptoWithdrawal`
# and `SpotTrade` all mapped against real activity in the 180-day window: two `send` rows
# over arbitrum (one inbound, one outbound) and two `advanced_trade_fill` rows matched to
# `orders.historical.fills`. `FiatDeposit`/`FiatWithdrawal` are written but unexercised
# here -- this account's only fiat row (a EUR `fiat_deposit`) predates the window, so those
# two branches are untested against live data; the same goes for `receive`, which this
# account has never produced in any wallet. The rest of the window is `trade`,
# `staking_transfer` and `staking_reward` rows falling through to `UnknownObservation`, as
# described above. `FutureTrade`/`Funding`/`RealizedPnl` have
# no source on this key (no CFM/INTX derivatives activity, and INTX itself returns
# `PERMISSION_DENIED` -- see `market.ipynb`). No pagination-window cap was hit; very long
# histories would need `starting_after` cursor pages instead of one page per account.

# %% [markdown]
# ## `Report` — snapshots

# %% [markdown]
# Balances live in two parallel places: `app.accounts` (v2 wallets/vault/fiat) and
# `app.advanced_trade.http.accounts` (v3 brokerage accounts backing Advanced Trade
# trading). Both are summed into the snapshot below as separate subaccounts. Futures (CFM)
# positions are queried too, for completeness, via `app.advanced_trade.http.futures`
# (empty on this account -- no CFM futures wallet). INTX perpetuals positions are not
# reachable at all on this key (`PERMISSION_DENIED`, see `market.ipynb`) and are omitted
# rather than guessed.

# %%
async def snapshot(assets: list[str] | None = None) -> SnapshotRecord:
  v2_balances: dict[str, Decimal] = {}
  page = await client.app.accounts.list(limit=100)
  for account in page['data']:
    asset = account['balance']['currency']
    if assets is not None and asset not in assets:
      continue
    v2_balances[asset] = v2_balances.get(asset, Decimal(0)) + Decimal(
      account['balance']['amount']
    )

  v3_balances: dict[str, Decimal] = {}
  v3_page = await client.app.advanced_trade.http.accounts.list(limit=100)
  for account in v3_page['accounts']:
    asset = account['currency']
    if assets is not None and asset not in assets:
      continue
    v3_balances[asset] = v3_balances.get(asset, Decimal(0)) + Decimal(
      account['available_balance']['value']
    )

  futures_positions: dict[str, Position] = {}
  futures_resp = await client.app.advanced_trade.http.futures.positions.list()
  for position in futures_resp['positions']:
    futures_positions[position['product_id']] = Position(
      size=Decimal(position['number_of_contracts']),
      avg_price=Decimal(position['avg_entry_price']),
    )

  return SnapshotRecord(
    snapshot=Snapshot(
      subaccounts=[
        SubaccountSnapshot(subaccount='accounts', balances=v2_balances),
        SubaccountSnapshot(subaccount='advanced_trade', balances=v3_balances),
        SubaccountSnapshot(subaccount='futures', positions=futures_positions),
      ]
    ),
    provenance={'source': 'api', 'service': 'coinbase', 'id': source_id('coinbase')},
  )


await snapshot()

# %% [markdown]
# **Coverage**: mostly supported, live-tested above. `accounts`/`advanced_trade` balances
# are both real and complete for this key. `positions` is partial: the CFM futures path
# works (returns an empty book, correctly) but INTX perpetual positions are unreachable on
# this key's permissions -- the interface would report them under a fourth
# `perpetuals`-style subaccount once a portfolio has INTX access.
