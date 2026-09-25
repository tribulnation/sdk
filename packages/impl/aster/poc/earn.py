# %% [markdown]
# # aster `earn` PoC
#
# Maps `typed_aster` onto the SDK `earn` surface, one method per cell; Coverage records what ran on testnet and what remains unmapped. The rules, and how a typed-client issue is reported in `typed-client-issues.md`, are in `.agents/skills/sdk-poc/SKILL.md`.

# %%
from typing_extensions import Collection, Sequence
from tribulnation.sdk.earn.instruments import Instrument, InstrumentTag
from sdk_dev.repo import repo_root


# %% [markdown]
# ## Surface
#
# What the client exposes. Widen or narrow the filter until every endpoint the mapping below uses is listed here.

# %%
from sdk_dev.surface import surface

print(
  surface('typed_aster', 'Aster', grep=r'earn|stak|saving|yield|lend|product|subscri')
)


# %% [markdown]
# ## `instruments`
#
# Fetch the venue's yield-bearing instruments.


# %%
# Unavailable: Aster Chain staking is mainnet-only and its documented API publishes no instrument APR
async def instruments(
  *,
  tags: Collection[InstrumentTag] | None = None,
  assets: Collection[str] | None = None,
) -> Sequence[Instrument]:
  """Do not turn locked totals or account rewards into an invented annual rate."""
  raise NotImplementedError('No testnet Earn catalogue or native instrument APR')


try:
  await instruments()
except NotImplementedError as exc:
  print(str(exc))
else:
  raise AssertionError('Review coverage: the method is no longer unavailable')


# %% [markdown]
# ## Coverage
#
# | method | status | note |
# |---|---|---|
# | `instruments` | not supported | No testnet Earn surface; mainnet chain staking exposes totals/positions/rewards, not the required instrument APR |
#
# `Aster.new(mainnet=False).chain` still points at mainnet for public calls. No chain
# call is made here. See [staking API](https://asterdex.github.io/aster-api-website/aster-chain/endpoints/).
# The absence of an APR in the documented API is not a missing typed endpoint.

# %% [markdown]
# ## Catalogue
#
# Every ID the verified methods returned, minus what the catalogue translates for this platform. Anything listed is a catalogue addition to make, not something to rename here: the SDK emits venue-native IDs and the catalogue maps them.

# %%
from sdk_dev.catalogue import Ids, gap, load_catalogue

# No instrument was emitted; this is not evidence of Earn coverage.
gap('aster', Ids(), load_catalogue(root=repo_root()))
