# Contributing

Thanks for helping. Bug reports, ideas and pull requests are all welcome.

## Reporting a problem

Open an issue and include the output of `kubepick --version`, your OS, and which cloud is involved. Remove account names,
ids and URLs you don't want to share before pasting any output.

## Development

```shell
git clone https://github.com/iammathh/kubepick && cd kubepick
uv run --extra test python -m pytest      # tests
uv run --with ruff ruff check .           # lint
uv tool install --editable .              # try your changes as the real `kubepick` command
```

The tests never touch your real configuration or your clouds: each one runs with its own `HOME` and `XDG_*` folders, and the
calls to the cloud CLIs are replaced by fakes.

## Pull requests

- Keep a change focused, and add or update tests for it.
- `pytest` and `ruff check` must pass, CI runs both on Linux and macOS.
- Add a line to [CHANGELOG.md](CHANGELOG.md) under "Unreleased".
- The code is indented with tabs, like the rest of the project.
- Anything specific to one setup (URLs, tenant ids, role names, naming rules) goes in the configuration file, never in
  the code or the examples.

## Layout

| File | Responsibility |
| --- | --- |
| `src/kubepick/cli.py` | commands and argument parsing |
| `src/kubepick/scanners.py` | finding clusters in AWS, Azure and GCP |
| `src/kubepick/kubeconfig.py` | reading and writing the kubeconfig |
| `src/kubepick/names.py` | proposing context names |
| `src/kubepick/config.py` | configuration file and login commands |
