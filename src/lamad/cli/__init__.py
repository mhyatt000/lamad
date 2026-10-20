"""Root `lamad` command group and the stdout/stderr contract shared by every command.

Every command emits exactly one JSON object on stdout. Progress notes and
errors go to stderr. A failure exits non-zero after emitting a JSON error.
"""

import json
import sys

import click


def emit(payload, code=0):
    """One JSON object on stdout. Progress and errors go to stderr."""
    click.echo(json.dumps(payload, indent=2))
    if code:
        sys.exit(code)


def fail(command, message, **extra):
    emit({"command": command, "status": "error", "message": message, **extra}, code=1)


def note(msg):
    click.echo(f"[lamad] {msg}", err=True)


def parse_params(raw_params, command):
    """Turn repeated `--param K=V` values into a dict of literal overrides.

    Values are parsed as JSON when possible (numbers, bools, quoted strings)
    and kept as bare strings otherwise.
    """
    overrides = {}
    for raw in raw_params:
        if "=" not in raw:
            fail(command, f"Bad --param {raw!r}. Expected KEY=VALUE.")
        k, v = raw.split("=", 1)
        try:
            overrides[k] = json.loads(v)
        except json.JSONDecodeError:
            overrides[k] = v
    return overrides


class HelpGroup(click.Group):
    """A group that prints its help and exits 0 when invoked bare.

    click >= 8.2 treats a bare group invocation as a usage error (exit 2);
    `lamad`, `lamad versions`, and `lamad re` should list subcommands instead.
    """

    def parse_args(self, ctx, args):
        if not args and not ctx.resilient_parsing:
            click.echo(ctx.get_help())
            ctx.exit(0)
        return super().parse_args(ctx, args)


@click.group(cls=HelpGroup)
@click.version_option(package_name="lamad")
def cli():
    """CAD toolkit. Write build123d scripts, get STEP files and pictures."""


# Subcommand modules import emit/fail/note from this module, so they are
# registered after the helpers above exist.
from lamad.cli import geom, project, reverse, web  # noqa: E402

cli.add_command(project.init)
cli.add_command(project.run)
cli.add_command(project.versions)
cli.add_command(geom.view)
cli.add_command(web.web)
cli.add_command(geom.measure)
cli.add_command(geom.export)
cli.add_command(reverse.re)
