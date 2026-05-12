"""Click entrypoint and group registration."""

import click

from cove import __version__
from cove.creds import creds
from cove.project import project


@click.group()
@click.version_option(version=__version__, prog_name="cove")
def app():
    """Cove management CLI."""


app.add_command(creds)
app.add_command(project)


@app.command()
def version():
    """Print the CLI version."""
    click.echo(f"cove {__version__}")
