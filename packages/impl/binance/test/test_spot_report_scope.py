"""Spot-side reports work without any futures surface or permissions."""

from datetime import datetime, timezone
import asyncio
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from typing_extensions import AsyncIterator, Self, cast

import pytest
from typed_binance import Binance
from tribulnation.binance.reporting import Reporting
from tribulnation.binance.reporting.history.spot import TRANSFER_TYPES
from tribulnation.sdk import AuthError
from tribulnation.sdk.reporting import Balances, HistoryRecord


class Pages:
  """Minimal deterministic endpoint pages, with no network dependency."""

  def __init__(self, *pages: list[dict[str, object]]):
    """Keep the exact pages the fixture should expose."""
    self.pages = pages

  def via(self, call: object) -> Self:
    """Accept the request middleware used by the real Typed pager."""
    return self

  async def __aiter__(self) -> AsyncIterator[list[dict[str, object]]]:
    """Yield the configured response pages."""
    for page in self.pages:
      yield page


async def test_snapshot_has_only_spot_funding_and_earn():
  """Missing futures namespaces cannot break or fabricate a futures compartment."""
  client = cast(
    Binance,
    SimpleNamespace(
      spot=SimpleNamespace(
        http=SimpleNamespace(
          account=SimpleNamespace(
            info=AsyncMock(
              return_value={
                'balances': [
                  {'asset': 'USDT', 'free': Decimal(2), 'locked': Decimal(3)},
                  {'asset': 'BTC', 'free': Decimal(1), 'locked': Decimal(0)},
                ]
              }
            )
          ),
          wallet=SimpleNamespace(
            asset=SimpleNamespace(
              funding_wallet=AsyncMock(
                return_value=[
                  {
                    'asset': 'USDT',
                    'free': Decimal(1),
                    'locked': Decimal(2),
                    'freeze': Decimal(3),
                    'withdrawing': Decimal(4),
                  },
                ]
              )
            )
          ),
          simple_earn=SimpleNamespace(
            flexible=SimpleNamespace(
              position_paged=Mock(
                return_value=Pages(
                  [{'asset': 'USDT', 'totalAmount': Decimal(5)}],
                  [{'asset': 'USDT', 'totalAmount': Decimal(6)}],
                )
              )
            ),
            locked=SimpleNamespace(
              position_paged=Mock(
                return_value=Pages(
                  [{'asset': 'USDT', 'amount': Decimal(7), 'redeemingAmt': Decimal(8)}],
                )
              )
            ),
          ),
        )
      )
    ),
  )
  result = await Reporting(client=client).snapshot(['USDT'])
  states = {row.subaccount: row for row in result.snapshot.subaccounts}
  assert set(states) == {'spot', 'funding', 'earn'}
  assert states['spot'].balances == {'USDT': 5}
  assert states['funding'].balances == {'USDT': 10}
  assert states['earn'].balances == {'USDT': 26}
  assert all(not row.positions for row in states.values())


@pytest.mark.parametrize(
  'failed', ['spot_balances', 'funding_balances', 'earn_balances']
)
async def test_supported_snapshot_rejections_are_not_empty(
  failed: str,
  monkeypatch: pytest.MonkeyPatch,
):
  """A denied supported compartment is a failed read, not an empty account."""
  finished: list[bool] = []

  async def slow_success(*args: object, **kwargs: object) -> Balances:
    """Finish a sibling request after the rejected request has already raised."""
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    finished.append(True)
    return Balances()

  for name in ('spot_balances', 'funding_balances', 'earn_balances'):
    monkeypatch.setattr(
      Reporting,
      name,
      AsyncMock(
        return_value=Balances(),
        side_effect=AuthError('fake rejection') if name == failed else slow_success,
      ),
    )
  with pytest.raises(AuthError):
    await Reporting(client=Binance.new(public=True)).snapshot()
  assert len(finished) == 2


async def test_history_has_only_spot_side_sources():
  """Real orchestration needs only spot endpoints, including Spot/Funding transfers."""
  transfer = Mock(return_value=Pages([]))
  client = cast(
    Binance,
    SimpleNamespace(
      spot=SimpleNamespace(
        http=SimpleNamespace(
          market=SimpleNamespace(exchange_info=AsyncMock(return_value={'symbols': []})),
          wallet=SimpleNamespace(
            capital=SimpleNamespace(
              deposit=SimpleNamespace(history_paged=Mock(return_value=Pages([]))),
              withdraw=SimpleNamespace(history_paged=Mock(return_value=Pages([]))),
            ),
            asset=SimpleNamespace(transfer=SimpleNamespace(history_paged=transfer)),
          ),
        )
      )
    ),
  )
  end = datetime(2026, 9, 9, tzinfo=timezone.utc)
  assert [row async for row in Reporting(client=client).history(end=end)] == []
  assert list(TRANSFER_TYPES) == ['MAIN_FUNDING', 'FUNDING_MAIN']
  assert [call.args[0] for call in transfer.call_args_list] == list(TRANSFER_TYPES)


async def test_history_does_not_hide_supported_source_rejections(
  monkeypatch: pytest.MonkeyPatch,
):
  """Failure on the first supported source is not swallowed as a permission gap."""

  async def rejected(*args: object, **kwargs: object) -> AsyncIterator[HistoryRecord]:
    """Fail while iterating the source, before any real endpoint can run."""
    raise AuthError('fake rejection')
    yield  # pragma: no cover

  monkeypatch.setattr(Reporting, 'crypto_deposits', rejected)
  with pytest.raises(AuthError):
    _ = [row async for row in Reporting(client=Binance.new(public=True)).history()]
