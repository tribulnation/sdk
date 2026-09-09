import typer
from .earn import test_earn
from .wallet import test_wallet
from .market import test_market
from .bitget import test_bitget
from .report import test_report

test_app = typer.Typer()
test_app.command('earn')(test_earn)
test_app.command('wallet')(test_wallet)
test_app.command('market')(test_market)
test_app.command('bitget')(test_bitget)
test_app.command('report')(test_report)
