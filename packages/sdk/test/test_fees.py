"""Public rules and personal fee rates have distinct, explicit contracts."""

from decimal import Decimal
from dataclasses import fields
from unittest.mock import AsyncMock
from types import SimpleNamespace

import pytest

from tribulnation.sdk import MarketSDK
from tribulnation.sdk.market import Book, Fees, Rules


def test_rules_unknown_fees_do_not_mean_zero():
  """Metadata remains usable when no reliable public fee schedule is available."""
  rules = Rules(
    fee_asset='USDT',
    tick_size=Decimal('0.1'),
    step_size=Decimal('0.001'),
    api=True,
  )
  assert rules.fees is None
  assert not {'base', 'quote'} & {field.name for field in fields(Rules)}
  assert rules.round_price(Decimal('10.11')) == Decimal('10.1')


@pytest.mark.parametrize('rate', [Decimal(0), Decimal('-0.0001'), Decimal('0.001')])
def test_account_rates_preserve_zero_and_rebates(rate: Decimal):
  """A real zero and a negative maker rebate must survive unchanged."""
  fees = Fees.symmetric(maker=rate, taker=rate)
  assert fees.maker_buy == fees.maker_sell == fees.taker_buy == fees.taker_sell == rate


@pytest.mark.parametrize('rate', [Decimal('NaN'), Decimal('Infinity'), None, 0.001])
def test_account_rates_reject_unknown_or_nonfinite(rate: object):
  """Malformed personal fee responses cannot become valid execution inputs."""
  with pytest.raises(ValueError, match='finite Decimals'):
    Fees.symmetric(maker=rate, taker=Decimal(0))  # type: ignore[arg-type]


async def test_account_fee_routing_preserves_refetch(monkeypatch: pytest.MonkeyPatch):
  """Root, venue and exchange fee calls reach the exact market and refresh flag."""
  expected = Fees.symmetric(maker=Decimal('0.001'), taker=Decimal('0.002'))
  call = AsyncMock(return_value=expected)
  async with MarketSDK() as sdk:
    venue = await sdk.venue('binance')
    exchange = await venue.exchange('spot')
    for router, identifier in (
      (sdk, 'binance:spot:BTCUSDT'),
      (venue, 'spot:BTCUSDT'),
      (exchange, 'BTCUSDT'),
    ):
      market = AsyncMock(return_value=SimpleNamespace(fees=call))
      monkeypatch.setattr(type(router), 'market', market)
      assert await router.fees(identifier, refetch=True) is expected
      market.assert_awaited_once_with(identifier)
  assert call.await_count == 3
  for invocation in call.call_args_list:
    assert invocation.kwargs == {'refetch': True}


@pytest.mark.parametrize('maker,bid,ask', [(True, '98', '101'), (False, '96', '103')])
def test_book_uses_matching_side_and_role(maker: bool, bid: str, ask: str):
  """Four different rates make any accidental buy/sell or maker/taker swap visible."""
  fees = Fees(
    maker_buy=Decimal('.01'),
    maker_sell=Decimal('.02'),
    taker_buy=Decimal('.03'),
    taker_sell=Decimal('.04'),
  )
  book = Book(
    bids=[Book.Entry(Decimal(100), Decimal(1))],
    asks=[Book.Entry(Decimal(100), Decimal(1))],
  )
  adjusted = book.with_fees(fees, maker=maker)
  assert adjusted.best_bid.price == Decimal(bid)
  assert adjusted.best_ask.price == Decimal(ask)
  assert book.best_bid.price == book.best_ask.price == 100
  assert book.with_fees(Decimal('.01'), maker=maker).best_bid.price == 99
