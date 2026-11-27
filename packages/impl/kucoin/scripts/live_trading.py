"""Live KuCoin trading check: read the account, then rest and cancel one tiny post-only order.

Not part of the test suite and never run in CI: it talks to mainnet with real
credentials. Run it by hand, from the repository root:

  KUCOIN_API_KEY=... KUCOIN_API_SECRET=... KUCOIN_API_PASSPHRASE=... \\
    python packages/impl/kucoin/scripts/live_trading.py --exchange both

`--mode` selects the account mode the SDK uses: `auto` (default) detects it with
`GET /api/ua/v2/account/mode`; `classic` or `unified` forces one and stops before
anything else when the account is in the other mode. A Unified Trading Account (UTA)
routes every read, order and fill below through the UTA API and private WebSocket:

  python packages/impl/kucoin/scripts/live_trading.py --mode unified --exchange both
  python packages/impl/kucoin/scripts/live_trading.py --mode unified --place --cross
  python packages/impl/kucoin/scripts/live_trading.py --mode unified --fill

Without `--place` it only reads (rules, fees, balances, position, collateral, leverage,
open orders, recent fills). With `--place` it, per market:

1. subscribes to the fill stream;
2. places one minimum-size POST_ONLY buy at `--depth` (default 10%) below the best bid,
   where it cannot fill;
3. checks `query_order` and `open_orders` see it resting with the quantity sent;
4. cancels it, checks `query_order` reports it inactive and that cancelling again raises
   `OrderNotFound`;
5. with `--cross`, places a minimum-size POST_ONLY buy at the best ask, which KuCoin must
   not fill: spot must raise `OrderRejected`; on futures the order must end cancelled
   with nothing filled.

With `--fill`, per market: one minimum-size MARKET buy (an IOC limit a little above the
best ask), its fill seen on `trades_stream` and in `trades_history`, then one
minimum-size MARKET sell closing it again. It pays the taker fee twice and the spread
once: roughly 0.2-0.3 USD per market at the minimum sizes.

Orders carry a client order ID and nothing is left resting: every placed order is
cancelled in a `finally`. The minimum futures order is one contract (0.001 BTC on
XBTUSDTM), so the futures account needs margin for about that notional over the
symbol's leverage; spot needs the pair's minimum funds in USDT in the trade account.
"""

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
import sys

from tribulnation.kucoin import KucoinMarket
from tribulnation.sdk import OrderNotFound, OrderRejected
from tribulnation.sdk.market import Market, OrderResponse, is_perp, is_spot


def check(condition: bool, message: str):
  """Print a pass, or fail the run."""
  if condition:
    print(f'  ok   {message}')
  else:
    raise SystemExit(f'  FAIL {message}')


async def read(market: Market):
  """Every account read of the market, printed."""
  print(f'\n== {market.id} (read only)')
  rules = await market.rules()
  print(
    f'  rules: tick {rules.tick_size} step {rules.step_size} min {rules.fixed_min_qty}'
  )
  fees = await market.fees()
  print(
    f'  fees: maker {fees.maker_buy}/{fees.maker_sell} taker {fees.taker_buy}/{fees.taker_sell}'
  )
  print(f'  open orders: {len(await market.open_orders())}')
  end = datetime.now(timezone.utc)
  fills = [
    t
    async for page in market.trades_history(end - timedelta(days=3), end)
    for t in page
  ]
  print(f'  fills in 3 days: {len(fills)}')
  if is_spot(market):
    balances = await market.balances()
    print(f'  balances: base {balances.base} quote {balances.quote}')
  if is_perp(market):
    print(f'  position: {await market.perp_position()}')
    print(f'  collateral: {await market.perp_collateral()}')
    print(f'  leverage: {await market.leverage()}')
    print(f'  available notional: {await market.available_notional()}')


async def trade(market: Market, *, depth: Decimal, cross: bool):
  """Rest one tiny post-only buy far from the book, then cancel it."""
  print(f'\n== {market.id} (placing)')
  rules = await market.rules()
  book = await market.depth(levels=1)
  check(bool(book.bids and book.asks), 'book has both sides')
  price = rules.trunc_price(book.bids[0].price * (1 - depth))
  qty = rules.min_qty(price)
  placed: list[OrderResponse] = []
  async with market.trades_stream():
    try:
      client_id = market.random_client_order_id()
      response = await market.place_order(
        {'type': 'POST_ONLY', 'qty': qty, 'price': price, 'client_order_id': client_id}
      )
      placed.append(response)
      print(f'  placed {response.id}: buy {qty} @ {price}')
      await asyncio.sleep(1)
      state = await market.query_order(response.id)
      check(state is not None and state.active, 'query_order sees it resting')
      check(
        state is not None and state.qty == qty, 'resting quantity is the quantity sent'
      )
      ids = [o.id for o in await market.open_orders()]
      check(response.id in ids, 'open_orders lists it')
      await market.cancel_order(response.id)
      await asyncio.sleep(1)
      state = await market.query_order(response.id)
      check(state is None or not state.active, 'cancelled order is inactive')
      try:
        await market.cancel_order(response.id)
        check(False, 'second cancel raises OrderNotFound')
      except OrderNotFound:
        check(True, 'second cancel raises OrderNotFound')
      if cross:
        ask = book.asks[0].price
        try:
          crossing = await market.place_order(
            {'type': 'POST_ONLY', 'qty': rules.min_qty(ask), 'price': ask}
          )
          placed.append(crossing)
          await asyncio.sleep(1)
          state = await market.query_order(crossing.id)
          check(
            state is not None and not state.active and state.filled_qty == 0,
            'crossing post-only ended cancelled with nothing filled',
          )
        except OrderRejected as exc:
          check(True, f'crossing post-only refused: {exc}')
    finally:
      for response in placed:
        try:
          await market.cancel_order(response.id)
        except OrderNotFound:
          pass


async def take(market: Market):
  """Buy the minimum at the ask with a MARKET order, then sell it back the same way."""
  print(f'\n== {market.id} (tiny fill)')
  rules = await market.rules()
  book = await market.depth(levels=1)
  check(bool(book.bids and book.asks), 'book has both sides')
  ask, bid = book.asks[0].price, book.bids[0].price
  qty = rules.min_qty(ask)
  start = datetime.now(timezone.utc) - timedelta(seconds=5)
  async with market.trades_stream() as fills:
    bought = await market.place_order(
      {
        'type': 'MARKET',
        'qty': qty,
        'price': rules.trunc_price(ask * Decimal('1.002')),
        'client_order_id': market.random_client_order_id(),
      }
    )
    print(f'  bought {bought.id}: {qty} at most {ask * Decimal("1.002")}')
    fill = await asyncio.wait_for(anext(aiter(fills)), 10)
    check(
      fill.order_id == bought.id and fill.qty > 0, 'trades_stream sees the buy fill'
    )
    print(f'  fill: {fill.qty} @ {fill.price}, maker {fill.maker}, fee {fill.fee}')
    sold = await market.place_order(
      {
        'type': 'MARKET',
        'qty': -fill.qty if is_perp(market) else -qty,
        'price': rules.trunc_price(bid * Decimal('0.998')),
      }
    )
    print(f'  sold {sold.id}')
    await asyncio.wait_for(anext(aiter(fills)), 10)
  await asyncio.sleep(2)
  history = [
    t
    async for page in market.trades_history(start, datetime.now(timezone.utc))
    for t in page
  ]
  ids = {t.order_id for t in history}
  check(bought.id in ids and sold.id in ids, 'trades_history lists both fills')
  if is_perp(market):
    check((await market.perp_position()).size == 0, 'position is flat again')


async def main():
  """Run the selected checks."""
  parser = argparse.ArgumentParser(description='Live KuCoin trading check.')
  parser.add_argument('--exchange', choices=['spot', 'perp', 'both'], default='both')
  parser.add_argument('--spot-market', default='BTC-USDT')
  parser.add_argument('--perp-market', default='XBTUSDTM')
  parser.add_argument('--place', action='store_true', help='place and cancel orders')
  parser.add_argument(
    '--cross', action='store_true', help='also try a crossing post-only'
  )
  parser.add_argument('--depth', type=Decimal, default=Decimal('0.1'))
  parser.add_argument(
    '--fill', action='store_true', help='buy and sell back the minimum (pays fees)'
  )
  parser.add_argument('--mode', choices=['auto', 'classic', 'unified'], default='auto')
  args = parser.parse_args()
  names = ('KUCOIN_API_KEY', 'KUCOIN_API_SECRET', 'KUCOIN_API_PASSPHRASE')
  if missing := [n for n in names if not os.environ.get(n)]:
    sys.exit(f'Set {", ".join(missing)} to run the live check.')
  ids: list[str] = []
  if args.exchange in ('spot', 'both'):
    ids.append(f'spot:{args.spot_market}')
  if args.exchange in ('perp', 'both'):
    ids.append(f'perp:{args.perp_market}')
  async with KucoinMarket.new(public=False) as venue:
    detected = await venue.shared.account_mode()
    print(f'account mode: {detected}')
    if args.mode != 'auto' and args.mode != detected:
      sys.exit(f'The account is {detected}, not {args.mode}: nothing was sent.')
    if detected == 'unified':
      print(
        f'unified pool: {await (await venue.perp_exchange("perp")).perp_collateral()}'
      )
    for id in ids:
      market = await venue.market(id)
      await read(market)
      if args.place:
        await trade(market, depth=args.depth, cross=args.cross)
      if args.fill:
        await take(market)
  print('\nall checks passed')


if __name__ == '__main__':
  asyncio.run(main())
