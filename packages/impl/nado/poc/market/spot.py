# %% [markdown]
# # nado `market` PoC: spot
#
# Maps `typed_nado` onto the SDK `market` surface's spot exchange, one method per cell, each executed live on mainnet. Spot products trade against USDT0 (product 0) on the same unified subaccount as the perpetuals, so the book, candle, order and fill paths are the perpetual PoC's (`perp.py`); this script covers what differs. The rules are in `.agents/skills/sdk-poc/SKILL.md`.

# %%
import os
from datetime import datetime, timezone
from decimal import Decimal

from dotenv import load_dotenv
from typed_nado import Nado
from typed_nado.core.auth import subaccount_bytes32

from tribulnation.sdk.market import (
  Balance,
  Book,
  Fees,
  SpotBalances,
  SpotCollateralIds,
  SpotRules,
  Ticker,
)

load_dotenv()

client = Nado.new(public=True)
SENDER = subaccount_bytes32(os.environ['NADO_ADDRESS'], 'default')
X18 = Decimal(10) ** 18


def x18(v: int) -> Decimal:
  """An x18 integer as a decimal."""
  return Decimal(int(v)) / X18


MARKETS = ['KBTC', 'WETH']

# %% [markdown]
# ## Surface

# %%
from sdk_dev.surface import surface

print(
  surface(
    'typed_nado',
    'Nado',
    grep=r'symbols|liquidity|tickers|market_prices|subaccount_info|max_withdrawable|assets|pairs',
  )
)

# %% [markdown]
# ## `markets`

# %%
symbols = (await client.gateway.symbols())['symbols']
PRODUCT = {name: s['product_id'] for name, s in symbols.items()}


async def markets() -> list[str]:
  """Spot symbols; product 0 (USDT0, the quote) is not a market."""
  return [name for name, s in symbols.items() if s['type'] == 'spot']


await markets()

# %% [markdown]
# ## `depth`


# %%
async def depth(market_id: str) -> Book:
  """The aggregated book, 3 levels."""
  raw = await client.gateway.market_liquidity(product_id=PRODUCT[market_id], depth=3)
  return Book(
    bids=[Book.Entry(x18(p), x18(q)) for p, q in raw['bids']],
    asks=[Book.Entry(x18(p), x18(q)) for p, q in raw['asks']],
    time=raw['timestamp'],
  )


{m: await depth(m) for m in MARKETS}

# %% [markdown]
# ## `tickers`


# %%
async def tickers() -> dict[str, Ticker]:
  """Last price and volumes (floats) with best bid/ask."""
  rows = await client.archive_v2.tickers('spot')
  ids = [PRODUCT[m] for m in await markets()]
  best = {
    p['product_id']: p
    for p in (await client.gateway.market_prices(ids))['market_prices']
  }
  return {
    t['base_currency']: Ticker(
      last=Decimal(repr(t['last_price'])),
      bid=x18(best[t['product_id']]['bid_x18']) if t['product_id'] in best else None,
      ask=x18(best[t['product_id']]['ask_x18']) if t['product_id'] in best else None,
      base_volume_24h=Decimal(repr(t['base_volume'])),
      quote_volume_24h=Decimal(repr(t['quote_volume'])),
    )
    for t in rows.values()
  }


await tickers()

# %% [markdown]
# ## `rules` and `fees`


# %%
async def rules(market_id: str) -> SpotRules:
  """The pair is the symbol against USDT0; fees are charged in USDT0."""
  s = symbols[market_id]
  return SpotRules(
    base=market_id,
    quote='USDT0',
    fee_asset='USDT0',
    tick_size=x18(s['price_increment_x18']),
    step_size=x18(s['size_increment']),
    min_value=x18(s['min_size']),
    fees=Fees.symmetric(
      maker=x18(s['maker_fee_rate_x18']), taker=x18(s['taker_fee_rate_x18'])
    ),
    api=s['trading_status'] == 'live',
  )


{m: await rules(m) for m in MARKETS}

# %% [markdown]
# ## `balances` and `collateral_ids`
#
# `subaccount_info`'s spot balances (signed: negative is a borrow). Resting orders hold nothing (a resting post-only buy left every health unchanged), so `free` is the balance; USDT0's is capped at the initial health, since it also margins every position. `max_withdrawable` is not a free figure: it nets the 1 USDT0 withdrawal fee, and borrows (a KBTC withdrawal was offered on a wallet holding none).


# %%
async def balances(market_id: str) -> SpotBalances:
  """The base and USDT0 balances."""
  info = await client.gateway.subaccount_info(subaccount=SENDER)
  amounts = {
    b['product_id']: x18(b['balance']['amount']) for b in info['spot_balances']
  }
  initial = x18(info['healths'][0]['health'])
  base = amounts.get(PRODUCT[market_id], Decimal(0))
  quote = amounts.get(0, Decimal(0))
  return SpotBalances(
    base=Balance(total=base, free=max(base, Decimal(0))),
    quote=Balance(total=quote, free=max(min(quote, initial), Decimal(0))),
  )


def collateral_ids(market_id: str) -> SpotCollateralIds:
  """`<account>:spot:<asset>`."""
  return SpotCollateralIds(base=f'nado:spot:{market_id}', quote='nado:spot:USDT0')


{m: (await balances(m), collateral_ids(m)) for m in MARKETS}

# %% [markdown]
# ## Orders
#
# The perpetual paths, plus `spot_leverage`: the venue's default lets a spot order borrow, so the SDK sends `False` unless asked (a $100 buy with $10 was then refused, `2017`).

# %%
# not executed: changes the account
signer = Nado.new()
await signer.gateway.place_order(
  product_id=PRODUCT['KBTC'],
  order={
    'priceX18': 32000 * 10**18,
    'amount': 3_150_000_000_000_000,
    'expiration': datetime(2100, 1, 1, tzinfo=timezone.utc),
    'appendix': 1537,
  },
  spot_leverage=False,
)

# %% [markdown]
# ## Coverage
#
# | method | status | note |
# |---|---|---|
# | `markets` | verified | 14 spot products |
# | `depth` | verified | |
# | `depth_stream` | verified | the perpetual path, run on KBTC through the implementation |
# | `tickers` | verified | floats on the wire: `Ticker.last_price` issue |
# | `rules` | verified | |
# | `fees` | verified | |
# | `candles` | verified | the perpetual path, run on KBTC through the implementation |
# | `balances` | verified | USDT0 held; KBTC zero |
# | `collateral_ids` | verified | |
# | `query_order` | verified | through the implementation, with a resting KBTC post-only buy |
# | `open_orders` | verified | through the implementation |
# | `trades_history` | empty | the account has never filled |
# | `trades_stream` | empty | no fill |
# | `place_order` | verified | POST_ONLY rested with `spot_leverage` and was cancelled; without it refused (`2017`); a fill not attempted |
# | `place_orders` | verified | the perpetual path |
# | `cancel_order` | verified | |
# | `cancel_orders` | verified | the perpetual path |
# | `replace_order` | verified | the perpetual path |
# | `replace_orders` | verified | the SDK default |
# | `cancel_open_orders` | verified | |

# %% [markdown]
# ## Catalogue

# %%
from sdk_dev.catalogue import Ids, gap, load_catalogue

listed = await markets()
ids = Ids(spot_markets={f'spot:{m}' for m in listed}, assets=set(listed) | {'USDT0'})
gap('nado', ids, load_catalogue())
