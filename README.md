# granola-mcp

MCP server for [Granola](https://granola.so) — exposes meeting notes, AI summaries, and transcripts to Claude via the [Model Context Protocol](https://modelcontextprotocol.io).

> **macOS only.** The server wraps [`granola-cli`](https://github.com/tmcinerney/granola-cli), which authenticates via the macOS Keychain. It cannot run on Linux or in a Docker container without modifications to the CLI itself — see [Why macOS only?](#why-macos-only) below.

## Tools

| Tool | Description |
|---|---|
| `granola_list_meetings` | List meetings, optionally filtered by creation/update time range or title search |
| `granola_get_notes` | Fetch AI-enhanced notes for a meeting |
| `granola_get_transcript` | Fetch the full transcript with raw audio channels and Granola-supplied names when available |
| `granola_get_meeting_context` | Fetch safe meeting context plus conservative channel/speaker-attribution summary |

## Prerequisites

**[`granola-cli`](https://github.com/tmcinerney/granola-cli)** installed and authenticated:

```sh
brew install tmcinerney/tap/granola-cli
granola auth login
```

`granola-mcp` 0.2.0 requires `granola-cli` 0.2.0 or later. Transcript source
labels (`microphone`, `system`) identify capture channels, not people. The MCP
server only renders individual names that Granola includes in raw transcript
segments, and never maps calendar attendees to speakers.

**[uv](https://docs.astral.sh/uv/)** installed:

```sh
brew install uv
```

## Setup

### Claude Code

Add to your project's `.mcp.json`:

```json
{
  "mcpServers": {
    "granola": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "git+https://github.com/tmcinerney/granola-mcp", "granola-mcp"]
    }
  }
}
```

### Claude Desktop / Cowork

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "granola": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/tmcinerney/granola-mcp", "granola-mcp"]
    }
  }
}
```

## Authentication

On auth errors the server automatically runs `granola auth login` and retries. On macOS this is non-interactive — credentials are read from the Keychain. If a biometrics or Keychain prompt stalls for more than 30 seconds the server gives up and surfaces an error rather than hanging indefinitely.

If you ever need to re-authenticate manually:

```sh
granola auth login
```

## Local development

```sh
git clone https://github.com/tmcinerney/granola-mcp
cd granola-mcp
```

Point your MCP config at the local clone instead of the git URL:

```json
{
  "mcpServers": {
    "granola": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--project", "/path/to/granola-mcp", "granola-mcp"]
    }
  }
}
```

## Why macOS only?

Claude Code runs in a sandbox without access to the macOS Keychain. `granola-cli` authenticates with Granola's API via a token stored in the Keychain — there's no env var or flag-based override. This server runs as a native macOS process alongside Claude, bridges the sandbox gap, and exposes the CLI's output as MCP tools.

Running in a Linux container would require forking `granola-cli` to add a non-keychain auth path (e.g. a `GRANOLA_TOKEN` env var). The CLI uses the [`keyring`](https://crates.io/crates/keyring) crate with no fallback for headless environments.

See [`granola-cli`](https://github.com/tmcinerney/granola-cli) for the underlying CLI this server wraps.
