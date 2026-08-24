import typer
from .test import test_app

app = typer.Typer()
app.add_typer(test_app, name='test')
