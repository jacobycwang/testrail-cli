import typer

from tr import api_cmd, auth, docs_cmd
from tr.output import set_json

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Thin TestRail CLI for coding agents. stdout is JSON; hints go to stderr.",
)


@app.callback()
def root(
    json_output: bool = typer.Option(
        False, "--json", help="Force JSON output (already the default)"
    ),
) -> None:
    set_json(json_output)


app.add_typer(auth.app, name="auth")
app.command("api")(api_cmd.api)
app.command("docs")(docs_cmd.docs)

# Sub-apps registered by other modules: sync, search, scope, case, run
# Each owner adds one import above and one app.add_typer(...)/app.command(...) line here.


def main() -> None:
    app()


if __name__ == "__main__":
    main()
