"""lamad — run a build123d script, get a versioned STEP + metrics + preview."""

__version__ = "0.1.0"


def main() -> None:
    """Console-script entry point: run the root `lamad` click group."""
    # Imported here so `import lamad` stays cheap for library users.
    from lamad.cli import cli

    cli()
