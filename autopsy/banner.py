"""ASCII art banner for flaky-test-autopsy."""


def print_banner() -> None:
    """Print the autopsy ASCII art banner to stderr."""
    import os
    import sys

    if not sys.stderr.isatty() or os.environ.get("CI") or os.environ.get("AUTOPSY_NO_BANNER"):
        return

    import pyfiglet
    from rich.console import Console

    console = Console(stderr=True)
    art = pyfiglet.figlet_format("AUTOPSY", font="big")
    console.print(f"[bold red]{art}[/bold red]", end="")
    console.print(
        "[dim red]  flaky test detection · root cause analysis · fix suggestions[/dim red]\n"
    )
