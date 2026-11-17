# %% [markdown]
# # nado `report` PoC
#
# Maps `typed_nado` onto the SDK `report` surface: a snapshot of every cross subaccount of one wallet, read with its address (Nado's reads are public). The rules are in `.agents/skills/sdk-poc/SKILL.md`.

# %%
import os
from decimal import Decimal

from dotenv import load_dotenv
from typed_nado import Nado

from tribulnation.sdk.reporting import Position, Snapshot, SubaccountSnapshot

load_dotenv()

client = Nado.new(public=True)
OWNER = os.environ['NADO_ADDRESS']
X18 = Decimal(10) ** 18


def x18(v: int) -> Decimal:
  """An x18 integer as a decimal."""
  return Decimal(int(v)) / X18


# %% [markdown]
# ## Surface

# %%
from sdk_dev.surface import surface

print(surface('typed_nado', 'Nado', grep=r'subaccount|positions|symbols'))

# %% [markdown]
# ## `snapshot`
#
# `archive.subaccounts` lists the wallet's subaccounts; each cross one's `subaccount_info` gives its spot balances (negative when borrowed) and perpetual positions. A position's value is `amount * price + v_quote_balance`: `amount * (price - entry)` is its unrealized PnL, so `v_quote_balance + amount * entry` (funding and PnL not yet settled into USDT0) is USDT0 cash. The entry is the archive's open position window.


# %%
async def snapshot() -> Snapshot:
  """Every cross subaccount."""
  symbols = (await client.gateway.symbols())['symbols']
  names = {s['product_id']: n for n, s in symbols.items()}
  names[0] = 'USDT0'
  rows = (await client.archive.subaccounts(address=OWNER))['subaccounts']
  subs: list[SubaccountSnapshot] = []
  for row in rows:
    if row['isolated']:
      continue
    info = await client.gateway.subaccount_info(subaccount=row['subaccount'])
    balances = {
      names[b['product_id']]: x18(b['balance']['amount'])
      for b in info['spot_balances']
      if int(b['balance']['amount'])
    }
    positions: dict[str, Position] = {}
    perps = [b for b in info['perp_balances'] if int(b['balance']['amount'])]
    if perps:
      windows = await client.archive.positions(
        row['subaccount'], isolated=False, open=True
      )
      entries = {
        p['product_id']: x18(p['average_entry_price']) for p in windows['positions']
      }
      for b in perps:
        amount, entry = x18(b['balance']['amount']), entries[b['product_id']]
        positions[names[b['product_id']]] = Position(size=amount, avg_price=entry)
        balances['USDT0'] = balances.get('USDT0', Decimal(0)) + (
          x18(b['balance']['v_quote_balance']) + amount * entry
        )
    subs.append(
      SubaccountSnapshot(
        subaccount=row['subaccount_name'], balances=balances, positions=positions
      )
    )
  return Snapshot(subaccounts=subs)


await snapshot()

# %% [markdown]
# ## Coverage
#
# | method | status | note |
# |---|---|---|
# | `snapshot` | verified | one `default` subaccount holding USDT0; no position, so the unsettled-cash path is covered by unit tests only |
# | `history` | not supported | the Report history surface is being retired |

# %% [markdown]
# ## Catalogue

# %%
from sdk_dev.catalogue import Ids, gap, load_catalogue

snap = await snapshot()
ids = Ids(assets={a for s in snap.subaccounts for a in s.balances})
gap('nado', ids, load_catalogue())
