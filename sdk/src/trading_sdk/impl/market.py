from functools import cache
from async_lru import alru_cache
from trading_sdk import Market
from mexc_sdk import MEXC
from hyperliquid_sdk import Hyperliquid
from dydx_sdk import DYDX

@alru_cache
async def dydx_sdk(mnemonic: str | None = None):
  return await DYDX.connect(mnemonic=mnemonic)

@alru_cache
async def dydx_market(market: str, *, subaccount: int = 0, mnemonic: str | None = None):
  dydx_client = await dydx_sdk(mnemonic)
  return await dydx_client.market(market, subaccount=subaccount)

@cache
def mexc_sdk(api_key: str | None = None, api_secret: str | None = None):
  return MEXC.new(api_key, api_secret)

@alru_cache
async def mexc_spot(instrument: str, *, api_key: str | None = None, api_secret: str | None = None):
  mexc = mexc_sdk(api_key, api_secret)
  return await mexc.spot(instrument)

@alru_cache
async def mexc_perp(instrument: str, *, api_key: str | None = None, api_secret: str | None = None):
  mexc = mexc_sdk(api_key, api_secret)
  return await mexc.perp(instrument)

@cache
def hyperliquid_sdk(address: str | None = None, *, wallet: str | None = None):
  return Hyperliquid.new(address=address, wallet=wallet)

@alru_cache
async def hyperliquid_spot(address: str | None = None, *, wallet: str | None = None):
  hyperliquid = hyperliquid_sdk(address, wallet)
  return await hyperliquid.spot()

@alru_cache
async def hyperliquid_spot_market(base: str, quote: str, index: int, *, address: str | None = None, wallet: str | None = None):
  spot = await hyperliquid_spot(base, quote, address=address, wallet=wallet)
  market = spot.spot(index)
  if market.base_name != base or market.quote_name != quote:
    raise ValueError(f'Expected market {base}/{quote} at index {index}, got {market.base_name}/{market.quote_name}')
  return market


@alru_cache
async def hyperliquid_perp(dex: str | None = None, *, address: str | None = None, wallet: str | None = None):
  hyperliquid = hyperliquid_sdk(address, wallet)
  return await hyperliquid.perp(dex)

@alru_cache
async def hyperliquid_perp_market(base: str, dex: str | None = None, *, address: str | None = None, wallet: str | None = None):
  perp = await hyperliquid_perp(base, dex, address=address, wallet=wallet)
  if dex:
    base = f'{dex}:{base}'
  return perp.find(base)

@alru_cache
async def load_market(id: str):
  """Load market SDK from ID.
  
  ### Supported exchanges
  - dYdX: `dydx:<subaccount>:<base>-USD`, e.g. `dydx:0:BTC-USD`
  - MEXC Spot: `mexc:spot:<instrument>`, e.g. `mexc:spot:BTCUSDT`
  - MEXC Perp: `mexc:perp:<instrument>`, e.g. `mexc:perp:BTC_USDT`
  - Hyperliquid Spot: `hyperliquid:spot:<base>/<quote>:<index>`, e.g. `hyperliquid:spot:UBTC/USDC:142`
  - Hyperliquid Perp: `hyperliquid:perp:<dex>:<base>`, e.g. `hyperliquid:perp::BTC`
  """
  venue, rest = id.split(':', 1)
  if venue == 'dydx':
    subaccount, market = rest.split(':', 1)
    return await dydx_market(market, subaccount=int(subaccount))
  elif venue == 'mexc':
    kind, instrument = rest.split(':', 1)
    if kind == 'spot':
      return await mexc_spot(instrument)
    elif kind == 'perp':
      return await mexc_perp(instrument)
    else:
      raise ValueError(f'Invalid market kind: {kind} [{id=:}]')
  elif venue == 'hyperliquid':
    kind, rest = rest.split(':', 1)
    if kind == 'spot':
      ticker, index = rest.split(':', 1)
      base, quote = ticker.split('/')
      index = int(index)
      return await hyperliquid_spot_market(base, quote, index)
    elif kind == 'perp':
      dex, base = rest.split(':', 1)
      return await hyperliquid_perp(base=base, dex=dex)
    else:
      raise ValueError(f'Invalid market kind: {kind} [{id=:}]')
  else:
    raise ValueError(f'Invalid venue: {venue} [{id=:}]')