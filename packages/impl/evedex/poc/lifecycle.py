"""EVEDEX mainnet trading lifecycle through the SDK implementation, for the owner to run.

Exercises every trading method of `EvedexPerpMarket` on XRPUSD at about 6.5 USD per
order: resting orders priced 3-4% under the best bid (inside the mark-price band, far
from filling), a post-only, a probe of the band itself, an immediate-or-cancel that
cannot fill, one small market round trip (buy, then sell), `set_leverage` and its
restore. A `finally` block cancels every XRPUSD order, closes any XRPUSD position and
restores the leverage, then prints a `FINAL` state line. Each step prints `ok`, or what
the venue answered, and the run carries on.

Credentials come from the environment (`EVEDEX_PRIVATE_KEY`, `EVEDEX_API_KEY`, via
`.env`). Costs: two taker fills of ~6.5 USD (~0.006 USDT in fees) plus the spread.

Usage, from the repository root:
  .venv/bin/python packages/impl/evedex/poc/lifecycle.py
"""

from datetime import datetime, timedelta, timezone
from decimal import ROUND_CEILING, ROUND_DOWN, Decimal
from typing_extensions import Any, Awaitable, Callable, Literal, TypeVar
import asyncio
import os
import traceback

from dotenv import load_dotenv

from tribulnation.evedex import EvedexMarket
from tribulnation.evedex.market.markets import EvedexPerpMarket
from tribulnation.sdk.core import OrderNotFound, OrderRejected
from tribulnation.sdk.market import Order, Trade

T = TypeVar('T')

INSTRUMENT = 'XRPUSD'
NOTIONAL = Decimal('6.5')
"""USD per order: above the 5 USD minimum."""
LEVERAGE = Decimal(2)
"""The leverage set for the run; the original setting is restored at the end."""
PAUSE = 1.5
"""Seconds between steps: placement is asynchronous, and heavy requests are limited to
30 a minute."""

results: list[str] = []


def note(step: str, outcome: str):
  """Print and keep one step's outcome."""
  line = f'{step}: {outcome}'
  results.append(line)
  print(line, flush=True)


async def step(name: str, fn: Callable[[], Awaitable[T]]) -> T | None:
  """Run one step, printing its outcome; a failure is printed and the run goes on."""
  try:
    value = await fn()
  except Exception as exc:
    note(name, f'{type(exc).__name__}: {exc!r}'[:400])
    return None
  note(name, f'ok {value!r}'[:400])
  await asyncio.sleep(PAUSE)
  return value


def on_tick(price: Decimal, tick: Decimal) -> Decimal:
  """`price` down to the tick."""
  return (price / tick).to_integral_value(rounding=ROUND_DOWN) * tick


async def main():
  """Run the lifecycle, then clean up whatever is left."""
  load_dotenv()
  venue = EvedexMarket.new(
    private_key=os.environ['EVEDEX_PRIVATE_KEY'],
    api_key=os.environ.get('EVEDEX_API_KEY'),
  )
  async with venue:
    perp = await venue.perp_exchange('perp')
    market: EvedexPerpMarket = await perp.market(INSTRUMENT)
    client = market.shared.client
    rules = await market.rules()
    tick, step_size = rules.tick_size, rules.step_size
    original_leverage = await market.leverage()
    start = datetime.now(timezone.utc) - timedelta(seconds=5)
    note(
      'start',
      f'leverage={original_leverage} position={await market.perp_position()} '
      f'open={await market.open_orders()} collateral={await market.perp_collateral()}',
    )

    async def prices() -> tuple[Decimal, Decimal, Decimal]:
      """Best bid, best ask and mark."""
      book = await market.depth(levels=1)
      mark = (await client.exchange.market.instrument(INSTRUMENT))['markPrice']
      return book.bids[0].price, book.asks[0].price, mark

    bid, ask, mark = await prices()
    qty = ((NOTIONAL / ask) / step_size).to_integral_value(
      rounding=ROUND_CEILING
    ) * step_size
    note(
      'setup', f'bid={bid} ask={ask} mark={mark} qty={qty} tick={tick} step={step_size}'
    )

    def limit(
      kind: Literal['MARKET', 'LIMIT', 'POST_ONLY'],
      side: int,
      price: Decimal,
      client_id: str | None = None,
    ) -> Order:
      """An SDK order of `qty`, signed by `side`."""
      order: Order = {'type': kind, 'qty': qty * side, 'price': on_tick(price, tick)}
      if client_id is not None:
        order['client_order_id'] = client_id
      return order

    fills: list[Trade] = []

    async def collect():
      """Record the account's XRPUSD fills from the stream."""
      async with market.trades_stream() as stream:
        async for trade in stream:
          fills.append(trade)
          note('trades_stream', f'fill {trade!r}'[:400])

    listener = asyncio.create_task(collect())
    try:
      # 1. Leverage: set for the run.
      await step('set_leverage', lambda: market.set_leverage(LEVERAGE))
      await step('leverage after set', market.leverage)

      # 2. A resting limit with a client order id: place, list, query, replace, cancel.
      cid = market.random_client_order_id()
      placed = await step(
        'place LIMIT (client id)',
        lambda: market.place_order(limit('LIMIT', 1, bid * Decimal('0.97'), cid)),
      )
      if placed is not None:
        note('client id is order id', str(placed.id == cid))
        await asyncio.sleep(PAUSE)
        await step('open_orders', market.open_orders)
        await step('query_order', lambda: market.query_order(placed.id))
        replaced = await step(
          'replace_order',
          lambda: market.replace_order(
            placed.id, limit('LIMIT', 1, bid * Decimal('0.96'))
          ),
        )
        await step('query_order (replaced)', lambda: market.query_order(placed.id))
        if replaced is not None:
          await step('cancel_order', lambda: market.cancel_order(replaced.id))
          await step('query_order (cancelled)', lambda: market.query_order(replaced.id))
          try:
            await market.cancel_order(replaced.id)
            note(
              'cancel_order again', 'no error (venue does not refuse a second cancel)'
            )
          except OrderNotFound as exc:
            note('cancel_order again', f'OrderNotFound {exc!r}'[:300])
          except Exception as exc:
            note('cancel_order again', f'{type(exc).__name__}: {exc!r}'[:300])
      await step(
        'cancel_order unknown',
        lambda: market.cancel_order('00483:00000000000000000000000000'),
      )

      # 3. Post-only, resting far from the ask.
      post = await step(
        'place POST_ONLY',
        lambda: market.place_order(limit('POST_ONLY', 1, bid * Decimal('0.97'))),
      )
      if post is not None:
        await step('query_order (post-only)', lambda: market.query_order(post.id))
        await step('cancel_order (post-only)', lambda: market.cancel_order(post.id))

      # 4. The mark-price band: a buy 7% under the mark (outside ±5%, inside ±30%).
      wide = await step(
        'place LIMIT 7% under mark',
        lambda: market.place_order(limit('LIMIT', 1, mark * Decimal('0.93'))),
      )
      if wide is not None:
        await step('query_order (7% under)', lambda: market.query_order(wide.id))
        await step('cancel_order (7% under)', lambda: market.cancel_order(wide.id))

      # 5. Immediate-or-cancel that cannot fill: it must not rest.
      ioc = await step(
        'place MARKET (IOC limit 3% under bid)',
        lambda: market.place_order(limit('MARKET', 1, bid * Decimal('0.97'))),
      )
      if ioc is not None:
        await asyncio.sleep(PAUSE)
        state = await step('query_order (IOC)', lambda: market.query_order(ioc.id))
        if state is not None and state.active:
          note(
            'IOC', 'still resting: the venue ignored timeInForce IOC on a limit order'
          )
          await step('cancel_order (IOC)', lambda: market.cancel_order(ioc.id))

      # 6. cancel_orders and cancel_open_orders, two resting orders each.
      a = await step(
        'place LIMIT a',
        lambda: market.place_order(limit('LIMIT', 1, bid * Decimal('0.97'))),
      )
      b = await step(
        'place LIMIT b',
        lambda: market.place_order(limit('LIMIT', 1, bid * Decimal('0.965'))),
      )
      ids = [o.id for o in (a, b) if o is not None]
      await asyncio.sleep(PAUSE)
      await step('cancel_orders', lambda: market.cancel_orders(ids))
      await step('open_orders after cancel_orders', market.open_orders)
      await step(
        'place LIMIT c',
        lambda: market.place_order(limit('LIMIT', 1, bid * Decimal('0.97'))),
      )
      await step(
        'place LIMIT d',
        lambda: market.place_order(limit('LIMIT', 1, bid * Decimal('0.965'))),
      )
      await asyncio.sleep(PAUSE)
      await step('cancel_open_orders', market.cancel_open_orders)
      await step('open_orders after cancel_open_orders', market.open_orders)

      # 7. A market round trip: an IOC buy through the ask, then an IOC sell through the bid.
      bid, ask, mark = await prices()
      buy = await step(
        'place MARKET buy (IOC 1% over ask)',
        lambda: market.place_order(limit('MARKET', 1, ask * Decimal('1.01'))),
      )
      await asyncio.sleep(3)
      if buy is not None:
        await step('query_order (buy)', lambda: market.query_order(buy.id))
      await step('perp_position (long)', market.perp_position)
      await step('perp_collateral (long)', market.perp_collateral)
      await step('remaining_position_limit (long)', market.remaining_position_limit)
      position = await market.perp_position()
      if position.size > 0:
        bid, ask, mark = await prices()
        sell: Order = {
          'type': 'MARKET',
          'qty': -position.size,
          'price': on_tick(bid * Decimal('0.99'), tick),
        }
        sold = await step(
          'place MARKET sell (IOC 1% under bid)', lambda: market.place_order(sell)
        )
        await asyncio.sleep(3)
        if sold is not None:
          await step('query_order (sell)', lambda: market.query_order(sold.id))
      await step('perp_position (after round trip)', market.perp_position)
      await asyncio.sleep(3)
      history = [
        t
        async for page in market.trades_history(start, datetime.now(timezone.utc))
        for t in page
      ]
      note('trades_history', f'{len(history)} fills: {history!r}'[:1200])
      note('trades_stream total', f'{len(fills)} fills')
    except Exception:
      traceback.print_exc()
    finally:
      listener.cancel()
      await asyncio.gather(listener, return_exceptions=True)
      await cleanup(market, original_leverage)


async def cleanup(market: EvedexPerpMarket, leverage: Decimal):
  """Cancel every XRPUSD order, close any XRPUSD position, restore the leverage, and
  print the final state."""
  client = market.shared.client
  try:
    await client.exchange.orders.cancel_by_instrument(INSTRUMENT)
  except Exception as exc:
    print(f'cleanup cancel_by_instrument: {exc!r}', flush=True)
  await asyncio.sleep(2)
  try:
    rows = (await client.exchange.positions.list())['list']
    for p in rows:
      if p['instrument'] == INSTRUMENT and p['quantity'] != 0:
        await client.exchange.positions.close(
          instrument=INSTRUMENT, quantity=p['quantity'], leverage=p['leverage']
        )
        print(f'cleanup closed {p["side"]} {p["quantity"]}', flush=True)
        await asyncio.sleep(3)
  except Exception as exc:
    print(f'cleanup close: {exc!r}', flush=True)
  try:
    if await market.leverage() != leverage:
      await market.set_leverage(leverage)
  except Exception as exc:
    print(f'cleanup set_leverage: {exc!r}', flush=True)
  opened: Any = await client.exchange.orders.opened()
  positions = [
    p for p in (await client.exchange.positions.list())['list'] if p['quantity'] != 0
  ]
  balance = await client.exchange.account.available_balance()
  print(
    f'FINAL open orders={len(opened)} open positions={len(positions)} '
    f'leverage={await market.leverage()} (was {leverage}) '
    f'availableBalance={balance["availableBalance"]} funding={balance["funding"]["balance"]}',
    flush=True,
  )


if __name__ == '__main__':
  asyncio.run(main())
