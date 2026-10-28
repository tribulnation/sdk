"""Spot (`SPOT_SWAP`) mappings: discovery by kind, rules and fees, the spot wallet's
balances and collateral IDs, and kind-scoped orders and fills."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from typing_extensions import Any, Sequence, cast
from typed_core import PaginatedResponse
from typed_grvt.schemas import Fill, InstrumentDisplay

from tribulnation.grvt.core import Shared
from tribulnation.grvt.market.exchanges import GrvtPerpExchange, GrvtSpotExchange
from tribulnation.grvt.market.markets import GrvtSpotMarket
from tribulnation.grvt.market.venue import GrvtMarket
from tribulnation.sdk import AuthError
from tribulnation.sdk.market import Balance, ExchangeTrade, Fees, SpotCollateralIds

BTC = 'BTC_USDT_Perp'
GRVT_PERP = 'GRVT_USDT_Perp'
GRVT = 'GRVT_USDT_SpotSwap'
USDC = 'USDC_USDT_SpotSwap'
END = datetime(2026, 10, 28, 16, tzinfo=timezone.utc)


def spot(name: str, **changes: object) -> InstrumentDisplay:
  """A mainnet spot instrument as `all_instruments` sent it (2026-10-28)."""
  base = name.split('_')[0]
  row: dict[str, Any] = {
    'instrument': name,
    'instrument_hash': '0x039308',
    'base': base,
    'quote': 'USDT',
    'kind': 'SPOT_SWAP',
    'venues': ['ORDERBOOK'],
    'base_decimals': 6,
    'quote_decimals': 6,
    'tick_size': Decimal('0.0001'),
    'min_size': Decimal('1.0'),
    'create_time': datetime(2026, 9, 30, 7, 46, 29, tzinfo=timezone.utc),
    'min_notional': Decimal('5.0'),
    'asset_class': 'CRYPTO',
    'status': 'ACTIVE',
  }
  return cast(InstrumentDisplay, {**row, **changes})


def wallet_row(currency: str, balance: str, available: str) -> dict[str, Any]:
  """One `spot_balances` row, with illustrative amounts."""
  return {
    'currency': currency,
    'balance': Decimal(balance),
    'index_price': Decimal(1),
    'entry_price': Decimal(1),
    'realized_pnl': Decimal(0),
    'unrealized_pnl': Decimal(0),
    'available_to_transfer': Decimal(available),
  }


@pytest.fixture
def mixed(make_fake: Any, make_shared: Any, make_instrument: Any, fake: Any) -> Shared:
  """Perpetuals and spot instruments cached together; `GRVT_USDT_Perp` shares its base
  and quote with `GRVT_USDT_SpotSwap`."""
  return make_shared(
    fake,
    make_instrument(BTC),
    make_instrument(GRVT_PERP),
    spot(GRVT),
    spot(USDC, tick_size=Decimal('0.00001')),
  )


async def test_exchanges_list_their_own_kind(mixed: Shared):
  """Each exchange lists and opens only its kind's instruments."""
  perp = GrvtPerpExchange(shared=mixed)
  spot_exchange = GrvtSpotExchange(shared=mixed)
  assert await perp.markets() == [BTC, GRVT_PERP]
  assert await spot_exchange.markets() == [GRVT, USDC]
  assert (await spot_exchange.market(GRVT)).market_id == GRVT
  with pytest.raises(ValueError, match='spot instrument'):
    await spot_exchange.market(GRVT_PERP)
  with pytest.raises(ValueError, match='perpetual'):
    await perp.market(GRVT)


async def test_venue_lists_both_exchanges(mixed: Shared):
  """`spot` resolves to the spot exchange; ids carry the exchange."""
  venue = GrvtMarket(shared=mixed)
  assert [e['id'] for e in await venue.exchanges()] == ['perp', 'spot']
  exchange = await venue.spot_exchange('spot')
  assert isinstance(exchange, GrvtSpotExchange)
  market = await exchange.market(GRVT)
  assert (market.kind, market.id) == ('spot', f'grvt:spot:{GRVT}')
  with pytest.raises(ValueError):
    await venue.exchange('futures')


async def test_spot_rules_name_the_pair_without_a_schedule(mixed: Shared):
  """Base and quote are the instrument's; fees go in the delivered asset and GRVT
  publishes no standard spot rates."""
  rules = await GrvtSpotMarket(shared=mixed, instrument=USDC).rules()
  assert (rules.base, rules.quote) == ('USDC', 'USDT')
  assert (rules.tick_size, rules.step_size, rules.fixed_min_qty, rules.min_value) == (
    Decimal('0.00001'),
    Decimal('1.0'),
    Decimal('1.0'),
    Decimal('5.0'),
  )
  assert rules.fee_asset is None and rules.fees is None and rules.api
  delisted = make_delisted(mixed)
  assert not (await GrvtSpotMarket(shared=delisted, instrument=GRVT).rules()).api


def make_delisted(shared: Shared) -> Shared:
  """`shared` with the GRVT spot instrument delisted."""
  shared.instruments[GRVT] = spot(GRVT, status='DELISTED')
  return shared


async def test_spot_fees_are_the_tiers_spot_rates(mixed: Shared, fake: Any):
  """`spot_*_fee` is in millionths like the futures rates: tier 1 is 600 and 850."""

  async def summary() -> dict[str, Any]:
    """Tier 1, as the mainnet account reported it (2026-10-28)."""
    return {
      'tier': {
        'tier': 1,
        'futures_maker_fee': -1,
        'futures_taker_fee': 450,
        'spot_maker_fee': 600,
        'spot_taker_fee': 850,
      }
    }

  fake.trading.funding_account_summary = summary
  fees = await GrvtSpotMarket(shared=mixed, instrument=GRVT).fees()
  assert fees == Fees.symmetric(maker=Decimal('0.0006'), taker=Decimal('0.00085'))


async def test_balances_read_the_spot_wallet(mixed: Shared, fake: Any):
  """`spot_account_summary`'s rows: `balance` is the total, `available_to_transfer`
  the free part; a currency the wallet does not list is zero. Concurrent readers
  share one request."""
  calls: list[None] = []

  async def summary() -> dict[str, Any]:
    """USDT held, partly unavailable; no GRVT row."""
    calls.append(None)
    return {
      'event_time': END,
      'sub_account_id': '1',
      'total_equity': Decimal('12.5'),
      'spot_balances': [wallet_row('USDT', '12.5', '10.0')],
    }

  fake.trading.spot_account_summary = summary
  market = GrvtSpotMarket(shared=mixed, instrument=GRVT)
  balances = await market.balances()
  assert balances.base == Balance(total=Decimal(0), free=Decimal(0))
  assert balances.quote == Balance(total=Decimal('12.5'), free=Decimal('10.0'))
  exchange = GrvtSpotExchange(shared=mixed)
  assert await exchange.balance('USDT', ttl=timedelta(seconds=5)) == balances.quote
  calls.clear()
  await exchange.balance('USDT', ttl=timedelta(minutes=1))
  assert calls == []


async def test_spot_collateral_resolves_to_the_wallet(mixed: Shared, fake: Any):
  """`collateral_ids` name the pair's assets in the spot exchange, and the venue
  resolves each to that asset's balance."""

  async def summary() -> dict[str, Any]:
    """USDC and USDT held."""
    return {
      'spot_balances': [
        wallet_row('USDC', '3', '3'),
        wallet_row('USDT', '7', '6'),
      ]
    }

  fake.trading.spot_account_summary = summary
  market = GrvtSpotMarket(shared=mixed, instrument=USDC)
  assert await market.collateral_ids() == SpotCollateralIds(
    base='grvt:spot:USDC', quote='grvt:spot:USDT'
  )
  quote = await GrvtMarket(shared=mixed).collateral('spot:USDT')
  assert (quote.equity, quote.free_collateral) == (Decimal(7), Decimal(6))


async def test_spot_balances_need_an_api_key(
  make_fake: Any, make_shared: Any, make_instrument: Any
):
  """A public client raises `AuthError` before any request."""
  shared = make_shared(make_fake(api_key=False), make_instrument(BTC), spot(GRVT))
  with pytest.raises(AuthError):
    await GrvtSpotMarket(shared=shared, instrument=GRVT).balances()


async def test_orders_are_scoped_by_kind(mixed: Shared, fake: Any):
  """Open orders and cancel-all filter by `SPOT_SWAP`, keeping `GRVT_USDT_Perp`'s
  orders, which share base and quote, out."""
  requests: list[dict[str, Any]] = []

  async def scoped(**kwargs: Any) -> list[Any]:
    """Record the filters."""
    requests.append(kwargs)
    return []

  fake.trading.open_orders = scoped
  fake.trading.cancel_all_orders = scoped
  market = GrvtSpotMarket(shared=mixed, instrument=GRVT)
  assert await market.open_orders() == []
  await market.cancel_open_orders()
  assert requests == [{'kind': ['SPOT_SWAP'], 'base': ['GRVT'], 'quote': ['USDT']}] * 2


async def test_spot_orders_name_the_spot_instrument(mixed: Shared, fake: Any):
  """A spot order is the perpetual's single-leg order on the spot instrument."""
  sent: list[Any] = []

  async def create_order(order: Any) -> Any:
    """Accept."""
    sent.append(order)
    return {'order_id': '0x00'}

  fake.trading.create_order = create_order
  market = GrvtSpotMarket(shared=mixed, instrument=GRVT)
  reply = await market.place_order(
    {'type': 'POST_ONLY', 'qty': Decimal(-25), 'price': Decimal('0.25')}
  )
  leg = sent[0]['legs'][0]
  assert (leg['instrument'], leg['size'], leg['is_buying_asset']) == (
    GRVT,
    Decimal(25),
    False,
  )
  assert sent[0]['post_only'] and reply.id == sent[0]['metadata']['client_order_id']


def spot_fill(time: datetime, **changes: object) -> Fill:
  """A spot taker buy: the fee is charged in the base it delivered."""
  row: dict[str, Any] = {
    'event_time': time,
    'sub_account_id': '1',
    'instrument': GRVT,
    'is_buyer': True,
    'is_taker': True,
    'size': Decimal('100'),
    'price': Decimal('0.22'),
    'index_price': Decimal('0.22'),
    'interest_rate': Decimal(0),
    'realized_pnl': Decimal(0),
    'fee': Decimal('0.085'),
    'fee_rate': Decimal('0.085'),
    'trade_id': f'{int(time.timestamp())}-1',
    'order_id': '0x0101',
    'venue': 'ORDERBOOK',
    'is_liquidation': False,
    'client_order_id': '9759235347865617030',
    'signer': '0x0',
    'is_rpi': False,
    'builder': '0x0000000000000000000000000000000000000000',
    'builder_fee_rate': Decimal(0),
    'builder_fee': Decimal(0),
    'fee_currency': 'GRVT',
    'repayment_scenario': 'UNSPECIFIED',
  }
  return cast(Fill, {**row, **changes})


def paged(rows: Sequence[Any], requests: list[dict[str, Any]]) -> Any:
  """A `fill_history_paged` stand-in serving one page and recording its request."""

  def walk(**kwargs: Any) -> PaginatedResponse[Any, int]:
    """Record, then serve the page."""
    requests.append(kwargs)

    async def fetch(state: int) -> tuple[Sequence[Any], int | None]:
      """The only page."""
      return rows, None

    return PaginatedResponse(0, fetch)

  return walk


async def test_spot_fills_filter_by_kind_and_keep_their_fee_asset(
  mixed: Shared, fake: Any
):
  """Exchange-wide fills ask for `SPOT_SWAP` only; a buy's fee is in the base and a
  sell's in the quote, as the fill names it."""
  requests: list[dict[str, Any]] = []
  rows = [
    spot_fill(END),
    spot_fill(
      END - timedelta(hours=1),
      instrument=USDC,
      is_buyer=False,
      fee=Decimal('0.01'),
      fee_currency='USDT',
    ),
  ]
  fake.trading.fill_history_paged = paged(rows, requests)
  exchange = GrvtSpotExchange(shared=mixed)
  trades = [
    t
    async for page in exchange.trades_history(None, END - timedelta(days=1), END)
    for t in page
  ]
  assert requests[0]['kind'] == ['SPOT_SWAP'] and 'base' not in requests[0]
  assert [(cast(ExchangeTrade, t).market_id, t.qty) for t in trades] == [
    (GRVT, Decimal(100)),
    (USDC, Decimal(-100)),
  ]
  assert [t.fee and t.fee.asset for t in trades] == ['GRVT', 'USDT']
  requests.clear()
  one = [
    t
    async for page in exchange.trades_history(GRVT, END - timedelta(days=1), END)
    for t in page
  ]
  assert [t.id for t in one] == [trades[0].id]
  assert requests[0]['kind'] == ['SPOT_SWAP'] and requests[0]['base'] == ['GRVT']


async def test_spot_tickers_leave_out_perpetuals(mixed: Shared, fake: Any):
  """The spot exchange asks for its own instruments only."""
  sent: list[str] = []

  async def one(instrument: str, *, transport: str = 'http') -> dict[str, Any]:
    """An empty-book ticker."""
    sent.append(instrument)
    return {'instrument': instrument, 'last_price': Decimal('0.22')}

  fake.market.ticker = one
  tickers = await GrvtSpotExchange(shared=mixed).tickers([GRVT, BTC])
  assert list(tickers) == [GRVT] and sent == [GRVT]
  assert tickers[GRVT].last == Decimal('0.22') and tickers[GRVT].bid is None
