"""Linear leverage: read from the position list, set on the symbol's leverage step,
and used for the available notional."""

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from typing_extensions import Any
from typed_bybit import ApiError as ClientApiError, Bybit

from tribulnation.bybit.market import PerpMarket
from tribulnation.bybit.market.impl import Cache
from tribulnation.sdk.core import ApiError, MissingData

SYMBOL = 'BTCUSDT'


def instrument(step: str = '0.01') -> dict[str, Any]:
  """The symbol's catalogue row, as far as leverage goes."""
  return {
    'symbol': SYMBOL,
    'leverageFilter': {
      'minLeverage': Decimal(1),
      'maxLeverage': Decimal(100),
      'leverageStep': Decimal(step),
    },
  }


def row(leverage: str, *, idx: int = 0, side: str = '') -> dict[str, Any]:
  """A `/v5/position/list` row; flat unless `side` is given."""
  return {'symbol': SYMBOL, 'positionIdx': idx, 'side': side, 'leverage': leverage}


def market(step: str = '0.01') -> PerpMarket:
  """A market over a public client, with the catalogue already cached."""
  cache = Cache()
  cache.perp = {SYMBOL: instrument(step)}  # type: ignore[assignment]
  return PerpMarket(client=Bybit.new(public=True), cache=cache, symbol=SYMBOL)


def wallet(available: str) -> dict[str, Any]:
  """A `/v5/account/wallet-balance` answer with one unified account."""
  return {'list': [{'accountType': 'UNIFIED', 'totalAvailableBalance': available}]}


@pytest.fixture
def venue(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
  """Patch the position list, set-leverage and account endpoints."""
  client = Bybit.new(public=True)
  mocks = {
    'list': AsyncMock(return_value={'category': 'linear', 'list': [row('10')]}),
    'set': AsyncMock(return_value={}),
    'wallet': AsyncMock(return_value=wallet('1000')),
    'info': AsyncMock(return_value={'marginMode': 'REGULAR_MARGIN'}),
  }
  monkeypatch.setattr(type(client.position), 'list', mocks['list'])
  monkeypatch.setattr(type(client.position), 'set_leverage', mocks['set'])
  monkeypatch.setattr(type(client.account), 'wallet_balance', mocks['wallet'])
  monkeypatch.setattr(type(client.account), 'info', mocks['info'])
  return mocks


async def test_leverage_reads_symbol_setting(venue: dict[str, AsyncMock]):
  """The setting comes from a symbol-scoped linear position list, fresh each call."""
  m = market()
  assert await m.leverage() == Decimal(10)
  assert await m.leverage() == Decimal(10)
  assert venue['list'].await_count == 2
  assert venue['list'].await_args_list[-1].args == ('linear',)
  assert venue['list'].await_args_list[-1].kwargs['symbol'] == SYMBOL


async def test_leverage_hedge_rows_take_lowest(venue: dict[str, AsyncMock]):
  """Hedge mode lists both legs; the lowest setting is used."""
  venue['list'].return_value = {
    'category': 'linear',
    'list': [row('12.5', idx=1, side='Buy'), row('10', idx=2, side='Sell')],
  }
  assert await market().leverage() == Decimal(10)


async def test_leverage_missing_row(venue: dict[str, AsyncMock]):
  """No row for the symbol is a malformed answer."""
  venue['list'].return_value = {'category': 'linear', 'list': []}
  with pytest.raises(MissingData):
    await market().leverage()


async def test_leverage_portfolio_margin(venue: dict[str, AsyncMock]):
  """Portfolio margin reports an empty leverage: there is no per-symbol setting."""
  venue['list'].return_value = {'category': 'linear', 'list': [row('')]}
  with pytest.raises(NotImplementedError):
    await market().leverage()


@pytest.mark.parametrize(
  ('leverage', 'sent'),
  [(Decimal('10'), '10'), (Decimal('1E+1'), '10'), (Decimal('12.50'), '12.5')],
)
async def test_set_leverage_request(
  venue: dict[str, AsyncMock], leverage: Decimal, sent: str
):
  """Buy and sell leverage are sent alike, as plain decimals, with no margin mode."""
  await market().set_leverage(leverage)
  venue['set'].assert_awaited_once()
  assert venue['set'].await_args_list[-1].args == ('linear',)
  kwargs = dict(venue['set'].await_args_list[-1].kwargs)
  kwargs.pop('validate')
  assert kwargs == {'symbol': SYMBOL, 'buy_leverage': sent, 'sell_leverage': sent}


@pytest.mark.parametrize(
  ('leverage', 'step'),
  [
    (Decimal(0), '0.01'),
    (Decimal(-5), '0.01'),
    (Decimal('10.005'), '0.01'),
    (Decimal('10.5'), '1'),
  ],
)
async def test_set_leverage_refuses_off_step(
  venue: dict[str, AsyncMock], leverage: Decimal, step: str
):
  """Non-positive values and values off the leverage step never reach the venue."""
  with pytest.raises(ValueError):
    await market(step).set_leverage(leverage)
  venue['set'].assert_not_awaited()


async def test_set_leverage_not_modified_succeeds(venue: dict[str, AsyncMock]):
  """`retCode` 110043, the leverage already set, is success."""
  venue['set'].side_effect = ClientApiError(110043, 'leverage not modified', {})
  await market().set_leverage(Decimal(10))


async def test_set_leverage_other_errors_translate(venue: dict[str, AsyncMock]):
  """Other refusals surface as SDK errors."""
  venue['set'].side_effect = ClientApiError(110013, 'cannot set leverage', {})
  with pytest.raises(ApiError):
    await market().set_leverage(Decimal(10))


async def test_set_then_read(venue: dict[str, AsyncMock]):
  """Reads are not shared, so the next `leverage()` asks the venue."""
  m = market()
  await m.leverage()
  await m.set_leverage(Decimal(20))
  venue['list'].return_value = {'category': 'linear', 'list': [row('20')]}
  assert await m.leverage() == Decimal(20)
  assert venue['list'].await_count == 2


async def test_available_notional_uses_set_leverage(venue: dict[str, AsyncMock]):
  """Free collateral times the symbol's setting, not the catalogue maximum (100)."""
  venue['list'].return_value = {'category': 'linear', 'list': [row('5')]}
  assert await market().available_notional() == Decimal(5000)


async def test_available_notional_reads_two_endpoints(venue: dict[str, AsyncMock]):
  """One symbol-scoped position list and one wallet balance, nothing else."""
  await market().available_notional()
  assert venue['list'].await_count == 1
  assert venue['list'].await_args_list[-1].kwargs['symbol'] == SYMBOL
  assert venue['wallet'].await_count == 1
  venue['info'].assert_not_awaited()


async def test_available_notional_empty_balance(venue: dict[str, AsyncMock]):
  """An empty available balance, or no unified account, opens nothing."""
  venue['wallet'].return_value = wallet('')
  assert await market().available_notional() == 0
  venue['wallet'].return_value = {'list': []}
  assert await market().available_notional() == 0


async def test_available_notional_without_leverage(venue: dict[str, AsyncMock]):
  """Portfolio margin has no setting: raise before reading the balance."""
  venue['list'].return_value = {'category': 'linear', 'list': [row('')]}
  with pytest.raises(NotImplementedError):
    await market().available_notional()
  venue['wallet'].assert_not_awaited()
