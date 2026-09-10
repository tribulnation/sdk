"""Shared implementations behind Coinbase's spot and perpetual market surfaces."""

from .account import (
  brokerage_account,
  collateral,
  perp_collateral,
  perp_position,
  position,
)
from .candles import CANDLE_INTERVALS, candles
from .catalogue import filtered, list_products, parse_perp_stats, tickers
from .depth import depth, depth_stream
from .funding import funding_rates, index, next_funding
from .mixin import (
  INTX_EXCHANGE_ID,
  SPOT_EXCHANGE_ID,
  VENUE_ID,
  ExchangeMixin,
  MarketMixin,
)
from .numbers import parse_optional_decimal
from .orders import cancel_order, open_orders, place_order
from .rules import fees, rules
from .trades import trades_history, trades_stream
