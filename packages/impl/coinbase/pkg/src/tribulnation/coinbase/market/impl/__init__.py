"""Shared implementations behind Coinbase's spot market surface."""

from .account import brokerage_account, collateral, position
from .candles import CANDLE_INTERVALS, candles
from .catalogue import filtered, list_products, tickers
from .depth import depth, depth_stream
from .mixin import SPOT_EXCHANGE_ID, VENUE_ID, ExchangeMixin, MarketMixin
from .numbers import parse_optional_decimal
from .orders import cancel_order, open_orders, place_order
from .rules import fees, rules
from .trades import trades_history, trades_stream
