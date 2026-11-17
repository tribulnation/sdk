"""Account fees, positions, the cross margin bucket, leverage and spot balances of the
configured subaccount.

A Nado subaccount is one unified cross-margin account: its spot balances (USDT0 and
every other spot asset, signed, negative when borrowed) and its perpetual positions
are margined together by health. `subaccount_info` reports health three ways, in
USDT0: `initial` (what new orders and withdrawals may still use), `maintenance`
(liquidation at zero) and `unweighted` (the account's value). Resting orders hold
nothing: placing and cancelling a post-only order left all three unchanged (mainnet,
2026-11-17), the venue checking health only when an order is placed and when it fills.
"""

from datetime import timedelta
from decimal import Decimal

from typing_extensions import NoReturn
from typed_nado.gateway.fee_rates import FeeRates
from typed_nado.schemas import AllProducts, SubaccountInfo
from tribulnation.sdk.market import Balance, Fees, PerpCollateral, PerpPosition

from ..core import QUOTE_ASSET, QUOTE_PRODUCT, Shared, x18

INITIAL, MAINTENANCE, UNWEIGHTED = 0, 1, 2
"""Positions of the three healths in `healths`."""


async def summary(shared: Shared, *, ttl: timedelta | None = None) -> SubaccountInfo:
  """The subaccount's healths, balances and positions; one answer serves every market,
  shared for the caller's `ttl`."""
  sender = shared.require_sender()
  return await shared.reads.read(
    ('subaccount_info', sender),
    lambda: shared.call(
      lambda: shared.client.gateway.subaccount_info(subaccount=sender)
    ),
    ttl=ttl,
  )


async def isolated_products(
  shared: Shared, *, ttl: timedelta | None = None
) -> set[int]:
  """The perpetuals the subaccount holds an isolated position on."""
  sender = shared.require_sender()
  reply = await shared.reads.read(
    ('isolated_positions', sender),
    lambda: shared.call(lambda: shared.client.gateway.isolated_positions(sender)),
    ttl=ttl,
  )
  return {
    p['base_balance']['product_id']
    for p in reply['isolated_positions']
    if int(p['base_balance']['balance']['amount'])
  }


def unsupported_isolated(symbol: str) -> NoReturn:
  """The error for a market holding an isolated position."""
  raise NotImplementedError(
    f'Nado isolated positions are not supported: {symbol} has one, in its own '
    'isolated subaccount'
  )


async def fee_rates(shared: Shared) -> FeeRates:
  """The subaccount's fee rates per product."""
  sender = shared.require_sender()
  return await shared.reads.read(
    ('fee_rates', sender),
    lambda: shared.call(lambda: shared.client.gateway.fee_rates(sender)),
    ttl=timedelta(minutes=1),
  )


async def fees(shared: Shared, product_id: int) -> Fees:
  """The subaccount's maker and taker rates on one product, the same for both sides
  (`fee_rates`, indexed by product id; a maker rebate is negative)."""
  rates = await fee_rates(shared)
  return Fees.symmetric(
    maker=x18(rates['maker_fee_rates_x18'][product_id]),
    taker=x18(rates['taker_fee_rates_x18'][product_id]),
  )


async def all_products(shared: Shared) -> AllProducts:
  """Every product's risk weights and state, shared for a minute: the weights are
  configuration."""
  return await shared.reads.read(
    ('all_products',),
    lambda: shared.call(shared.client.gateway.all_products),
    ttl=timedelta(minutes=1),
  )


async def leverage(shared: Shared, product_id: int) -> Decimal:
  """The leverage cross margin allows on a perpetual, from its initial risk weights.

  A long of notional `n` needs `n * (1 - long_weight_initial)` of initial health and a
  short `n * (short_weight_initial - 1)`; the leverage is the inverse of the larger of
  the two, so it holds for either side (they are equal on every market sampled,
  2026-11-17: `0.9`/`1.1`, 10x, on BTC-PERP). Nado has no per-account leverage setting
  for cross margin.

  Raises:
    ValueError: Nado lists no perpetual with that product id.
  """
  products = await all_products(shared)
  for p in products['perp_products']:
    if p['product_id'] == product_id:
      risk = p['risk']
      margin = max(
        1 - x18(risk['long_weight_initial_x18']),
        x18(risk['short_weight_initial_x18']) - 1,
      )
      return 1 / margin
  raise ValueError(f'Unknown Nado perpetual product: {product_id}')


def perp_amount(info: SubaccountInfo, product_id: int) -> Decimal:
  """The subaccount's cross position on a perpetual, in base units."""
  for b in info['perp_balances']:
    if b['product_id'] == product_id:
      return x18(b['balance']['amount'])
  return Decimal(0)


async def perp_position(
  shared: Shared, symbol: str, product_id: int, *, ttl: timedelta | None = None
) -> PerpPosition:
  """The signed cross position, at the archive's `average_entry_price` of the open
  position window; flat when the subaccount holds none.

  Raises:
    NotImplementedError: The market holds an isolated position.
  """
  info = await summary(shared, ttl=ttl)
  if product_id in await isolated_products(shared, ttl=ttl):
    unsupported_isolated(symbol)
  size = perp_amount(info, product_id)
  if not size:
    return PerpPosition(size=Decimal(0))
  sender = shared.require_sender()
  windows = await shared.call(
    lambda: shared.client.archive.positions(
      sender, product_id=product_id, isolated=False, open=True, limit=1
    )
  )
  rows = windows['positions']
  entry = x18(rows[0]['average_entry_price']) if rows else Decimal(0)
  return PerpPosition(size=size, entry_price=entry)


def cross_bucket(info: SubaccountInfo) -> PerpCollateral:
  """The cross-margin bucket: the whole subaccount.

  `equity` is the unweighted health (the account's value in USDT0), the margins are
  how far the initial and maintenance healths sit below it, and the free collateral is
  the initial health, what new orders may still use (never negative). `leverage` is the
  perpetual notional at oracle prices over the equity.
  """
  healths = [x18(h['health']) for h in info['healths']]
  equity = healths[UNWEIGHTED]
  prices = {p['product_id']: x18(p['oracle_price_x18']) for p in info['perp_products']}
  notional = sum(
    (
      abs(x18(b['balance']['amount'])) * prices.get(b['product_id'], Decimal(0))
      for b in info['perp_balances']
    ),
    Decimal(0),
  )
  return PerpCollateral(
    equity=equity,
    free_collateral=max(healths[INITIAL], Decimal(0)),
    initial_margin=equity - healths[INITIAL],
    maintenance_margin=equity - healths[MAINTENANCE],
    leverage=notional / equity if equity > 0 and notional else Decimal(0),
    margin_mode='cross',
  )


async def market_bucket(
  shared: Shared, symbol: str, product_id: int, *, ttl: timedelta | None = None
) -> PerpCollateral:
  """The cross bucket backing a perpetual.

  Raises:
    NotImplementedError: The market holds an isolated position.
  """
  info = await summary(shared, ttl=ttl)
  if product_id in await isolated_products(shared, ttl=ttl):
    unsupported_isolated(symbol)
  return cross_bucket(info)


def spot_amount(info: SubaccountInfo, product_id: int) -> Decimal:
  """The subaccount's balance of a spot product, negative when borrowed."""
  for b in info['spot_balances']:
    if b['product_id'] == product_id:
      return x18(b['balance']['amount'])
  return Decimal(0)


def spot_balance(info: SubaccountInfo, product_id: int) -> Balance:
  """One spot asset's balance.

  `total` is the venue's signed balance (negative when borrowed). Orders hold nothing,
  so `free` is what can be spent without borrowing: the balance, never negative; for
  USDT0, which also margins every position, it is further capped at the initial health
  (what the account may still commit).
  """
  total = spot_amount(info, product_id)
  free = max(total, Decimal(0))
  if product_id == QUOTE_PRODUCT:
    free = max(min(free, x18(info['healths'][INITIAL]['health'])), Decimal(0))
  return Balance(total=total, free=free)


async def balance(
  shared: Shared, asset: str, *, ttl: timedelta | None = None
) -> Balance:
  """A spot asset's balance by asset id (`USDT0`, or a spot symbol such as `KBTC`).

  Raises:
    ValueError: Nado lists no spot asset with that id.
  """
  if asset == QUOTE_ASSET:
    product_id = QUOTE_PRODUCT
  else:
    product_id = (await shared.symbol(asset, type='spot'))['product_id']
  return spot_balance(await summary(shared, ttl=ttl), product_id)
