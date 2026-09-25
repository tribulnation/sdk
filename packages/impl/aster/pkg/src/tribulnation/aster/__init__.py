"""Load Aster SDK surfaces independently when an application requests them."""

import lazy_loader as lazy

__getattr__, __dir__, __all__ = lazy.attach_stub(__name__, __file__)
