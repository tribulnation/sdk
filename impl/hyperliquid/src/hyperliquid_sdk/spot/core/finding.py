from hyperliquid.info.spot.spot_meta import SpotMetaResponse

def match_token(name: str, spot_meta: SpotMetaResponse):
  for token in spot_meta['tokens']:
    if name in token['name']:
      yield token['index']
  
def match_spot(base: str, quote: str, spot_meta: SpotMetaResponse):
  bases = set(match_token(base, spot_meta))
  quotes = set(match_token(quote, spot_meta))
  if bases and quotes:
    for idx, asset in enumerate(spot_meta['universe']):
      base_idx, quote_idx = asset['tokens']
      if base_idx in bases and quote_idx in quotes:
        yield idx

def find_token(name: str, spot_meta: SpotMetaResponse):
  finds: list[int] = []
  for token in spot_meta['tokens']:
    if token['name'] == name:
      finds.append(token['index'])
  if not finds:
    raise ValueError(f'Token {name} not found')
  if len(finds) > 1:
    raise ValueError(f'Multiple tokens found named "{name}"')
  return finds[0]

def find_spot(base: str, quote: str, spot_meta: SpotMetaResponse):
  base_token = find_token(base, spot_meta)
  quote_token = find_token(quote, spot_meta)
  finds: list[int] = []
  for idx, asset in enumerate(spot_meta['universe']):
    base_idx, quote_idx = asset['tokens']
    if base_idx == base_token and quote_idx == quote_token:
      finds.append(idx)
  if not finds:
    raise ValueError(f'Spot {base}/{quote} not found')
  if len(finds) > 1:
    raise ValueError(f'Multiple spots found for {base}/{quote}')
  return finds[0]

