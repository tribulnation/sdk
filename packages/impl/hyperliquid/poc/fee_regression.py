# %%
"""Compare `fees()` with the fees charged on recent public fills, read-only.

Samples counterparty addresses from each market's public `trades` stream (its first push
replays recent prints), then for every sampled address reads the SDK's `fees()` and
`trades_history()` for that market and compares each fill's charged fee with the
amount the matching combined rate implies, and its fee asset with the expected token.
Rates are the account's current ones, so a fill made before a tier change can
legitimately differ; those show up as the occasional mismatch.

Nothing here signs or places anything: `fees()` and `trades_history()` are reads keyed by
a public address.
"""

import asyncio
from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from typing_extensions import TypeAlias, TypedDict

from tribulnation.sdk import Context, RateLimited
from tribulnation.sdk.market import Fees, Trade
from tribulnation.hyperliquid import HyperliquidMarket
from tribulnation.hyperliquid.market.perps_market import PerpMarket
from tribulnation.hyperliquid.market.spot_market import SpotMarket

VenueMarket: TypeAlias = SpotMarket | PerpMarket

MARKETS = [
  ':BTC',
  'xyz:xyz:SILVER',
  'para:para:VST',
  'spot:UBTC/USDC:142',
  'spot:USDT0/USDC:166',
  'spot:HYPE/USDE:255',
]
"""Default and HIP-3 USDC perpetuals, USDC spot, a stable pair and a USDE pair."""
ADDRESSES_PER_MARKET = 5
SAMPLE_SECONDS = 5
WINDOW = timedelta(days=1)

venue = await HyperliquidMarket.http(None, mainnet=True).__aenter__()
markets: dict[str, VenueMarket] = {}
for m in MARKETS:
  opened = await venue.market(m)
  assert isinstance(opened, (SpotMarket, PerpMarket))
  markets[m] = opened
{m: market.asset_name for m, market in markets.items()}


# %%
async def sample_users(coin: str) -> list[str]:
  """Distinct counterparties of recent prints, from the stream's first pushes."""
  users: list[str] = []
  stream = await venue.client.streams.trades(coin)

  async def collect():
    """Gather addresses until enough are seen."""
    async for prints in stream:
      for trade in prints:
        for user in trade['users']:
          if user not in users:
            users.append(user)
      if len(users) >= ADDRESSES_PER_MARKET:
        return

  try:
    await asyncio.wait_for(collect(), SAMPLE_SECONDS)
  except TimeoutError:
    pass
  finally:
    await stream.unsubscribe()
  return users[:ADDRESSES_PER_MARKET]


samples = {m: await sample_users(market.asset_name) for m, market in markets.items()}
{m: len(users) for m, users in samples.items()}


# %%
class Row(TypedDict):
  """One fill's charged fee against the amount the SDK's matching rate implies."""

  market: str
  role: str
  side: str
  fee_asset: str
  expected_asset: str
  amount: Decimal
  expected: Decimal
  quantum: Decimal
  """The fee amount's last decimal place, the venue's rounding unit for it."""


def expected_rate(fees: Fees, trade: Trade) -> Decimal:
  """The combined rate for the fill's liquidity role and side."""
  buy = trade.qty > 0
  if trade.maker:
    return fees.maker_buy if buy else fees.maker_sell
  return fees.taker_buy if buy else fees.taker_sell


def expected_asset(market: VenueMarket, trade: Trade) -> str:
  """Perpetuals settle in collateral; spot charges the received token and credits
  maker rebates in the given one."""
  if isinstance(market, PerpMarket):
    return str(market.collateral_meta['index'])
  assert trade.fee is not None
  base, quote = str(market.base_meta['index']), str(market.quote_meta['index'])
  receives_base = (trade.qty > 0) == (trade.fee.amount >= 0)
  return base if receives_base else quote


def row(market_id: str, market: VenueMarket, fees: Fees, trade: Trade) -> Row:
  """Compare one fill, measuring a base-token fee against size, else notional."""
  assert trade.fee is not None
  builder = Decimal(str(trade.details.get('builderFee') or 0))
  amount = trade.fee.amount - builder
  size = abs(trade.qty)
  in_base = isinstance(market, SpotMarket) and trade.fee.asset == str(
    market.base_meta['index']
  )
  return Row(
    market=market_id,
    role='maker' if trade.maker else 'taker',
    side='buy' if trade.qty > 0 else 'sell',
    fee_asset=trade.fee.asset,
    expected_asset=expected_asset(market, trade),
    amount=amount,
    expected=expected_rate(fees, trade) * (size if in_base else size * trade.price),
    quantum=Decimal(1).scaleb(int(trade.fee.amount.as_tuple().exponent)),
  )


async def compare(market_id: str, address: str) -> list[Row]:
  """Read one address's fees and recent fills on one market through the SDK."""
  base = markets[market_id]
  shared = replace(base.shared, maybe_address=address, user_fees=None)
  market = replace(base, shared=shared)
  fees = await market.fees()
  end = datetime.now(timezone.utc)
  rows: list[Row] = []
  async for page in market.trades_history(end - WINDOW, end):
    rows += [row(market_id, market, fees, t) for t in page if t.fee is not None]
  return rows


async def paced(market_id: str, address: str) -> list[Row]:
  """Retry rate-limited reads; `fees()` itself is not a retried SDK method."""
  for attempt in range(6):
    try:
      with Context().retried(RateLimited, max_retries=5, base_delay=5).use():
        return await compare(market_id, address)
    except RateLimited:
      await asyncio.sleep(15 * (attempt + 1))
  raise RuntimeError('Still rate limited')


rows: list[Row] = []
for market_id, users in samples.items():
  for user in users:
    rows += await paced(market_id, user)
len(rows)


# %%
def close(r: Row) -> bool:
  """Within one rounding unit of the charged amount, or 1% of it."""
  return abs(r['amount'] - r['expected']) <= max(r['quantum'], abs(r['expected']) / 100)


summary = Counter(
  (
    r['market'],
    r['role'],
    r['side'],
    r['fee_asset'],
    r['fee_asset'] == r['expected_asset'],
    close(r),
  )
  for r in rows
)
for (market_id, role, side, asset, asset_ok, ok), n in sorted(summary.items()):
  print(
    f'{market_id:22} {role:5} {side:4} fee_asset={asset:4} asset_ok={asset_ok!s:5} '
    f'rate_ok={ok!s:5} fills={n}'
  )


# %%
await venue.__aexit__(None, None, None)
