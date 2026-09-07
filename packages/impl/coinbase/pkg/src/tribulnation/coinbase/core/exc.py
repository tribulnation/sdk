"""Translation of `typed_coinbase` errors into the SDK's exception hierarchy."""

from tribulnation.sdk.core import exception_wrapper

wrap_exceptions = exception_wrapper()
"""Re-raise `typed_core` exceptions as their `tribulnation.sdk.core.exc` equivalents.

`typed_coinbase.core.exc` re-exports `typed_core`'s hierarchy unchanged, so the SDK's
default `translate_exception` already covers every error the client raises.
"""
