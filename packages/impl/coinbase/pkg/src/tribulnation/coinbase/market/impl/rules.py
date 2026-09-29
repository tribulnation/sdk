"""Trading rules for one Advanced Trade product."""

from tribulnation.sdk.market import Fees, Rules

from typed_coinbase.schemas import Product

from tribulnation.coinbase.core import wrap_exceptions
from .mixin import MarketMixin


def base_asset(product: Product) -> str:
  """The product's base asset.

  Perpetuals leave `base_display_symbol`/`base_currency_id` empty (verified live); the
  underlying asset code only shows up under `future_product_details.contract_code`.
  """
  if product['base_display_symbol']:
    return product['base_display_symbol']
  details = product.get('future_product_details')
  if details is None:
    return ''
  return details.get('contract_code') or ''


@wrap_exceptions
async def rules(self: MarketMixin, *, refetch: bool = False) -> Rules:
  """Fetch product rules without reading the account's fee tier.

  Args:
    refetch: Fetch even when the product is already cached.
  """
  product = await self.shared.load_product(self.product_id, refetch=refetch)
  quote = product['quote_display_symbol']
  return Rules(
    fee_asset=quote,
    tick_size=product['quote_increment'],
    step_size=product['base_increment'],
    fixed_min_qty=product['base_min_size'],
    min_value=product['quote_min_size'],
    max_qty=product['base_max_size'],
    fees=None,
    api=not product['trading_disabled'],
    details=product,
  )


async def fees(self: MarketMixin) -> Fees:
  """Unsupported: spot fee tiers do not resolve product-specific stablepair pricing."""
  raise NotImplementedError(
    'Coinbase spot fee tiers do not resolve product-specific stablepair pricing'
  )
