# %% [markdown]
# # aster `wallet` PoC
#
# Maps `typed_aster` onto the SDK `wallet` surface, one method per cell; Coverage records what ran on testnet and what remains unmapped. The rules, and how a typed-client issue is reported in `typed-client-issues.md`, are in `.agents/skills/sdk-poc/SKILL.md`.

# %%
from typing_extensions import Collection, Sequence
from dotenv import dotenv_values
from typed_aster import Aster
from sdk_dev.repo import repo_root
from tribulnation.sdk.wallet.deposit_methods import DepositMethod
from tribulnation.sdk.wallet.withdrawal_methods import WithdrawalMethod

credentials = dotenv_values(repo_root() / 'packages/impl/aster/poc/.env')
client = await Aster.new(
  mainnet=False,
  public=not bool(credentials.get('ASTER_SIGNER_PRIVATE_KEY')),
  user=credentials.get('ASTER_USER'),
  signer=credentials.get('ASTER_SIGNER_PRIVATE_KEY'),
).__aenter__()


# %% [markdown]
# ## Surface
#
# What the client exposes. Widen or narrow the filter until every endpoint the mapping below uses is listed here.

# %%
from sdk_dev.surface import surface

print(
  surface('typed_aster', 'Aster', grep=r'deposit|withdraw|coin|currenc|network|chain')
)


# %% [markdown]
# ## `deposit_methods`
#
# Fetch the ways to deposit: one entry per asset and network.


# %%
# Not yet mapped: typed-aster 0.2.0 exposes client.bapi.wallet.deposit_assets
async def deposit_methods(
  *, assets: Collection[str] | None = None
) -> Sequence[DepositMethod]:
  """Leave the deposit catalogue unmapped until the mainnet-only BAPI is qualified."""
  raise NotImplementedError('Aster deposit catalogue is not mapped yet')


try:
  await deposit_methods()
except NotImplementedError as exc:
  print(str(exc))
else:
  raise AssertionError('Review coverage: the method is no longer unavailable')


# %% [markdown]
# ## `withdrawal_methods`
#
# Fetch the ways to withdraw: one entry per asset and network, with its fee.


# %%
# Not yet mapped: typed-aster 0.2.0 exposes client.bapi.wallet.withdraw_assets
async def withdrawal_methods(
  *, assets: Collection[str] | None = None, networks: Collection[str] | None = None
) -> Sequence[WithdrawalMethod]:
  """Leave the withdrawal catalogue unmapped until the mainnet-only BAPI is qualified."""
  raise NotImplementedError('Aster withdrawal catalogue is not mapped yet')


try:
  await withdrawal_methods()
except NotImplementedError as exc:
  print(str(exc))
else:
  raise AssertionError('Review coverage: the method is no longer unavailable')


# %% [markdown]
# ## Coverage
#
# | method | status | note |
# |---|---|---|
# | `deposit_methods` | not attempted | typed-aster 0.2.0 adds the mainnet-only BAPI catalogue; mapping deferred to a follow-up |
# | `withdrawal_methods` | not attempted | Same; account-scoped withdrawal-info also returns a testnet venue error |
#
# The probe below records the venue rejection separately from a typed validation issue:
# code -1000 initially, and a gateway timeout on a subsequent run. No withdrawal or
# deposit-address creation is executed. A balance-limited withdrawal list is not a
# replacement for the documented complete asset catalogue.

# %% [markdown]
# ## Catalogue
#
# Every ID the verified methods returned, minus what the catalogue translates for this platform. Anything listed is a catalogue addition to make, not something to rename here: the SDK emits venue-native IDs and the catalogue maps them.

# %%
from sdk_dev.catalogue import Ids, gap, load_catalogue

# No method emitted IDs: an empty diff is not wallet coverage.
gap('aster', Ids(), load_catalogue(root=repo_root()))

# %% [markdown]
# ## Withdrawal-info availability

# %%
from pydantic import TypeAdapter
from typing_extensions import NotRequired, TypedDict
from typed_aster import ApiError


class ErrorBody(TypedDict):
  """Error code/message or gateway status, with credential-bearing fields dropped."""

  code: NotRequired[int]
  msg: NotRequired[str]
  status: NotRequired[int]
  error: NotRequired[str]
  message: NotRequired[str]


try:
  withdrawal_info = await client.futures.wallet.withdraw_info()
except ApiError as exc:
  print(TypeAdapter(ErrorBody).validate_python(exc.args[1]))
else:
  print(
    'Withdrawal metadata available; re-run the mapping:',
    list(withdrawal_info['balances']),
  )

# %%
await client.__aexit__(None, None, None)  # pyright: ignore[reportUnknownMemberType] -- upstream lifecycle parameters are untyped
