"""Bit2Me exception translation, built on `typed_core`'s shared exception hierarchy.

`typed_bit2me`'s HTTP transport and response validation already translate
`httpx`/`pydantic` errors into `typed_core.exceptions` before they reach the SDK
implementation, so the default `exception_wrapper` translation is all this needs.
"""

from tribulnation.sdk.core import exception_wrapper

wrap_exceptions = exception_wrapper()
