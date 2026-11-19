"""A fake `typed_evedex` client: records calls and answers from canned rows."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from typing_extensions import Any, Sequence, cast

import pytest
from typed_evedex import BadRequest as ClientBadRequest, Evedex

from tribulnation.evedex.core import Shared

T0 = datetime(2026, 11, 19, 12, 16, 35, 603000, tzinfo=timezone.utc)
BUY_ID = '00483:ff96987b2e82e00d336ad19b3f'
SELL_ID = '00483:8ea0f9fa29101942ff321425ec'


def instrument(**overrides: Any) -> dict[str, Any]:
  """XRPUSD's record, with the fields the adapter reads."""
  row: dict[str, Any] = {
    'name': 'XRPUSD',
    'from': {'avgLastPrice': Decimal('0.98911278')},
    'lotSize': Decimal('1'),
    'priceIncrement': Decimal('0.0001'),
    'quantityIncrement': Decimal('0.1'),
    'minQuantity': Decimal('0.1'),
    'maxQuantity': Decimal('12612529'),
    'minVolume': Decimal('5'),
    'minPrice': Decimal('0.1973'),
    'maxPrice': Decimal('1.9735'),
    'markPriceLimit': Decimal('0.3'),
    'maxLeverage': 100,
    'leverageLimit': {'1': Decimal('12442000'), '2': Decimal('7398000')},
    'type': 'perpetual-futures',
    'visibility': 'all',
    'trading': 'all',
    'marketState': 'OPEN',
    'matcherState': 'active',
    'fees': {'maker': Decimal('0.00015'), 'taker': Decimal('0.00045')},
    'markPrice': Decimal('0.98877989'),
    'lastPrice': Decimal('0.9887'),
    'volume': Decimal('13992156'),
    'volumeBase': Decimal('13644163.55406'),
    'openInterest': Decimal('30331317.1'),
    'fundingRate': Decimal('-0.00013691'),
    'fundingRateInterval': 8,
  }
  return row | overrides


def order(**overrides: Any) -> dict[str, Any]:
  """A filled XRPUSD limit sell, as `orders.get`/`orders.list` send it."""
  row: dict[str, Any] = {
    'id': SELL_ID,
    'instrument': 'XRPUSD',
    'type': 'LIMIT',
    'side': 'SELL',
    'status': 'FILLED',
    'quantity': Decimal('6'),
    'unFilledQuantity': Decimal('0'),
    'limitPrice': Decimal('0.9429'),
  }
  return row | overrides


def position(**overrides: Any) -> dict[str, Any]:
  """XRPUSD's position record."""
  row: dict[str, Any] = {
    'instrument': 'XRPUSD',
    'side': 'BUY',
    'quantity': Decimal('0'),
    'avgPrice': Decimal('0.9877'),
    'leverage': 1,
    'maintenanceMargin': Decimal('0'),
    'unRealizedPnL': Decimal('0'),
  }
  return row | overrides


def refusal(status: int, label: str) -> ClientBadRequest:
  """The exception `typed_evedex` raises for an EVEDEX error body."""
  return ClientBadRequest(status, {'tagId': 't', 'error': '', 'label': label})


class Pages:
  """A typed pager over canned pages, iterated without middleware."""

  def __init__(self, pages: Sequence[Sequence[Any]]):
    self.pages = pages

  def via(self, call: Any) -> Any:
    """The pages, one at a time."""

    async def pages():
      for page in self.pages:
        yield page

    return pages()


@dataclass
class Fake:
  """Every client call the adapter makes, recorded and answered from fields."""

  calls: list[tuple[str, Any]] = field(default_factory=list[tuple[str, Any]])
  error: Exception | None = None
  instruments: list[dict[str, Any]] = field(default_factory=lambda: [instrument()])
  orders: list[dict[str, Any]] = field(default_factory=lambda: [order()])
  opened: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
  positions: list[dict[str, Any]] = field(default_factory=lambda: [position()])
  fill_pages: list[list[dict[str, Any]]] = field(
    default_factory=list[list[dict[str, Any]]]
  )
  order_fills: dict[str, list[dict[str, Any]]] = field(
    default_factory=dict[str, list[dict[str, Any]]]
  )
  candle_pages: list[list[tuple[Any, ...]]] = field(
    default_factory=list[list[tuple[Any, ...]]]
  )
  placed: dict[str, Any] = field(
    default_factory=lambda: order(id=BUY_ID, side='BUY', status='NEW')
  )

  def raise_error(self):
    """Raise the configured error, once."""
    if self.error is not None:
      error, self.error = self.error, None
      raise error

  def client(self, *, wallet: bool = True, keyed: bool = True) -> Evedex:
    """A client namespace over this fake."""
    fake = self

    async def instruments(fields: Any = None) -> Any:
      return fake.instruments

    async def instrument_(name: str) -> Any:
      return next(r for r in fake.instruments if r['name'] == name)

    async def order_book(*, instrument: str, market_level: Any = None) -> Any:
      fake.calls.append(('order_book', (instrument, market_level)))
      level = {'price': Decimal('0.9885'), 'quantity': Decimal('19488.5')}
      return {'t': T0, 'bids': [level], 'asks': [level | {'price': Decimal('0.9887')}]}

    async def place_limit(**kwargs: Any) -> Any:
      fake.calls.append(('place_limit', kwargs))
      fake.raise_error()
      return fake.placed

    async def cancel(order_id: str) -> Any:
      fake.calls.append(('cancel', order_id))
      fake.raise_error()
      return {}

    async def cancel_by_instrument(instrument: str) -> Any:
      fake.calls.append(('cancel_by_instrument', instrument))
      return {}

    async def get(order_id: str) -> Any:
      fake.calls.append(('get', order_id))
      fake.raise_error()
      return next(o for o in fake.orders if o['id'] == order_id)

    async def opened() -> Any:
      return fake.opened

    def list_paged(*, id: list[str], limit: int) -> Any:
      fake.calls.append(('orders.list', id))
      return Pages([[o for o in fake.orders if o['id'] in id]])

    async def order_fills(order_id: str) -> Any:
      fake.calls.append(('orders.fills', order_id))
      return fake.order_fills.get(order_id, [])

    def fills_paged(instrument: Any, *, after: Any, before: Any, limit: Any) -> Any:
      fake.calls.append(('fills', (instrument, after, before)))
      return Pages(fake.fill_pages)

    async def positions_list() -> Any:
      return {'list': fake.positions}

    async def set_leverage(instrument: str, *, leverage: int) -> Any:
      fake.calls.append(('set_leverage', (instrument, leverage)))
      return {}

    def candles_paged(**kwargs: Any) -> Any:
      fake.calls.append(('candles', kwargs))
      return Pages(fake.candle_pages)

    credentials = (
      SimpleNamespace(account=object() if wallet else None) if keyed else None
    )
    client = SimpleNamespace(
      credentials=credentials,
      exchange=SimpleNamespace(
        market=SimpleNamespace(
          instruments=instruments, instrument=instrument_, order_book=order_book
        ),
        orders=SimpleNamespace(
          place_limit=place_limit,
          cancel=cancel,
          cancel_by_instrument=cancel_by_instrument,
          get=get,
          opened=opened,
          list_paged=list_paged,
          fills=order_fills,
        ),
        positions=SimpleNamespace(list=positions_list, set_leverage=set_leverage),
        fills_paged=fills_paged,
      ),
      market_data=SimpleNamespace(candles_paged=candles_paged),
    )
    return cast(Evedex, client)

  def shared(self, *, wallet: bool = True, keyed: bool = True) -> Shared:
    """A `Shared` over this fake."""
    return Shared(client=self.client(wallet=wallet, keyed=keyed))


@pytest.fixture
def fake() -> Fake:
  """A fresh fake client."""
  return Fake()
