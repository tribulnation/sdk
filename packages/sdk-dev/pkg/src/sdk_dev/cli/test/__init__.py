import typer
from .earn import test_earn
from .wallet import test_wallet
from .bitget import test_bitget

test_app = typer.Typer()
test_app.command('earn')(test_earn)
test_app.command('wallet')(test_wallet)
test_app.command('bitget')(test_bitget)
