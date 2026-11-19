"""Spot tickers take each pair's 24h volume from its own asset context."""

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from pydantic import TypeAdapter
from typing_extensions import Any, cast

from typed_hyperliquid.info.spot_meta_and_asset_ctxs import (
  SpotAssetCtx,
  SpotMeta,
  SpotMetaAndAssetCtxsResponse,
)

from tribulnation.sdk.market import Settings, Ticker
from tribulnation.hyperliquid.market import spot_exchange

FIXTURE = Path(__file__).parent / 'fixtures' / 'spot_meta_and_asset_ctxs.json'
NO_DEPTH: Settings = {'hyperliquid': {'tickers_fetch_depth': False}}


def recorded() -> tuple[SpotMeta, list[SpotAssetCtx]]:
  """Validate the recorded (trimmed) `spotMetaAndAssetCtxs` answer of 2026-11-19."""
  raw = json.loads(FIXTURE.read_text())['response']
  return TypeAdapter(SpotMetaAndAssetCtxsResponse).validate_python(raw)


async def tickers(
  spot_meta: SpotMeta, contexts: list[SpotAssetCtx]
) -> dict[str, Ticker]:
  """Run the spot exchange's `tickers` over one answer, without order books."""

  class Info:
    async def spot_meta_and_asset_ctxs(self):
      return spot_meta, contexts

  target = cast(
    Any,
    SimpleNamespace(shared=SimpleNamespace(client=SimpleNamespace(info=Info()))),
  )
  result = await spot_exchange.SpotExchange.tickers(target, settings=NO_DEPTH)
  return dict(result)


def volumes(result: dict[str, Ticker]) -> dict[str, tuple[Any, Any]]:
  """Each market's (quote, base) 24h volume."""
  return {m: (t.quote_volume_24h, t.base_volume_24h) for m, t in result.items()}


RECORDED_VOLUMES = {
  'PURR/USDC:0': (Decimal('1215315.7214920004'), Decimal('15023135.0')),
  'FRIED/USDC:70': (Decimal('0.0'), Decimal('0.0')),
  'NOCEX/USDC:72': (Decimal('611.0936894'), Decimal('749.13')),
  'HYPE/USDC:107': (Decimal('40156103.4671499133'), Decimal('596129.1799999999')),
  'HWTR/USDC:140': (Decimal('18.62263956'), Decimal('665094.27')),
  'UBTC/USDC:142': (Decimal('38633694.5591400042'), Decimal('613.29495')),
  'UETH/USDC:151': (Decimal('8057440.4427700024'), Decimal('4532.3074')),
}


async def test_recorded_answer_volumes_are_each_pairs_own() -> None:
  """Join the recorded answer by coin, past the gap at index 71."""
  spot_meta, contexts = recorded()
  # The recording reproduces the venue's misalignment: by position, @142 meets @140.
  pairs = {p['index']: p for p in spot_meta['universe']}
  assert contexts[spot_meta['universe'].index(pairs[142])].get('coin') == '@140'

  result = await tickers(spot_meta, contexts)

  assert volumes(result) == RECORDED_VOLUMES


async def test_order_of_universe_and_contexts_is_irrelevant() -> None:
  """Give the same volumes when universe and contexts arrive in other orders."""
  spot_meta, contexts = recorded()
  shuffled: SpotMeta = {**spot_meta, 'universe': spot_meta['universe'][::-1]}
  rotated = contexts[3:] + contexts[:3]

  result = await tickers(shuffled, rotated)

  assert volumes(result) == RECORDED_VOLUMES


async def test_pair_without_context_has_no_volume() -> None:
  """Leave a pair's volume unset when the answer has no context for it."""
  spot_meta, contexts = recorded()
  without_ubtc = [c for c in contexts if c.get('coin') != '@142']

  result = await tickers(spot_meta, without_ubtc)

  assert volumes(result)['UBTC/USDC:142'] == (None, None)
  assert {m: v for m, v in volumes(result).items() if m != 'UBTC/USDC:142'} == {
    m: v for m, v in RECORDED_VOLUMES.items() if m != 'UBTC/USDC:142'
  }


def context(volume: str, coin: str | None = None) -> SpotAssetCtx:
  """One spot context with `volume` as both daily volumes."""
  ctx: SpotAssetCtx = {
    'markPx': Decimal('1'),
    'midPx': Decimal('1'),
    'prevDayPx': Decimal('1'),
    'dayNtlVlm': Decimal(volume),
    'dayBaseVlm': Decimal(volume),
  }
  if coin is not None:
    ctx['coin'] = coin
  return ctx


def gapped_universe(*indices: int) -> SpotMeta:
  """Spot pairs at positive `indices`, each token `COIN-<index>` against `USD` (token 0)."""
  return {
    'tokens': [
      {
        'index': i,
        'name': 'USD' if i == 0 else f'COIN-{i}',
        'szDecimals': 2,
        'weiDecimals': 8,
        'tokenId': f'0x{i:032x}',
        'isCanonical': True,
        'evmContract': None,
        'fullName': None,
      }
      for i in (0, *indices)
    ],
    'universe': [
      {'index': i, 'tokens': (i, 0), 'name': f'@{i}', 'isCanonical': False}
      for i in indices
    ],
  }


async def test_contexts_without_coin_fall_back_to_the_pairs_index() -> None:
  """Use the context at the pair's spot index when contexts carry no `coin`."""
  spot_meta = gapped_universe(1, 2, 5)
  contexts = [context(str(i)) for i in range(6)]

  result = await tickers(spot_meta, contexts)

  assert volumes(result) == {
    'COIN-1/USD:1': (Decimal('1'), Decimal('1')),
    'COIN-2/USD:2': (Decimal('2'), Decimal('2')),
    'COIN-5/USD:5': (Decimal('5'), Decimal('5')),
  }


async def test_index_fallback_never_takes_another_coins_context() -> None:
  """Ignore the context at the pair's index when it names another coin."""
  spot_meta = gapped_universe(1, 2, 5)
  contexts = [
    context('0', '@0'),
    context('1', '@1'),
    context('3', '@3'),
    context('2', '@2'),
    context('4', '@4'),
  ]

  result = await tickers(spot_meta, contexts)

  assert volumes(result) == {
    'COIN-1/USD:1': (Decimal('1'), Decimal('1')),
    'COIN-2/USD:2': (Decimal('2'), Decimal('2')),
    'COIN-5/USD:5': (None, None),
  }
