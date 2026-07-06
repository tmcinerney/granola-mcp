# Releasing

This server is installed directly from GitHub via `uvx --from git+https://github.com/tmcinerney/granola-mcp`.
There are no compiled binaries or package index steps — tagging a release is enough for users to pin to it.

## Prerequisites

- `main` is passing locally (`uv run pytest` if tests exist)
- local checkout is clean
- `gh` is authenticated for `tmcinerney/granola-mcp`

## 1. Decide whether to bump MIN_GRANOLA_CLI_VERSION

Open `src/granola_mcp/server.py` and check the `MIN_GRANOLA_CLI_VERSION` constant.

Bump it if this release depends on behaviour introduced in a newer `granola-cli` — for example, a new
subcommand, a changed output format, or a fixed auth flow. Leave it if the MCP server changes are
independent of the CLI version.

If you bump it, update the constant and note the dependency in the commit message and release notes.
See [granola-cli releases](https://github.com/tmcinerney/granola-cli/releases) for the current CLI version.

## 2. Cut the release commit

Create a release worktree from the current `main`:

```sh
git fetch origin
git worktree add .worktrees/release-v0.2.0 -b release/v0.2.0 origin/main
cd .worktrees/release-v0.2.0
```

Bump the version in `pyproject.toml`:

```sh
# edit [project] version = "0.2.0"
git add pyproject.toml src/granola_mcp/server.py  # include server.py if MIN_GRANOLA_CLI_VERSION changed
git commit -m "chore(release): bump version to 0.2.0"
```

## 3. Tag and push

Fast-forward `main`, tag the release commit, and push both:

```sh
git checkout main
git merge --ff-only release/v0.2.0
git tag v0.2.0
git push origin main
git push origin v0.2.0
```

Then create a GitHub release with release notes:

```sh
gh release create v0.2.0 --title "v0.2.0" --notes "$(cat <<'EOF'
Summary of changes.

Requires granola-cli >= 0.1.2.
EOF
)"
```

If this release is paired with a `granola-cli` release, link to it in the notes:
`Paired with [granola-cli v1.2.0](https://github.com/tmcinerney/granola-cli/releases/tag/v1.2.0).`

## 4. Validate

On a machine using the uvx install path, clear the uvx cache and re-run to confirm the new version loads:

```sh
uv cache clean
uvx --from git+https://github.com/tmcinerney/granola-mcp granola-mcp --version 2>/dev/null || true
```

Also confirm the startup version check fires correctly if `MIN_GRANOLA_CLI_VERSION` changed —
run the server and look for a warning (or absence of one) in stderr.

## 5. Clean up

```sh
cd ~/Code/Public/granola-mcp
git worktree remove .worktrees/release-v0.2.0
git branch -d release/v0.2.0
```

## Paired CLI releases

When a `granola-cli` release introduces changes the MCP server depends on:

1. Release `granola-cli` first so the Homebrew tap is updated before anyone hits the version warning.
2. Bump `MIN_GRANOLA_CLI_VERSION` in `server.py` and release `granola-mcp`.
3. Cross-link the two GitHub releases in their respective release notes.

The version numbers do not need to match — they are independent semver sequences.
