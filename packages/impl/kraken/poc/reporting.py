# %%
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from typing_extensions import Sequence

from typed_kraken import Kraken
from typed_kraken.spot.account.ledgers import LedgerEntry
from dotenv import load_dotenv

from tribulnation.sdk.reporting import (
  HistoryRecord,
  SnapshotRecord,
  Snapshot,
  SubaccountSnapshot,
  TradeLeg,
  FeeLeg,
  Yield,
  Bonus,
  Transfer,
  CryptoDeposit,
  CryptoWithdrawal,
  FiatDeposit,
  FiatWithdrawal,
  UnknownObservation,
  source_id,
)

load_dotenv()

client = await Kraken.new().__aenter__()

FIAT_ASSETS = {
  'ZUSD',
  'ZEUR',
  'ZGBP',
  'ZCAD',
  'ZJPY',
  'ZKRW',
  'ZAUD',
  'CHF',
  'USD',
  'EUR',
  'GBP',
  'CAD',
  'JPY',
}

# The concrete union of observation shapes `map_ledger_entry()` can produce -- a proper
# subset of the SDK's full `Observation` union (which also covers blockchain/EVM/Cosmos
# shapes this venue never emits). Narrower than `Observation` so that `.type` on an element
# stays within `FeeLeg.event_type`'s `ExchangeObservationType` domain.
LedgerObservation = (
  TradeLeg
  | FiatDeposit
  | CryptoDeposit
  | FiatWithdrawal
  | CryptoWithdrawal
  | Yield
  | Transfer
  | Bonus
  | UnknownObservation
  | FeeLeg
)


# %% [markdown]
# ## `History`
#
# Kraken has no single "unified history" endpoint -- `spot.account.ledgers` is the closest fit: every balance-affecting event (trades, deposits, withdrawals, staking rewards, transfers, ...) shows up there as one row per asset leg, which lines up well with the SDK's per-observation model.

# %%
def map_ledger_entry(ledger_id: str, entry: LedgerEntry) -> Sequence[LedgerObservation]:
  asset = entry.get('asset', '')
  amount = Decimal(entry.get('amount', '0'))
  time = entry.get('time')
  type_ = entry.get('type')
  fiat = asset in FIAT_ASSETS

  observations: list[LedgerObservation]
  if type_ == 'trade':
    # Kraken splits a trade into one ledger row per asset leg (base + quote), joined by
    # `refid` -- reconstructing a full `SpotTrade` (pair/price/side) would need
    # cross-referencing `account.trades_history`/`query_trades`. This notebook keeps the
    # simpler, per-row `TradeLeg` shape instead; see coverage notes.
    observations = [
      TradeLeg(
        id=ledger_id, time=time, asset=asset, amount=amount, event_type='spot_trade'
      )
    ]
  elif type_ == 'deposit':
    cls = FiatDeposit if fiat else CryptoDeposit
    observations = [cls(id=ledger_id, time=time, asset=asset, amount=abs(amount))]
  elif type_ == 'withdrawal':
    cls = FiatWithdrawal if fiat else CryptoWithdrawal
    observations = [cls(id=ledger_id, time=time, asset=asset, amount=amount)]
  elif type_ == 'staking':
    observations = [Yield(id=ledger_id, time=time, asset=asset, amount=amount)]
  elif type_ == 'transfer':
    observations = [Transfer(id=ledger_id, time=time, asset=asset, amount=amount)]
  elif type_ == 'reward':
    observations = [Bonus(id=ledger_id, time=time, asset=asset, amount=amount)]
  else:
    # margin/adjustment/rollover/credit/settled/sale/conversion/nft*/... -- Kraken has ~20
    # ledger types; only the common ones above get a precise Observation, everything else
    # falls back to Unknown rather than guessing at semantics. See coverage notes.
    observations = [
      UnknownObservation(id=ledger_id, time=time, asset=asset, amount=amount)
    ]

  fee = Decimal(entry.get('fee') or '0')
  if fee != 0:
    # `event_type` documents which *canonical* SDK observation this fee belongs to (one of
    # `ExchangeObservationType`'s literal values, e.g. 'crypto_deposit'/'yield'/'spot_trade'),
    # not Kraken's own raw ledger `type` string ('deposit'/'staking'/...) -- those two
    # vocabularies mostly don't overlap, so passing `type_` here directly would fail
    # `FeeLeg`'s pydantic validation for every ledger type except 'transfer'. Reuse the type
    # already resolved onto the primary observation above instead.
    observations.append(
      FeeLeg(
        id=f'{ledger_id}-fee',
        time=time,
        asset=asset,
        amount=fee,
        event_type=observations[0].type,
        event_id=ledger_id,
      )
    )
  return observations


def history(start: datetime | None = None, end: datetime | None = None):
  async def gen():
    ofs = 0
    while True:
      page = await client.spot.account.ledgers(
        start=int(start.timestamp()) if start is not None else None,
        end=int(end.timestamp()) if end is not None else None,
        ofs=ofs,
      )
      entries = page.get('ledger') or {}
      if not entries:
        break
      for ledger_id, entry in entries.items():
        yield HistoryRecord(
          observations=map_ledger_entry(ledger_id, entry),
          provenance={'id': ledger_id, 'source': 'api', 'service': 'kraken'},
        )
      if len(entries) < 50:
        break
      ofs += 50

  return gen()


end = datetime.now(timezone.utc)
start = end - timedelta(days=365)
[record async for record in history(start, end)]


# %% [markdown]
# ## `Snapshots`
#
# `spot.account.balance` is a direct fit for a point-in-time balance snapshot.

# %%
async def snapshot(assets: list[str] | None = None) -> SnapshotRecord:
  # `assets` is accepted per the interface but ignored -- Kraken's Balance endpoint always
  # enumerates every held asset in one call, so there's no discovery gap to fill (matches
  # the docstring: "for [venues like] CEXs it's ignored").
  raw = await client.spot.account.balance()
  balances = {asset: Decimal(amount) for asset, amount in raw.items()}
  return SnapshotRecord(
    snapshot=Snapshot(subaccounts=[SubaccountSnapshot(balances=balances)]),
    provenance={'id': source_id('kraken'), 'source': 'api', 'service': 'kraken'},
  )


await snapshot()

# %% [markdown]
# ## Coverage
#
# **`Snapshots`: fully supported.** `spot.account.balance` returns exactly what `snapshot()` needs; there is no derivatives/margin position concept on this spot-only client, so `positions` is always empty (`{}`) -- see `market.ipynb` for the same spot-has-no-positions point in the `Market` interface.
#
# **`History`: partially supported.** `spot.account.ledgers` covers the breadth of event types reasonably well (this notebook maps `trade`/`deposit`/`withdrawal`/`staking`/`transfer`/`reward` explicitly, falling back to `UnknownObservation` for the rest of Kraken's ~20 ledger types), but two things are approximated rather than exact:
#
# 1. **Trade reconstruction.** Kraken doesn't give a single ledger row with pair/price/side the way a full `SpotTrade` wants -- a trade shows up as two separate `trade` rows (one per asset leg) sharing a `refid`. This notebook keeps the simpler, source-preserving `TradeLeg` shape (one leg = one observation) rather than joining legs by `refid` and cross-referencing `account.trades_history` to recover price/side; a production implementation would likely do that join to emit proper `SpotTrade` observations.
# 2. **Provenance granularity.** Each `HistoryRecord` here wraps one ledger row (plus a synthetic fee leg when Kraken bundles a nonzero fee into the same row) rather than grouping every row sharing a `refid` into one record -- simpler, and still a valid `Provenance`, but it means a single logical trade currently spans two separate `HistoryRecord`s instead of one.
# 3. **`history` is blocked** on `LedgerEntry.time` is a bare `float` where the spec says `epoch-seconds` (`typed-client-issues.md`, codegen). Pydantic coerces the epoch to an aware UTC `datetime` at runtime, so the output above is right, but `BaseObservation.time` wants `AwareDatetime` and every constructor call in the cell fails `poc check` until the client renders `TimestampSeconds`. Not converted locally: the fix belongs in the client.
#
# `spot.account.ledgers` pages via `ofs` in blocks of 50; `history()` follows the pagination fully rather than capping it, since a `Report.History` consumer is expected to see the whole window regardless of how many ledger pages that takes.
