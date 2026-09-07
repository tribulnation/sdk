"""Trading rules for one Advanced Trade product."""

from decimal import Decimal

from tribulnation.sdk.market import Rules

from typed_coinbase.schemas import Product

from tribulnation.coinbase.core import FeeScope, wrap_exceptions
from .mixin import MarketMixin


def base_asset(product: Product) -> str:
  """The product's base asset.

  Perpetuals leave `base_display_symbol`/`base_currency_id` empty (verified live); the
  underlying asset code only shows up under `future_product_details.contract_code`.
  """
  if product['base_display_symbol']:
    return product['base_display_symbol']
  details = product.get('future_product_details') or {}
  return details.get('contract_code') or ''


@wrap_exceptions
async def rules(
  self: MarketMixin, scope: FeeScope, /, *, refetch: bool = False
) -> Rules:
  """Fetch the product's trading rules and the account's current fee tier.

  Args:
    scope: Which fee schedule prices this product.
    refetch: Fetch even when the product and fee tier are already cached.
  """
  product = await self.shared.load_product(self.product_id, refetch=refetch)
  tier = await self.shared.load_fee_tier(scope, refetch=refetch)
  quote = product['quote_display_symbol']
  return Rules(
    base=base_asset(product),
    quote=quote,
    fee_asset=quote,
    tick_size=product['quote_increment'],
    step_size=product['base_increment'],
    fixed_min_qty=product['base_min_size'],
    min_value=product['quote_min_size'],
    max_qty=product['base_max_size'],
    maker_fee=tier.get('maker_fee_rate') or Decimal(0),
    taker_fee=tier.get('taker_fee_rate') or Decimal(0),
    api=not product['trading_disabled'],
    details=product,
  )
