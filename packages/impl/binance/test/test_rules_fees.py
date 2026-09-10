"""Public Binance rules never require account commissions."""

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from tribulnation.binance import BinanceMarket
from tribulnation.sdk.market import Fees
from tribulnation.binance.market.spot_market import SpotMarket
from typed_binance.spot.http.account.commission import Commission
from typed_binance.usdm_futures.http.market.exchange_info import ExchangeInfoEndpoint
from typed_binance.usdm_futures.http.trading.trading_fee import TradingFee


def symbol(*, quote: str = 'USDT', kind: str = 'COIN') -> dict[str, object]:
  """A decoded contract whose precision deliberately differs from its filters."""
  return {
    'symbol': 'BTCUSDT',
    'contractType': 'PERPETUAL',
    'status': 'TRADING',
    'baseAsset': 'BTC',
    'quoteAsset': quote,
    'marginAsset': quote,
    'underlyingType': kind,
    'pricePrecision': 8,
    'quantityPrecision': 8,
    'filters': [
      {
        'filterType': 'PRICE_FILTER',
        'tickSize': Decimal('0.1'),
        'minPrice': Decimal('0.1'),
        'maxPrice': Decimal('1000000'),
      },
      {
        'filterType': 'LOT_SIZE',
        'stepSize': Decimal('0.001'),
        'minQty': Decimal('0.001'),
        'maxQty': Decimal('1000'),
      },
      {'filterType': 'MIN_NOTIONAL', 'notional': Decimal(5)},
      {
        'filterType': 'PERCENT_PRICE',
        'multiplierDown': Decimal('0.9'),
        'multiplierUp': Decimal('1.1'),
      },
    ],
  }


async def test_public_rules_share_discovery_cache(monkeypatch: pytest.MonkeyPatch):
  """Metadata uses actual increments, and explicit refresh fetches once again."""
  metadata = AsyncMock(return_value={'symbols': [symbol()]})
  personal = AsyncMock(side_effect=AssertionError('Private endpoint called'))
  monkeypatch.setattr(ExchangeInfoEndpoint, 'exchange_info', metadata)
  monkeypatch.setattr(TradingFee, 'trading_fee', personal)
  async with BinanceMarket.new(public=True) as venue:
    exchange = await venue.perp_exchange('usdm')
    assert await exchange.markets() == ['BTCUSDT']
    market = await exchange.market('BTCUSDT')
    rules = await market.rules()
    assert rules.fee_asset == 'USDT'
    assert rules.tick_size == Decimal('0.1')
    assert rules.step_size == Decimal('0.001')
    assert rules.min_value == 5 and rules.api
    assert rules.rel_min_price == Decimal('0.9')
    assert rules.fees == Fees.symmetric(
      maker=Decimal('0.0002'), taker=Decimal('0.0005')
    )
    metadata.assert_awaited_once()
    await market.rules(refetch=True)
    assert metadata.await_count == 2
  personal.assert_not_awaited()


@pytest.mark.parametrize('quote,kind', [('USDC', 'COIN'), ('USDT', 'INDEX')])
async def test_public_rates_are_not_guessed_for_other_products(
  monkeypatch: pytest.MonkeyPatch,
  quote: str,
  kind: str,
):
  """USDT crypto rates are not silently applied to other schedules."""
  monkeypatch.setattr(
    ExchangeInfoEndpoint,
    'exchange_info',
    AsyncMock(return_value={'symbols': [symbol(quote=quote, kind=kind)]}),
  )
  async with BinanceMarket.new(public=True) as venue:
    rules = await (await venue.perp_market('usdm:BTCUSDT')).rules()
  assert rules.fees is None


async def test_missing_filter_increments_fail(monkeypatch: pytest.MonkeyPatch):
  """Precision is not an acceptable substitute for a missing filter increment."""
  info = symbol()
  info['filters'] = [{'filterType': 'PRICE_FILTER'}, {'filterType': 'LOT_SIZE'}]
  monkeypatch.setattr(
    ExchangeInfoEndpoint,
    'exchange_info',
    AsyncMock(return_value={'symbols': [info]}),
  )
  async with BinanceMarket.new(public=True) as venue:
    with pytest.raises(ValueError, match='positive price/quantity increments'):
      await (await venue.perp_market('usdm:BTCUSDT')).rules()


@pytest.mark.parametrize(
  'rates',
  [
    {},
    {
      'symbol': 'ETHUSDT',
      'makerCommissionRate': Decimal(0),
      'takerCommissionRate': Decimal('0.001'),
    },
  ],
)
async def test_personal_fee_missing_or_wrong_symbol_fails(
  monkeypatch: pytest.MonkeyPatch,
  rates: dict[str, object],
):
  """Account failures cannot become public defaults or zero-rate success."""
  monkeypatch.setattr(TradingFee, 'trading_fee', AsyncMock(return_value=rates))
  async with BinanceMarket.new(public=True) as venue:
    with pytest.raises(ValueError, match='missing matching rates'):
      await (await venue.perp_market('usdm:BTCUSDT')).fees()


@pytest.mark.parametrize('symbol_id', ['BTCUSDT', 'ETHUSDT'])
async def test_spot_personal_rates_validate_symbol_and_preserve_zero(
  monkeypatch: pytest.MonkeyPatch,
  symbol_id: str,
):
  """A genuine account zero is valid, but a different symbol's fee is not."""
  source = AsyncMock(
    return_value={
      'symbol': symbol_id,
      'standardCommission': {
        'maker': Decimal(0),
        'taker': Decimal('0.0001'),
        'buyer': Decimal(0),
        'seller': Decimal(0),
      },
      'taxCommission': dict.fromkeys(('maker', 'taker', 'buyer', 'seller'), Decimal(0)),
      'specialCommission': dict.fromkeys(
        ('maker', 'taker', 'buyer', 'seller'), Decimal(0)
      ),
    }
  )
  monkeypatch.setattr(Commission, 'commission', source)
  async with BinanceMarket.new(public=True) as venue:
    market = SpotMarket(shared=venue.shared, symbol='BTCUSDT')
    if symbol_id != 'BTCUSDT':
      with pytest.raises(ValueError, match='wrong symbol'):
        await market.fees()
    else:
      fees = await market.fees()
      assert fees == Fees.symmetric(maker=Decimal(0), taker=Decimal('0.0001'))
  source.assert_awaited_once_with('BTCUSDT')


async def test_spot_fees_combine_every_side_component(monkeypatch: pytest.MonkeyPatch):
  """Tax and special rates are additive; BNB payment does not discount this quote."""
  source = AsyncMock(
    return_value={
      'symbol': 'BTCUSDT',
      'standardCommission': {
        'maker': Decimal('0.001'),
        'taker': Decimal('0.002'),
        'buyer': Decimal('0.003'),
        'seller': Decimal('0.004'),
      },
      'taxCommission': {
        'maker': Decimal('0.0001'),
        'taker': Decimal('0.0002'),
        'buyer': Decimal('0.0003'),
        'seller': Decimal('0.0004'),
      },
      'specialCommission': {
        'maker': Decimal('-0.00001'),
        'taker': Decimal('0.00002'),
        'buyer': Decimal('0.00003'),
        'seller': Decimal('0.00004'),
      },
      'discount': {
        'enabledForAccount': True,
        'enabledForSymbol': True,
        'discountAsset': 'BNB',
        'discount': Decimal('0.25'),
      },
    }
  )
  monkeypatch.setattr(Commission, 'commission', source)
  async with BinanceMarket.new(public=True) as venue:
    market = SpotMarket(shared=venue.shared, symbol='BTCUSDT')
    assert await market.fees() == Fees(
      maker_buy=Decimal('0.00442'),
      maker_sell=Decimal('0.00553'),
      taker_buy=Decimal('0.00555'),
      taker_sell=Decimal('0.00666'),
    )


@pytest.mark.parametrize(
  'missing', ['standardCommission', 'taxCommission', 'specialCommission']
)
async def test_spot_fees_missing_components_do_not_become_zero(
  monkeypatch: pytest.MonkeyPatch,
  missing: str,
):
  """An absent charge group cannot silently yield an incomplete quote."""
  response: dict[str, object] = {
    key: dict.fromkeys(('maker', 'taker', 'buyer', 'seller'), Decimal(0))
    for key in ('standardCommission', 'taxCommission', 'specialCommission')
  }
  response['symbol'] = 'BTCUSDT'
  del response[missing]
  monkeypatch.setattr(Commission, 'commission', AsyncMock(return_value=response))
  async with BinanceMarket.new(public=True) as venue:
    with pytest.raises(KeyError, match=missing):
      await SpotMarket(shared=venue.shared, symbol='BTCUSDT').fees()


async def test_perp_personal_fees_are_symmetric_ordinary_rates(
  monkeypatch: pytest.MonkeyPatch,
):
  """Rebates survive and the distinct RPI commission cannot replace ordinary rates."""
  monkeypatch.setattr(
    TradingFee,
    'trading_fee',
    AsyncMock(
      return_value={
        'symbol': 'BTCUSDT',
        'makerCommissionRate': Decimal('-0.0001'),
        'takerCommissionRate': Decimal('0.0004'),
        'rpiCommissionRate': Decimal('0.5'),
      }
    ),
  )
  async with BinanceMarket.new(public=True) as venue:
    assert await (await venue.perp_market('usdm:BTCUSDT')).fees() == Fees.symmetric(
      maker=Decimal('-0.0001'),
      taker=Decimal('0.0004'),
    )
