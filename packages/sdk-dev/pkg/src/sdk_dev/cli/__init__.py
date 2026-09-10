import typer
from .test import test_app
from .docs import app as docs_app
from .poc import app as poc_app
from .catalogue import app as catalogue_app
from .support import support
from .results import app as results_app

app = typer.Typer()
app.add_typer(test_app, name='test')
app.add_typer(docs_app, name='docs')
app.add_typer(poc_app, name='poc')
app.add_typer(catalogue_app, name='catalogue')
app.add_typer(results_app, name='results')
app.command('support')(support)
