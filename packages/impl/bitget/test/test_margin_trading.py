"""Trading a Bitget UTA spot-margin pair end to end against a fake unified pool.

The fake keeps per-coin balances the way Bitget reported them live on 2026-11-21: a
resting margin sell auto-borrows the base it lacks at placement and locks it, leaving
`balance` (net of debt, excluding what is locked) at minus the borrow, and buys repay
debt first (`repayMode: auto`). What a hedger must see is the net exposure: nothing
while the sell rests, minus its size once it fills, nothing again once bought back.
"""

from typing_extensions import TYPE_CHECKING, Any, AsyncIterator
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from tribulnation.bitget.market import BitgetMarket, MarginMarket
from tribulnation.bitget.market.impl.account import (
  margin_exposure,
  spot_holding,
  spot_position,
)
from tribulnation.sdk.core import Subscription
from tribulnation.sdk.market import Settings

if TYPE_CHECKING:
  from typed_bitget.uta.account.assets import AccountAsset
  from conftest import FakeMargin

PAIR = 'LITUSDT'


def bodies(fake: 'FakeMargin') -> list[dict[str, Any]]:
  """The bodies of every `place-order` request so far."""
  return [p for _, e, p in fake.requests if e == 'trade/place-order']


async def test_the_market_id_and_rules_come_from_the_margin_catalogue(
  margin: MarginMarket,
):
  """`bg:margin:LITUSDT`, with tick, step and minimums read off the unvalidated row."""
  assert margin.id == 'bg:margin:LITUSDT'
  rules = await margin.rules()
  assert rules.tick_size == Decimal('0.0001') and rules.step_size == Decimal('0.01')
  assert rules.fixed_min_qty == Decimal('0.01') and rules.min_value == 1
  assert rules.max_qty is None and rules.api
  assert rules.rel_min_price == Decimal('0.9') and rules.fee_asset == 'USDT'


async def test_a_resting_borrowed_sell_is_no_exposure_until_it_fills(
  margin_fake: 'FakeMargin', margin: MarginMarket
):
  """The maker's sell: auto-borrowed at placement, yet the position stays flat while
  it rests (a hedger must not hedge it), and is short its size once it fills."""
  r = await margin.place_order(
    {'type': 'POST_ONLY', 'qty': Decimal(-10), 'price': Decimal('2.32')}
  )
  [body] = bodies(margin_fake)
  assert body['side'] == 'sell' and body['timeInForce'] == 'post_only'
  assert margin_fake.lit.row('LIT')['balance'] == '-10'
  assert margin_fake.lit.debt == 10 and margin_fake.lit.locked == 10
  assert (await margin.position()).size == 0
  assert await margin.delta() == 0
  [listed] = await margin.open_orders()
  assert listed.id == r.id and listed.qty == -10
  margin_fake.fill(r.id)
  assert (await margin.position()).size == -10
  assert await margin.delta() == -10


async def test_buying_back_repays_the_debt_and_flattens_the_position(
  margin_fake: 'FakeMargin', margin: MarginMarket
):
  """A buy-back of the short repays the borrow (nothing is borrowed for it) and the
  position returns to zero."""
  r = await margin.place_order(
    {'type': 'LIMIT', 'qty': Decimal(-10), 'price': Decimal('2.30')}
  )
  assert (await margin.query_order(r.id)) is not None
  assert (await margin.position()).size == -10
  await margin.place_order(
    {'type': 'MARKET', 'qty': Decimal(10), 'price': Decimal('2.31')}
  )
  assert margin_fake.lit.debt == 0 and margin_fake.lit.free == 0
  assert (await margin.position()).size == 0


async def test_a_cancelled_sell_leaves_no_position(
  margin_fake: 'FakeMargin', margin: MarginMarket
):
  """Cancelling returns the locked borrow, which repays itself: still flat."""
  r = await margin.place_order(
    {'type': 'POST_ONLY', 'qty': Decimal(-10), 'price': Decimal('2.32')}
  )
  await margin.cancel_order(r.id)
  assert margin_fake.lit.debt == 0
  assert (await margin.position()).size == 0
  assert not await margin.open_orders()


async def test_a_sell_of_held_coins_borrows_only_what_it_lacks(
  margin_fake: 'FakeMargin', margin: MarginMarket
):
  """Owning 4 LIT, a sell of 10 borrows 6; the position goes from +4 to -6."""
  margin_fake.lit.free = Decimal(4)
  assert (await margin.position()).size == 4
  await margin.place_order(
    {'type': 'LIMIT', 'qty': Decimal(-10), 'price': Decimal('2.30')}
  )
  assert margin_fake.lit.debt == 6
  assert (await margin.position()).size == -6


async def test_spot_reads_what_the_pool_owns_and_margin_the_net(
  margin_fake: 'FakeMargin', margin: MarginMarket
):
  """One pool, read twice without double counting a short: owning 4 LIT and selling
  10 on margin, spot holds 0 and margin is -6; spot alone would have read -6 too."""
  margin_fake.lit.free = Decimal(4)
  assert (await spot_position(margin, 'LIT')).size == 4
  r = await margin.place_order(
    {'type': 'POST_ONLY', 'qty': Decimal(-10), 'price': Decimal('2.32')}
  )
  assert (await spot_position(margin, 'LIT')).size == 10
  assert (await margin.position()).size == 4
  margin_fake.fill(r.id)
  assert (await spot_position(margin, 'LIT')).size == 0
  assert (await margin.position()).size == -6


async def test_every_margin_pair_of_a_coin_reads_the_same_pool_holding(
  margin_fake: 'FakeMargin', margin: MarginMarket
):
  """`LITUSDC` borrows from the same LIT debt as `LITUSDT`: both read it, since a
  strategy on either sizes from it, so consumers count it once per coin."""
  rows = dict(await margin.margin_instruments())
  rows['LITUSDC'] = {**rows[PAIR], 'symbol': 'LITUSDC', 'quoteCoin': 'USDC'}
  margin.cache.margin = rows
  other = await BitgetMarket(account=margin.account, cache=margin.cache).margin_market(
    'margin:LITUSDC'
  )
  r = await margin.place_order(
    {'type': 'LIMIT', 'qty': Decimal(-10), 'price': Decimal('2.30')}
  )
  margin_fake.fill(r.id)
  assert (await margin.position()).size == (await other.position()).size == -10


async def test_replace_cancels_and_places_anew(
  margin_fake: 'FakeMargin', margin: MarginMarket
):
  """No in-place modify on margin: the borrow follows the new order alone."""
  r = await margin.place_order(
    {'type': 'POST_ONLY', 'qty': Decimal(-10), 'price': Decimal('2.32')}
  )
  new = await margin.replace_order(
    r.id, {'type': 'POST_ONLY', 'qty': Decimal(-5), 'price': Decimal('2.33')}
  )
  assert not any(e == 'trade/modify-order' for _, e, _ in margin_fake.requests)
  assert margin_fake.orders[r.id].status == 'cancelled'
  assert margin_fake.lit.debt == 5 and margin_fake.lit.locked == 5
  [listed] = await margin.open_orders()
  assert listed.id == new.id
  assert (await margin.position()).size == 0


async def test_cancel_open_orders_uses_the_margin_category(
  margin_fake: 'FakeMargin', margin: MarginMarket
):
  """Cancel-all is scoped to `MARGIN`; with nothing open it is a no-op."""
  await margin.place_order(
    {'type': 'POST_ONLY', 'qty': Decimal(-10), 'price': Decimal('2.32')}
  )
  await margin.cancel_open_orders()
  [params] = [p for _, e, p in margin_fake.requests if e == 'trade/cancel-symbol-order']
  assert params['category'] == 'MARGIN'
  assert (await margin.cancel_open_orders()) == {'list': []}


async def test_reduce_only_is_refused_before_anything_is_sent(
  margin_fake: 'FakeMargin', margin: MarginMarket
):
  """Bitget takes no reduce-only flag on margin: placing without it would differ."""
  settings: Settings = {'bitget': {'reduce_only': True}}
  with pytest.raises(NotImplementedError):
    await margin.place_order(
      {'type': 'LIMIT', 'qty': Decimal(10), 'price': Decimal('2.30')},
      settings=settings,
    )
  assert not bodies(margin_fake)


async def test_collateral_is_the_unified_pool_shared_with_the_perpetuals(
  margin: MarginMarket,
):
  """One pool, one ID: the margin pair names `<account>:usdt`, and resolving either
  `margin` or `usdt` gives the same figures, so USDT is never counted twice."""
  assert await margin.collateral_id() == 'bg:usdt'
  pool = await margin.collateral()
  assert pool.equity == 1010 and pool.free_collateral == 800
  venue = BitgetMarket(account=margin.account, cache=margin.cache)
  via_margin = await venue.collateral('margin')
  via_usdt = await venue.collateral('usdt')
  assert via_margin == via_usdt
  assert via_margin.free_collateral == 800


async def test_leverage_is_the_listed_cross_setting_else_one(
  margin_fake: 'FakeMargin', margin: MarginMarket
):
  """An unlisted pair answers 1; a listed `MARGIN` cross row is read."""
  assert await margin.leverage() == 1
  margin_fake.symbol_configs.append(
    {'category': 'MARGIN', 'symbol': PAIR, 'marginMode': 'crossed', 'leverage': '3'}
  )
  assert await margin.leverage() == 3


async def test_a_classic_account_is_refused(classic_margin: MarginMarket):
  """The margin surface reads the unified pool only."""
  market = classic_margin
  assert isinstance(market, MarginMarket)
  with pytest.raises(NotImplementedError):
    await market.position()
  with pytest.raises(NotImplementedError):
    await market.place_order(
      {'type': 'LIMIT', 'qty': Decimal(-1), 'price': Decimal('2.3')}
    )


def fill_push(category: str, symbol: str, qty: str) -> dict[str, Any]:
  """One UTA `fill` channel row."""
  return {
    'category': category,
    'symbol': symbol,
    'orderId': '1',
    'clientOid': '',
    'execId': f'{category}-{symbol}',
    'execPrice': Decimal('2.32'),
    'execQty': Decimal(qty),
    'side': 'sell',
    'tradeScope': 'maker',
    'execTime': datetime(2026, 11, 21, tzinfo=timezone.utc),
    'feeDetail': [{'feeCoin': 'USDT', 'fee': Decimal('0.0232')}],
  }


async def test_the_fill_stream_keeps_this_pairs_margin_fills_only(
  margin: MarginMarket,
):
  """The account-wide channel is narrowed to category `margin` and this symbol: the
  spot fills of the same pair are not this market's."""
  pushes = [
    fill_push('spot', PAIR, '1'),
    fill_push('margin', 'BTCUSDT', '2'),
    fill_push('usdt-futures', PAIR, '3'),
    fill_push('margin', PAIR, '10'),
  ]

  async def subscribe():
    async def rows() -> AsyncIterator[Any]:
      for p in pushes:
        yield p

    async def unsubscribe():
      pass

    return rows(), unsubscribe

  margin.cache.uta_fills = Subscription.of(subscribe)  # type: ignore
  async with margin.trades_stream() as trades:
    async for trade in trades:
      assert trade.qty == -10 and trade.maker
      assert trade.fee is not None and trade.fee.asset == 'USDT'
      break


def test_exposure_adds_back_what_orders_lock():
  """The live reading of a resting borrowed sell nets to zero."""
  row: AccountAsset = {
    'coin': 'LIT',
    'equity': Decimal(-10),
    'usdValue': Decimal(-23),
    'balance': Decimal(-10),
    'available': Decimal(0),
    'debt': Decimal(10),
    'locked': Decimal(10),
    'bonus': Decimal(0),
  }
  assert margin_exposure(row) == 0
  assert margin_exposure(None) == 0


def test_spot_holds_what_is_owned_never_what_is_owed():
  """The live 548 LIT short (2026-11-21) holds nothing on spot; no row holds nothing."""
  row: AccountAsset = {
    'coin': 'LIT',
    'equity': Decimal('-548.26695058'),
    'usdValue': Decimal(-1200),
    'balance': Decimal('-548.26695058'),
    'available': Decimal('-548.26695058'),
    'debt': Decimal('548.26695058'),
    'locked': Decimal(0),
    'bonus': Decimal(0),
  }
  assert spot_holding(row) == 0
  assert margin_exposure(row) == Decimal('-548.26695058')
  assert spot_holding(None) == 0
