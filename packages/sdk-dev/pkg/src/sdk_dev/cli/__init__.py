import typer
from .test import test_app
from .docs import app as docs_app
from .support import support

app = typer.Typer()
app.add_typer(test_app, name='test')
app.add_typer(docs_app, name='docs')
app.command('support')(support)
