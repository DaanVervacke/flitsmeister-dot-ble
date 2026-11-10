# Contributing to flitsmeister-dot-ble

Thanks for your interest in contributing. This project is an async Python
library for the Flitsmeister DOT over Bluetooth Low Energy, targeting
Python >= 3.14.

## Setup

Use [uv](https://docs.astral.sh/uv/) (>= 0.12.21, < 0.14) to install the
environment:

```bash
uv sync
```

The lockfile excludes Intel macOS because the `habluetooth` dev dependency
ships no Intel macOS wheels.

## Hardware scripts

The scripts under `scripts/` talk to a real DOT. Run them as modules:

| Script | Does |
| --- | --- |
| `scripts.probe_dot` | connects read-only and records the traffic as JSON lines |
| `scripts.drive_dot_client` | prints every update, `--controls` plays every preset and cycles the settings |
| `scripts.live_validate` | runs every public function and asks you whether the DOT responded correctly |

`--controls` and `live_validate` change device settings and need the
local config file `scripts/drive_dot_client.local.json`, a JSON object
with `proxy`, `noise_psk` and `address`. `--proxy` routes the
connection through an ESPHome Bluetooth proxy. Captures redact the
serial number.

## Running the checks

Before opening a pull request, run the full gate:

```bash
uv run python -m scripts.check
```

It stops at the first failure and runs these steps in order:

```text
version drift check
ruff format --check .
ruff check .
python -m scripts.check_style
mypy src tests scripts
coverage run --branch -m pytest
coverage report --show-missing
uv build --no-sources
uv audit --locked --preview-features audit-command
```

Coverage measures branches in `src/flitsmeister_dot_ble` and requires 98%. Your
pull request must pass this gate completely.

The API documentation is not part of the local gate. CI builds it on every
pull request and fails on any warning. Build it locally with:

```bash
uv run --group docs sphinx-build -W -b html docs docs/_build
```

## Code style

- No code comments in any language, neither full-line nor trailing. Pragmas
  such as `# noqa`, `# type: ignore`, `# pragma: no cover` and `# shellcheck:`,
  a shebang on the first line, and non-code files such as `.md` and `.json`
  are exempt.
- Docstrings are the only documentation. They follow the Google convention
  and use plain, direct language.
- Docstrings must not contain semicolons, en or em dashes, curly quotes,
  ellipsis characters, arrows, emoji or non-breaking spaces.
- Docstrings must not use the words or phrases delve, leverage, robust,
  streamline, seamless, utilize, "worth noting", "serves as" or "it is
  important to note".

`python -m scripts.check_style` enforces these rules for Python files in
the gate.

The optional pre-commit hooks in `.pre-commit-config.yaml` run
`ruff --fix` and `ruff format` on each commit:

```bash
uvx pre-commit install
```

## Protocol and behavior changes

A protocol or behavior change is complete only when all of the following are
present:

1. A captured payload under `tests/fixtures/` backing the change. Do not
   guess wire shapes.
2. The protocol notes in `README.md` and `PROTOCOL.md` updated when wire
   shapes change.
3. Tests covering the new behavior, including the failure paths.
4. A conventional commit subject, which git-cliff renders into `CHANGELOG.md`.

## Changelog

`CHANGELOG.md` is generated with git-cliff from conventional commit subjects.
Never rewrite entries by hand. Features, bug fixes, documentation, and
maintenance chores reach the changelog through their `feat:`, `fix:`, `docs:`,
and `chore:` subjects. Regenerate the unreleased section with
`git-cliff --unreleased --prepend CHANGELOG.md` and commit the result. At
release, rename the Unreleased heading to `## [X.Y.Z] - YYYY-MM-DD`, add the
`[X.Y.Z]:` compare link at the bottom of the file, and point the
`[Unreleased]:` link at the new tag. Bump the version, commit, and tag
`vX.Y.Z`. Push the tag, then publish the GitHub release that Release Drafter
prepared for it. Publishing the release runs the gate and uploads the build
to PyPI.

## Commit style

One conventional-commit subject line, no body. Write the description as an
imperative sentence, for example: `chore: cap bleak below 4`. Do not mention
the plan or issue number in the subject.

## Deprecation policy

- While the project is on 0.x: breaking changes are allowed in minor releases,
  provided their commit subject marks them breaking (`feat!:` or `fix!:`).
- From 1.0 onwards: deprecated APIs emit a `DeprecationWarning` for at least
  one minor release before being removed in a major release.

## Pull requests

Every pull request must carry one of the seven repository labels
(`breaking-change`, `new-feature`, `enhancement`, `bugfix`, `maintenance`,
`documentation`, `dependencies`). CI fails otherwise. Dependabot pull
requests are labeled `dependencies` automatically.
