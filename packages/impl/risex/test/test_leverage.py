"""Setting the account's leverage: the signed request, refusals before signing, and
the shared leverage read dropped afterwards."""

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from typing_extensions import Any, cast

import pytest
from typed_risex import RISEx, BadRequest as ClientBadRequest

from tribulnation.risex.core import Shared
from tribulnation.risex.market.markets import RisexPerpMarket
from tribulnation.sdk.core import AuthError, BadRequest

MINUTE = timedelta(minutes=1)


@dataclass
class Account:
  """Record `account` calls: one market's leverage setting and its updates."""

  leverage: Decimal = Decimal(50)
  calls: list[tuple[str, Any]] = field(default_factory=list[tuple[str, Any]])
  error: Exception | None = None

  async def position(self, market_id: int, *, account: str) -> Any:
    """The `account.position` row, with the current setting."""
    self.calls.append(('position', (market_id, account)))
    return {'position': {'leverage': self.leverage}}

  async def update_leverage(self, market_id: int, *, leverage: str) -> Any:
    """Record a leverage update and apply it."""
    self.calls.append(('update_leverage', (market_id, leverage)))
    if self.error is not None:
      raise self.error
    self.leverage = Decimal(leverage)
    return {'transaction_hash': '0x1', 'block_number': 1, 'receipt': {}}


def market(fake: Account, *, signer: bool = True) -> RisexPerpMarket:
  """BTC/USDC over a fake client, with or without a signer key."""
  credentials = SimpleNamespace(signer_key=object() if signer else None)
  client = SimpleNamespace(account=fake, credentials=credentials)
  shared = Shared(client=cast(RISEx, client), address='0xabc')
  return RisexPerpMarket(shared=shared, index_id=1)


def updates(fake: Account) -> list[tuple[str, Any]]:
  """The leverage updates sent."""
  return [c for c in fake.calls if c[0] == 'update_leverage']


async def test_set_leverage_sends_the_whole_multiple_and_rereads():
  """The setting goes out as the venue's whole-number string, and the shared
  `account.position` read is dropped, so `leverage()` asks again."""
  fake = Account()
  m = market(fake)
  assert await m.leverage(ttl=MINUTE) == 50
  await m.set_leverage(Decimal('7.0'))
  assert updates(fake) == [('update_leverage', (1, '7'))]
  assert await m.leverage(ttl=MINUTE) == 7
  assert [c[0] for c in fake.calls] == ['position', 'update_leverage', 'position']


async def test_set_leverage_sends_no_margin_mode():
  """Only the leverage endpoint is called: the margin mode is a separate setting."""
  fake = Account()
  await market(fake).set_leverage(Decimal(3))
  assert [c[0] for c in fake.calls] == ['update_leverage']


@pytest.mark.parametrize(
  'leverage', [Decimal(0), Decimal(-2), Decimal('2.5'), Decimal(256)]
)
async def test_set_leverage_refuses_before_signing(leverage: Decimal):
  """Non-positive, fractional and above-`uint8` multiples send nothing."""
  fake = Account()
  with pytest.raises(ValueError):
    await market(fake).set_leverage(leverage)
  assert fake.calls == []


async def test_set_leverage_takes_the_uint8_maximum():
  """255 is the highest multiple a permit carries."""
  fake = Account()
  await market(fake).set_leverage(Decimal(255))
  assert updates(fake) == [('update_leverage', (1, '255'))]


async def test_set_leverage_needs_a_signer():
  """Without a signer key nothing is sent."""
  fake = Account()
  with pytest.raises(AuthError):
    await market(fake, signer=False).set_leverage(Decimal(5))
  assert fake.calls == []


async def test_a_refusal_is_translated_and_keeps_the_read():
  """A venue refusal is a `BadRequest`, and the shared read is left as it was."""
  fake = Account(
    error=ClientBadRequest(
      'FailedPrecondition',
      'UpdateLeverage reverted',
      {'error': {'code': 'FailedPrecondition', 'message': 'UpdateLeverage reverted'}},
    )
  )
  m = market(fake)
  assert await m.leverage(ttl=MINUTE) == 50
  with pytest.raises(BadRequest):
    await m.set_leverage(Decimal(80))
  assert await m.leverage(ttl=MINUTE) == 50
  assert [c[0] for c in fake.calls] == ['position', 'update_leverage']
