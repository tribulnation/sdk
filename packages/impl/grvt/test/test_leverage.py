"""Setting leverage with `set_position_config`: the request, the margin type kept, values
refused before sending, and the shared leverage read dropped."""

from datetime import timedelta
from decimal import Decimal

import pytest
from typing_extensions import Any
from typed_core.exceptions import BadRequest as ClientBadRequest

from tribulnation.grvt.core import Shared
from tribulnation.grvt.market.markets import GrvtPerpMarket
from tribulnation.sdk import ApiError, AuthError, BadRequest

BTC = 'BTC_USDT_Perp'
ETH = 'ETH_USDT_Perp'


def row(instrument: str, margin_type: str, leverage: str) -> dict[str, Any]:
  """One `all_initial_leverage` result, allowing 1x to 50x."""
  return {
    'instrument': instrument,
    'leverage': Decimal(leverage),
    'min_leverage': Decimal('1'),
    'max_leverage': Decimal('50'),
    'margin_type': margin_type,
  }


def serve(fake: Any, *, ack: bool = True) -> tuple[list[int], list[dict[str, Any]]]:
  """Serve BTC isolated and ETH cross, each read's leverage the last one set.

  Returns:
    The leverage read log and the `set_position_config` requests.
  """
  reads: list[int] = []
  sent: list[dict[str, Any]] = []
  setting = {BTC: '10', ETH: '10'}

  async def all_initial_leverage() -> dict[str, Any]:
    """The current settings."""
    reads.append(1)
    return {
      'results': [row(BTC, 'ISOLATED', setting[BTC]), row(ETH, 'CROSS', setting[ETH])]
    }

  async def set_position_config(**kwargs: Any) -> dict[str, Any]:
    """Record and apply."""
    sent.append(kwargs)
    if ack:
      setting[kwargs['instrument']] = str(kwargs['leverage'])
    return {'ack': ack}

  fake.trading.all_initial_leverage = all_initial_leverage
  fake.trading.set_position_config = set_position_config
  return reads, sent


async def test_request_keeps_the_margin_type(shared: Shared, fake: Any):
  """The instrument's current margin type, read afresh, is sent back with the value."""
  reads, sent = serve(fake)
  await GrvtPerpMarket(shared=shared, instrument=ETH).set_leverage(Decimal('5'))
  await GrvtPerpMarket(shared=shared, instrument=BTC).set_leverage(Decimal('20.0'))
  assert sent == [
    {'instrument': ETH, 'margin_type': 'CROSS', 'leverage': Decimal(5)},
    {'instrument': BTC, 'margin_type': 'ISOLATED', 'leverage': Decimal(20)},
  ]
  assert reads == [1, 1]


async def test_shared_read_is_forgotten(shared: Shared, fake: Any):
  """A cached leverage read is not reused by the set, and is dropped after it."""
  reads, _ = serve(fake)
  eth = GrvtPerpMarket(shared=shared, instrument=ETH)
  hour = timedelta(hours=1)
  assert await eth.leverage(ttl=hour) == 10 and reads == [1]
  await eth.set_leverage(Decimal(3))
  assert reads == [1, 1]
  assert await eth.leverage(ttl=hour) == 3 and reads == [1, 1, 1]


@pytest.mark.parametrize('value', ['0', '-2', '2.5', '51'])
async def test_bad_values_send_nothing(shared: Shared, fake: Any, value: str):
  """Non-whole, non-positive and out-of-range values raise before any change is sent."""
  _, sent = serve(fake)
  with pytest.raises(ValueError):
    await GrvtPerpMarket(shared=shared, instrument=ETH).set_leverage(Decimal(value))
  assert sent == []


async def test_needs_the_private_key(make_fake: Any, make_shared: Any):
  """Without the signer key nothing is read or sent."""
  fake = make_fake(private_key=False)
  reads, sent = serve(fake)
  with pytest.raises(AuthError):
    await GrvtPerpMarket(shared=make_shared(fake), instrument=ETH).set_leverage(
      Decimal(5)
    )
  assert reads == [] and sent == []


async def test_unacknowledged_and_refused(shared: Shared, fake: Any):
  """A refused ack is an `ApiError`; venue errors are translated; both drop the read."""
  reads, _ = serve(fake, ack=False)
  eth = GrvtPerpMarket(shared=shared, instrument=ETH)
  with pytest.raises(ApiError):
    await eth.set_leverage(Decimal(5))

  async def refuse(**kwargs: Any) -> Any:
    """Refuse."""
    raise ClientBadRequest(400, 'Bad Request')

  fake.trading.set_position_config = refuse
  with pytest.raises(BadRequest):
    await eth.set_leverage(Decimal(5))
  count = len(reads)
  await eth.leverage(ttl=timedelta(hours=1))
  assert len(reads) == count + 1
