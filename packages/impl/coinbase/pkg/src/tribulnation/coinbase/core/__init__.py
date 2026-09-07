"""Shared plumbing behind every Coinbase SDK surface."""

from .exc import wrap_exceptions
from .mixin import FeeScope, Mixin, Shared
from .streams import book_stream, user_trades_stream
