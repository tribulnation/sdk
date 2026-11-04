"""Wallet and earn reads serve UTA accounts as well as Classic ones."""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import AsyncMock
from typing_extensions import cast

import pytest
from typed_bitget import Bitget
from typed_bitget.classic.earn.savings.products import (
  Products as SavingsProducts,
  SavingsProduct,
)
from typed_bitget.classic.spot.coins import Coins, SpotCoin
from typed_bitget.uta.earn.elite.products import EliteProduct, Products as EliteProducts

from tribulnation.bitget.earn import Earn
from tribulnation.bitget.wallet import Wallet
from tribulnation.sdk.earn.instruments import Instrument

COINS: list[SpotCoin] = cast(
  list[SpotCoin],
  [
    {
      'coinId': '1',
      'coin': 'USDT',
      'transfer': True,
      'chains': [
        {
          'chain': 'TRC20',
          'rechargeable': True,
          'withdrawable': True,
          'withdrawFee': '1',
          'contractAddress': 'TR7',
          'depositConfirm': '20',
        },
      ],
    },
  ],
)

ELITE: list[EliteProduct] = [
  {
    'productId': 'p1',
    'coin': 'BGUSD',
    'minApr': Decimal('4.00'),
    'maxApr': Decimal('5.93'),
    'subscriptionCoinList': [
      {
        'subscriptionCoin': 'USDC',
        'precision': '2',
        'feeRate': Decimal(0),
        'exchangeRate': Decimal(1),
        'minAmount': '10',
        'remainQuota': '1000',
      },
    ],
    'sellOut': 'NO',
  },
  {
    'productId': 'p2',
    'coin': 'BGBTC',
    'minApr': Decimal('0.80'),
    'maxApr': Decimal('0.80'),
    'subscriptionCoinList': [],
    'sellOut': 'YES',
  },
]


@pytest.mark.parametrize('uta', [True, False])
async def test_wallet_methods_read_the_public_coin_list(
  uta: bool, monkeypatch: pytest.MonkeyPatch
):
  """Deposit and withdrawal networks come from the public coin list in either mode."""
  monkeypatch.setattr(Coins, 'coins', AsyncMock(return_value=COINS))
  wallet = Wallet(client=Bitget.new(public=True), uta=uta)
  [deposit] = await wallet.deposit_methods()
  [withdrawal] = await wallet.withdrawal_methods()
  assert (deposit.asset, deposit.network, deposit.min_confirmations) == (
    'USDT',
    'TRC20',
    20,
  )
  assert withdrawal.fee is not None
  assert (withdrawal.asset, withdrawal.network, withdrawal.fee.amount) == (
    'USDT',
    'TRC20',
    Decimal(1),
  )


async def test_uta_earn_lists_elite_products(monkeypatch: pytest.MonkeyPatch):
  """A UTA account lists open Elite products, never the Classic savings API."""
  monkeypatch.setattr(EliteProducts, 'products', AsyncMock(return_value=ELITE))
  monkeypatch.setattr(
    SavingsProducts, 'products', AsyncMock(side_effect=AssertionError('Classic API'))
  )
  earn = Earn(client=Bitget.new(public=True), uta=True)
  assert await earn.instruments() == [
    Instrument(
      tags=['staking'],
      asset='USDC',
      yield_asset='BGUSD',
      apr=Decimal('0.04'),
      min_qty=Decimal(10),
      max_qty=Decimal(1000),
      id='p1',
    )
  ]
  assert await earn.instruments(assets=['BTC']) == []


async def test_classic_earn_lists_savings_products(monkeypatch: pytest.MonkeyPatch):
  """A Classic account keeps reading the savings products."""
  savings = cast(
    list[SavingsProduct],
    [
      {
        'productId': 's1',
        'coin': 'USDT',
        'periodType': 'fixed',
        'period': '7',
        'status': 'in_progress',
        'apyList': [{'currentApy': '5', 'minStepVal': '1', 'maxStepVal': '100'}],
      }
    ],
  )
  monkeypatch.setattr(SavingsProducts, 'products', AsyncMock(return_value=savings))
  monkeypatch.setattr(
    EliteProducts, 'products', AsyncMock(side_effect=AssertionError('UTA API'))
  )
  earn = Earn(client=Bitget.new(public=True), uta=False)
  [instrument] = await earn.instruments()
  assert (instrument.asset, instrument.apr, instrument.duration) == (
    'USDT',
    Decimal('0.05'),
    timedelta(days=7),
  )
