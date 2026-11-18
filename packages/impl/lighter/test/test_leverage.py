"""`set_leverage`: the `L2UpdateLeverage` sent, the margin mode kept and the shared read dropped."""

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

import pytest
from typing_extensions import Any, cast
from typed_lighter import Lighter
from typed_lighter.core.exc import BadRequest

from tribulnation.lighter.core import Shared
from tribulnation.lighter.market.account import CROSS, ISOLATED
from tribulnation.lighter.market.markets import LighterPerpMarket
from tribulnation.sdk.core import ApiError, AuthError

ACCOUNT = 7
MARKET = 1


@dataclass
class Tx:
  """Record `update_leverage` calls instead of signing them."""

  calls: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
  error: Exception | None = None
  """Raised instead of answering, when set."""

  async def update_leverage(self, **request: Any) -> dict[str, Any]:
    """Record the request."""
    self.calls.append(request)
    if self.error is not None:
      raise self.error
    return {'code': 200, 'tx_hash': 'ab'}


@dataclass
class AccountApi:
  """`/account` by index, with one position entry on `MARKET` when `mode` is set."""

  mode: int | None = None
  fraction: Decimal = Decimal('20')
  """The position's configured initial margin fraction, in percent."""
  requests: int = 0

  async def get(self, request: dict[str, Any]) -> dict[str, Any]:
    """The account, counting requests."""
    self.requests += 1
    positions: list[dict[str, Any]] = (
      []
      if self.mode is None
      else [
        {
          'market_id': MARKET,
          'margin_mode': self.mode,
          'initial_margin_fraction': self.fraction,
        }
      ]
    )
    return {'accounts': [{'index': request['value'], 'positions': positions}]}


@dataclass
class Api:
  """The REST API `set_leverage` reads."""

  account: AccountApi = field(default_factory=AccountApi)


@dataclass
class Client:
  """The client attributes `set_leverage` reaches."""

  tx: Tx = field(default_factory=Tx)
  api: Api = field(default_factory=Api)
  account_index: int | None = ACCOUNT
  account_signer: object | None = field(default_factory=object)
  """Any signer: trading checks one is configured."""


def detail(*, min_fraction: int = 200) -> dict[str, Any]:
  """A perp's details: a 50x maximum and a 10x default."""
  return {
    'market_id': MARKET,
    'min_initial_margin_fraction': min_fraction,
    'default_initial_margin_fraction': 1_000,
  }


def market(client: Client) -> LighterPerpMarket:
  """The fixture perp over `client`, with its details cached."""
  shared = Shared(client=cast(Lighter, client))
  shared.perps[MARKET] = cast(Any, detail())
  return LighterPerpMarket(shared=shared, market_index=MARKET)


async def test_sends_the_fraction_in_ten_thousandths_on_cross():
  """`10_000 / leverage` on cross margin when the account has no position entry."""
  client = Client()
  await market(client).set_leverage(Decimal('5'))
  assert client.tx.calls == [
    {'market_index': MARKET, 'initial_margin_fraction': 2_000, 'margin_mode': 'cross'}
  ]


@pytest.mark.parametrize(('mode', 'name'), [(CROSS, 'cross'), (ISOLATED, 'isolated')])
async def test_keeps_the_positions_margin_mode(mode: int, name: str):
  """The position's mode is resent, read fresh from `/account`."""
  client = Client()
  client.api.account.mode = mode
  await market(client).set_leverage(Decimal('20.0'))
  assert client.tx.calls == [
    {'market_index': MARKET, 'initial_margin_fraction': 500, 'margin_mode': name}
  ]
  assert client.api.account.requests == 1


@pytest.mark.parametrize('leverage', ['0', '-5', '2.5', '3', '7', '51', '100'])
async def test_refuses_bad_values_before_any_request(leverage: str):
  """Not whole, not positive, not dividing 10 000 (no rounding) or above the 50x maximum."""
  client = Client()
  with pytest.raises(ValueError):
    await market(client).set_leverage(Decimal(leverage))
  assert client.tx.calls == []
  assert client.api.account.requests == 0


async def test_accepts_the_market_maximum():
  """A fraction equal to `min_initial_margin_fraction` is allowed."""
  client = Client()
  await market(client).set_leverage(Decimal('50'))
  assert client.tx.calls[0]['initial_margin_fraction'] == 200


async def test_needs_an_api_key():
  """A read-only client is refused before any request."""
  client = Client(account_signer=None)
  with pytest.raises(AuthError):
    await market(client).set_leverage(Decimal('5'))
  assert client.tx.calls == []
  assert client.api.account.requests == 0


async def test_forgets_the_shared_account_read():
  """The next shared `leverage()` asks `/account` again and reads the new fraction."""
  client = Client()
  client.api.account.mode = CROSS
  m = market(client)
  minute = timedelta(minutes=1)
  assert await m.leverage(ttl=minute) == 5
  await m.set_leverage(Decimal('10'))
  client.api.account.fraction = Decimal('10')
  before = client.api.account.requests
  assert await m.leverage(ttl=minute) == 10
  assert client.api.account.requests == before + 1


async def test_forgets_the_shared_read_when_the_outcome_is_unknown():
  """A failed submission may have landed, so the shared answer is dropped as well."""
  client = Client()
  client.api.account.mode = CROSS
  client.tx.error = BadRequest('refused')
  m = market(client)
  minute = timedelta(minutes=1)
  await m.leverage(ttl=minute)
  with pytest.raises(ApiError):
    await m.set_leverage(Decimal('10'))
  before = client.api.account.requests
  await m.leverage(ttl=minute)
  assert client.api.account.requests == before + 1
