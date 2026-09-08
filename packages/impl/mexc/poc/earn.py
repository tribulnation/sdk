# %%
from functools import cached_property

from dotenv import load_dotenv

from typed_mexc import MEXC

load_dotenv()

client = await MEXC.new(public=True).__aenter__()


# %% [markdown]
# ## `Instruments`
#
# `typed_mexc` has no earn/savings/staking surface at all: no `earn`, `financial`, or
# `saving` module anywhere in the package (confirmed by grepping the full package tree),
# and neither `client.spot` nor `client.futures` exposes a namespace for it. Production
# `tribulnation.mexc.earn.Instruments` doesn't use `typed_mexc` for this reason -- it
# reaches MEXC's undocumented internal website API directly with a raw
# `httpx.AsyncClient` call to
# `https://www.mexc.com/api/financialactivity/financial/products/list/V2`, which isn't
# part of `typed_mexc` (or any documented MEXC REST/WebSocket API) at all.
#
# Each product (`spot`, `futures`) splits into an `http` and a `streams` transport, and
# each of those exposes its endpoint groups as `cached_property` attributes. The cell
# below lists all four namespaces' groups, confirming there's nothing earn-shaped to
# hand-map.

# %%
def groups(namespace: object) -> list[str]:
  """Endpoint groups a `typed_mexc` namespace exposes, as its `cached_property` names."""
  return sorted(
    name
    for name, value in vars(type(namespace)).items()
    if isinstance(value, cached_property)
  )


{
  'spot.http': groups(client.spot.http),
  'spot.streams': groups(client.spot.streams),
  'futures.http': groups(client.futures.http),
  'futures.streams': groups(client.futures.streams),
}

# %% [markdown]
# ### Coverage assessment: `Earn`
#
# **Not applicable.** `instruments()` is the only method in the abstract
# `Earn`/`Instruments` interface, and there is no `typed_mexc` surface to hand-map it
# from -- the groups listed above are every endpoint group `typed_mexc.spot`/
# `typed_mexc.futures` expose, and none of them is earn/savings/staking related. This
# isn't a permissions or credentials gap (no client above even needs an API key): the
# endpoint simply isn't part of the package's generated surface, unlike production's
# `tribulnation.mexc.earn`, which bypasses `typed_mexc` entirely and calls MEXC's internal
# website API directly (see above). Since this notebook's brief is to explore
# `typed_mexc` specifically, `instruments()` is marked not-applicable rather than
# reproduced via that out-of-band call.
