"""Snapshot layout and the holdings it refuses to guess, from testnet-shaped rows."""

from decimal import Decimal

import pytest
from typing_extensions import Any

from tribulnation.grvt.core import Shared
from tribulnation.grvt.report import Report
from tribulnation.sdk import AuthError
from tribulnation.sdk.reporting import Position

SUBS = ['111', '222']


def balance(currency: str, amount: str, **changes: object) -> dict[str, Any]:
  """A `SpotBalance` row."""
  return {
    'currency': currency,
    'balance': Decimal(amount),
    'index_price': Decimal(1),
    **changes,
  }


def funding(*balances: dict[str, Any], vaults: int = 0) -> dict[str, Any]:
  """`funding_account_summary`, with `vaults` vault investments."""
  return {
    'result': {
      'spot_balances': list(balances),
      'vault_investments': [{'vault_id': str(i)} for i in range(vaults)],
    },
    'tier': {},
  }


def futures(*balances: dict[str, Any], **changes: object) -> dict[str, Any]:
  """`account_summary` holding a short and a flat position row."""
  return {
    'spot_balances': list(balances),
    'positions': [
      {
        'instrument': 'BARD_USDT_Perp',
        'size': Decimal('-234.0'),
        'entry_price': Decimal('0.1072'),
      },
      {
        'instrument': 'BTC_USDT_Perp',
        'size': Decimal('0'),
        'entry_price': Decimal('0'),
      },
    ],
    **changes,
  }


def report(fake: Any, shared: Shared, **rows: Any) -> Report:
  """A report over `fake`, serving `rows` by endpoint name (sub-account rows by id)."""

  async def funding_account_summary() -> Any:
    """The funding account."""
    return rows['funding']

  async def sub_accounts() -> Any:
    """Two sub-accounts."""
    return {'sub_account_ids': SUBS}

  async def account_summary(id: str) -> Any:
    """One sub-account's futures wallet."""
    return rows['futures'][id]

  async def spot_account_summary(id: str) -> Any:
    """One sub-account's spot wallet."""
    return {'spot_balances': rows['spot'][id]}

  fake.trading.funding_account_summary = funding_account_summary
  fake.trading.sub_accounts = sub_accounts
  fake.trading.account_summary = account_summary
  fake.trading.spot_account_summary = spot_account_summary
  return Report(shared=shared)


async def test_snapshot_layout(fake: Any, shared: Shared):
  """`funding`, then `<id>:futures` (cash and open positions) and `<id>:spot` per
  sub-account; zero balances and flat positions are left out."""
  record = await report(
    fake,
    shared,
    funding=funding(balance('USDT', '2000.5'), balance('GRVT', '0')),
    futures={
      '111': futures(balance('USDT', '18000.25'), balance('USDC', '19.1')),
      '222': futures(),
    },
    spot={'111': [balance('USDT', '0')], '222': [balance('ETH', '0.5')]},
  ).snapshot()
  states = {s.subaccount: s for s in record.snapshot.subaccounts}
  assert list(states) == [
    'funding',
    '111:futures',
    '111:spot',
    '222:futures',
    '222:spot',
  ]
  assert states['funding'].balances == {'USDT': Decimal('2000.5')}
  assert states['111:futures'].balances == {
    'USDT': Decimal('18000.25'),
    'USDC': Decimal('19.1'),
  }
  assert states['111:futures'].positions == {
    'BARD_USDT_Perp': Position(size=Decimal('-234.0'), avg_price=Decimal('0.1072'))
  }
  assert states['111:spot'].balances == {} and states['111:spot'].positions == {}
  assert states['222:spot'].balances == {'ETH': Decimal('0.5')}
  assert record.provenance == {
    'source': 'api',
    'service': 'grvt',
    'id': record.snapshot.time.isoformat(),
  }


@pytest.mark.parametrize(
  'rows',
  [
    {'funding': funding(vaults=1)},
    {'funding': funding(balance('USDT', '1', borrowed_amount=Decimal('0.5')))},
    {
      'futures': {
        '111': futures(balance('USDT', '1', borrowed_amount=Decimal('2'))),
        '222': futures(),
      }
    },
    {'futures': {'111': futures(is_vault=True), '222': futures()}},
  ],
  ids=['vault investment', 'funding borrow', 'futures borrow', 'vault sub-account'],
)
async def test_unverified_holdings_raise(
  fake: Any, shared: Shared, rows: dict[str, Any]
):
  """Vault investments, borrowed balances and vault sub-accounts are not guessed."""
  defaults: dict[str, Any] = {
    'funding': funding(),
    'futures': {'111': futures(), '222': futures()},
    'spot': {'111': [], '222': []},
  }
  with pytest.raises(NotImplementedError):
    await report(fake, shared, **{**defaults, **rows}).snapshot()


async def test_a_zero_borrow_is_no_borrow(fake: Any, shared: Shared):
  """`borrowed_amount` `0` (multi-asset mode always sends it) is held as is."""
  record = await report(
    fake,
    shared,
    funding=funding(),
    futures={
      '111': futures(balance('USDT', '5', borrowed_amount=Decimal('0'))),
      '222': futures(),
    },
    spot={'111': [], '222': []},
  ).snapshot()
  assert record.snapshot.balances == {'USDT': Decimal('5')}


async def test_history_is_not_supported(shared: Shared):
  """The Report history surface is being retired."""
  with pytest.raises(NotImplementedError):
    await anext(aiter(Report(shared=shared).history()))


async def test_snapshots_need_an_api_key(make_fake: Any, make_shared: Any):
  """A public client raises `AuthError` before any request."""
  with pytest.raises(AuthError):
    await Report(shared=make_shared(make_fake(api_key=False))).snapshot()


def test_report_reads_no_environment(monkeypatch: pytest.MonkeyPatch):
  """The key is passed explicitly; the testnet report names its venue."""
  monkeypatch.setenv('GRVT_TESTNET_API_KEY', 'from-the-environment')
  report = Report.new(api_key='explicit', env='testnet')
  assert report.shared.venue_id == 'grvt_testnet'
  session = report.shared.client.session
  assert session is not None and session.api_key == 'explicit'
