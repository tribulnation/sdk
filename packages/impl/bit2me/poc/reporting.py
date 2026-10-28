# %%
import asyncio
from decimal import Decimal
from datetime import datetime, timedelta, timezone

from typed_bit2me import Bit2Me
from dotenv import load_dotenv

from tribulnation.sdk.reporting import (
  CryptoDeposit,
  CryptoWithdrawal,
  Fee,
  HistoryRecord,
  Snapshot,
  SnapshotRecord,
  SpotTrade,
  SubaccountSnapshot,
  Yield,
  source_id,
)

load_dotenv()

client = await Bit2Me.new().__aenter__()

SPOT_MARKETS = ['BTC/EUR', 'ETH/EUR', 'USDT/EUR']


# %% [markdown]
# ## `Snapshots`
#
# Bit2Me splits balances across three separate sub-products with no shared ledger: the
# Trading Spot wallet (`v1.trading.balance`), Earn (`v2.earn.wallets`), and Wallet pockets
# (`v1.wallet.pockets.get`). Funds move between them only through explicit transfers
# (`v1/trading/wallet/{deposit,withdraw}` between spot and pockets; `v1/earn/movements`
# between earn and pockets), so they're not fungible views of one balance -- each becomes
# its own `SubaccountSnapshot`.

# %%
async def spot_balances(*, assets: list[str] | None = None) -> dict[str, Decimal]:
  out: dict[str, Decimal] = {}
  for entry in await client.v1.trading.balance():
    asset = entry.get('currency')
    if asset is None or (assets is not None and asset not in assets):
      continue
    total = Decimal(str(entry.get('balance', 0))) + Decimal(
      str(entry.get('blockedBalance', 0))
    )
    out[asset] = out.get(asset, Decimal(0)) + total
  return out


await spot_balances()


# %%
async def earn_balances(*, assets: list[str] | None = None) -> dict[str, Decimal]:
  out: dict[str, Decimal] = {}
  resp = await client.v2.earn.wallets(limit=100)
  for entry in resp.get('data', []):
    asset = entry.get('currency')
    if asset is None or (assets is not None and asset not in assets):
      continue
    out[asset] = out.get(asset, Decimal(0)) + entry.get('balance', Decimal(0))
  return out


await earn_balances()


# %%
async def pocket_balances(*, assets: list[str] | None = None) -> dict[str, Decimal]:
  out: dict[str, Decimal] = {}
  for entry in await client.v1.wallet.pockets.get():
    asset = entry.get('currency')
    if asset is None or (assets is not None and asset not in assets):
      continue
    total = entry.get('balance', Decimal(0)) + entry.get('blockedBalance', Decimal(0))
    out[asset] = out.get(asset, Decimal(0)) + total
  return out


await pocket_balances()


# %%
async def snapshot(assets: list[str] | None = None) -> SnapshotRecord:
  spot, earn, pocket = await asyncio.gather(
    spot_balances(assets=assets),
    earn_balances(assets=assets),
    pocket_balances(assets=assets),
  )
  return SnapshotRecord(
    snapshot=Snapshot(
      subaccounts=[
        SubaccountSnapshot(subaccount='spot', balances=spot),
        SubaccountSnapshot(subaccount='earn', balances=earn),
        SubaccountSnapshot(subaccount='pocket', balances=pocket),
      ]
    ),
    provenance={'source': 'api', 'service': 'bit2me', 'id': source_id('bit2me')},
  )


await snapshot()

# %%
# `assets` is accepted per the abstract `Snapshots.snapshot()` signature but ignored by
# every helper above -- all three balance endpoints always enumerate every held asset in
# one call, so (per the abstract docstring, meant for venues without full enumeration)
# there's no discovery gap here for `assets` to fill.
await snapshot(assets=['BTC', 'ETH'])


# %% [markdown]
# ## `History`
#
# No single Bit2Me endpoint is a unified ledger. This notebook maps three separately-shaped
# sources, each hand-picked for having an unambiguous `Observation` mapping:
#
# - **Spot trades**: `v1.trading.trade` (`client.v1.trading.trades.list`), per market symbol,
#   natively filterable by `startTime`/`endTime`.
# - **Crypto deposits/withdrawals**: `v2.wallet.transaction`
#   (`client.v2.wallet.transactions`) filtered to `operation='receive'`/`'send'` -- *not*
#   `'deposit'`/`'withdrawal'`, which select the fiat bank/card rows -- and then to rows
#   where the blockchain side's `class` is `'blockchain'`. The only date filter is `year`,
#   so the requested `start`/`end` window is walked one year at a time and re-applied
#   client-side.
# - **Earn rewards**: `v1.earn.wallets.list_movements`, one call per Earn wallet (there's no
#   cross-wallet movements endpoint), filtered to `type == 'reward'`.

# %%
async def spot_trades(start: datetime, end: datetime) -> list[SpotTrade]:
  out: list[SpotTrade] = []
  for symbol in SPOT_MARKETS:
    base, quote = symbol.split('/')
    resp = await client.v1.trading.trades.list(
      symbol=symbol, start_time=start, end_time=end, limit=100
    )
    for t in resp.get('data', []):
      side = t.get('side')
      amount = Decimal(str(t.get('amount', 0)))
      size = amount if side == 'buy' else -amount
      price = t.get('price')
      fee_amount = t.get('feeAmount')
      fee_currency = t.get('feeCurrency')
      out.append(
        SpotTrade(
          id=t.get('id'),
          time=t.get('createdAt'),
          base=base,
          quote=quote,
          pair=symbol,
          size=size,
          price=Decimal(str(price)) if price is not None else None,
          order_id=t.get('orderId'),
          fee=Fee(amount=Decimal(str(fee_amount)), asset=fee_currency)
          if fee_amount and fee_currency
          else None,
        )
      )
  return out


end = datetime.now(timezone.utc)
start = end - timedelta(days=30)
await spot_trades(start, end)


# %%
async def crypto_deposits(start: datetime, end: datetime) -> list[CryptoDeposit]:
  out: list[CryptoDeposit] = []
  # On-chain credits are `operation='receive'`, not `'deposit'`: `'deposit'`/`'withdrawal'`
  # select the fiat (bank/card) rows, and asking for `'deposit'` returns nothing at all on
  # this account. Only `year` is filterable server-side, so the window is walked one year
  # at a time and re-applied client-side afterwards.
  for year in range(start.year, end.year + 1):
    resp = await client.v2.wallet.transactions(
      operation='receive', limit=100, year=year
    )
    for tx in resp.get('data', []):
      origin = tx.get('origin') or {}
      dest = tx.get('destination') or {}
      time = tx.get('date')
      asset = dest.get('currency')
      if (
        origin.get('class') != 'blockchain'
        or time is None
        or asset is None
        or not (start <= time <= end)
      ):
        continue
      if tx.get('status') != 'completed':
        continue
      net_fee = (tx.get('fee') or {}).get('network')
      fee_amount = net_fee.get('amount') if net_fee else None
      fee_currency = net_fee.get('currency') if net_fee else None
      out.append(
        CryptoDeposit(
          id=tx.get('id'),
          time=time,
          asset=asset,
          amount=dest.get('amount', Decimal(0)),
          # On a deposit the blockchain side is the *origin*, but it carries neither
          # `address` nor `addressNetwork` -- both sit on the crediting pocket instead.
          network=dest.get('addressNetwork'),
          tx_id=(tx.get('transaction') or {}).get('hash'),
          src_address=origin.get('address'),
          dst_address=dest.get('address'),
          fee=Fee(amount=fee_amount, asset=fee_currency)
          if fee_amount and fee_currency
          else None,
        )
      )
  return out


end = datetime.now(timezone.utc)
start = end - timedelta(days=365)
await crypto_deposits(start, end)


# %%
async def crypto_withdrawals(start: datetime, end: datetime) -> list[CryptoWithdrawal]:
  out: list[CryptoWithdrawal] = []
  # Mirror of `crypto_deposits`: on-chain debits are `operation='send'`. `'withdrawal'`
  # returns the fiat bank-transfer rows instead, which is why filtering by it and then
  # discarding everything whose destination isn't `'blockchain'` yields nothing.
  for year in range(start.year, end.year + 1):
    resp = await client.v2.wallet.transactions(operation='send', limit=100, year=year)
    for tx in resp.get('data', []):
      origin = tx.get('origin') or {}
      dest = tx.get('destination') or {}
      time = tx.get('date')
      asset = origin.get('currency')
      if (
        dest.get('class') != 'blockchain'
        or time is None
        or asset is None
        or not (start <= time <= end)
      ):
        continue
      # Cancelled withdrawals stay in the listing with the amount they would have sent.
      if tx.get('status') != 'completed':
        continue
      net_fee = (tx.get('fee') or {}).get('network')
      fee_amount = net_fee.get('amount') if net_fee else None
      fee_currency = net_fee.get('currency') if net_fee else None
      out.append(
        CryptoWithdrawal(
          id=tx.get('id'),
          time=time,
          asset=asset,
          amount=-origin.get('amount', Decimal(0)),
          network=dest.get('addressNetwork'),
          tx_id=(tx.get('transaction') or {}).get('hash'),
          src_address=origin.get('address'),
          dst_address=dest.get('address'),
          fee=Fee(amount=fee_amount, asset=fee_currency)
          if fee_amount and fee_currency
          else None,
        )
      )
  return out


end = datetime.now(timezone.utc)
start = end - timedelta(days=365)
await crypto_withdrawals(start, end)


# %%
async def earn_yield(start: datetime, end: datetime) -> list[Yield]:
  wallets = await client.v2.earn.wallets(limit=100)
  out: list[Yield] = []
  for w in wallets.get('data', []):
    wallet_id = w.get('walletId')
    if wallet_id is None:
      continue
    movements = await client.v1.earn.wallets.list_movements(
      wallet_id=wallet_id,
      limit=50,
      sort_by='createdAt',
      sort_direction='descending',
    )
    for m in movements.get('data', []):
      time = m.get('createdAt')
      if m.get('type') != 'reward' or time is None or not (start <= time <= end):
        continue
      net = m.get('netAmount') or m.get('amount') or {}
      value = net.get('value')
      currency = net.get('currency')
      if value is None or currency is None:
        continue
      out.append(
        Yield(
          id=m.get('movementId'),
          time=time,
          asset=currency,
          amount=value,
        )
      )
  return out


end = datetime.now(timezone.utc)
start = end - timedelta(days=7)
await earn_yield(start, end)


# %%
async def history(start: datetime | None = None, end: datetime | None = None):
  end = end or datetime.now(timezone.utc)
  start = start or end - timedelta(days=1)
  groups = await asyncio.gather(
    spot_trades(start, end),
    crypto_deposits(start, end),
    crypto_withdrawals(start, end),
    earn_yield(start, end),
  )
  for group in groups:
    for observation in group:
      yield HistoryRecord(
        observations=[observation],
        provenance={'source': 'api', 'service': 'bit2me', 'id': source_id('bit2me')},
      )


end = datetime.now(timezone.utc)
start = end - timedelta(days=1)
[record async for record in history(start, end)]

# %% [markdown]
# ## Coverage
#
# **`Snapshots`: fully supported.** `spot_balances()`, `earn_balances()`, and
# `pocket_balances()` each map 1:1 onto one endpoint, and `snapshot()` composes them with no
# loss. There's no derivatives/margin concept on this venue, so `SubaccountSnapshot.positions`
# is always empty -- expected, not a gap. `assets` is accepted but ignored, consistent with
# the abstract docstring for a venue that always enumerates every held asset regardless.
#
# **`History`: partially supported.** Spot trades, on-chain deposits/withdrawals, and Earn
# reward payouts each map onto their matching `Observation` subtype and are live-tested
# above: 10 deposits and 8 withdrawals across four networks in the last year, plus the daily
# B2M reward payouts. Three things the mapping cannot fill in, all confirmed against every
# `receive`/`send` row this account has (2025 and 2026, both directions):
#
# - **`tx_id` is always `None`.** `v2.wallet.transaction`'s `transaction` object only ever
#   carries `confirmedAt`/`confirmationCount`; the `hash` its schema declares is never
#   actually returned, so the on-chain hash isn't recoverable from this endpoint.
# - **`src_address` is always `None`.** Only one side of a transfer carries
#   `address`/`addressNetwork`, and it is the *pocket* side in both directions -- so a
#   deposit's `network` has to be read off the destination (the blockchain `origin` has
#   neither field), and the sender's address is never reported at all.
# - **`fee` is always `None`.** No row in either year carries a `fee` object, so the network
#   fee a withdrawal paid is not in the history listing (`v1.wallet.transactions.preview()`,
#   used in `wallet.ipynb`, is the only place a withdrawal fee shows up).
#
# The `year` filter is also the only date filter (`v2.wallet.transaction` has no
# `startTime`/`endTime` params, unlike `v1.trading.trade`), so both helpers walk
# `start.year..end.year` and re-apply the window client-side. Cancelled withdrawals stay in
# the listing with the amount they would have sent, so rows whose `status` isn't
# `'completed'` are dropped.
#
# **Not covered here, but present on the venue:**
# - **Internal transfers** between spot/earn/pocket compartments (`origin.class`/
#   `destination.class` of `'pocket'`/`'trading'`/`'earn'`, reachable through the
#   `deposit-earn`/`withdrawal-earn`/`deposit-trading`/`withdrawal-trading` operations) --
#   would map to `InternalTransfer`, omitted here to keep the demonstrated mapping to the
#   sources whose semantics this notebook actually confirmed end-to-end.
# - **Fiat deposits/withdrawals** (bank transfer, card/Teller purchases) -- same
#   `v2.wallet.transaction` endpoint. `operation='withdrawal'` returns them (this account
#   has a `pocket -> bankAccount` row); the matching fiat *deposit* (`subtype='funding'`,
#   `method='bank-transfer'`) shows up in the unfiltered listing but is returned by no
#   `operation` value at all, which is why the fiat side isn't mapped here.
# - **Loans** (`v1.loan.movements`, `v1.loan.orders`) and **Social Pay** (`v1.social_pay`) --
#   separate ledgers, not explored here.
# - **`crypto_ws`** -- the Crypto API WebSocket (`authenticate`, then the account's own
#   notification firehose). `docs/contract/report.yml` declares only `snapshot` and
#   `history`, with no streaming method for it to implement, so it is deliberately left
#   unmapped.
#
# `v1.wallet.transaction` and `v3.wallet.transaction` both exist as alternatives to
# `v2.wallet.transaction`. v1 is marked `@deprecated` in `typed_bit2me` and is gone upstream
# too -- calling it returns `404 Cannot GET /v1/wallet/transaction`. v3 works on this
# account's credentials and returns identically-shaped rows, but pages by opaque cursor
# instead of `offset`, and its listing is not year-scoped (one 100-row page spans 2025 and
# 2026), so it -- not the year walk above -- is what a real implementation should use.
# `v2` is kept here because it is the version whose `operation`/`year` filtering this
# notebook mapped against.
#
# No subscribe/redeem/withdraw call exists in the abstract `Report` interface for this
# venue, so every call above is read-only and there was nothing to write-but-not-execute.
