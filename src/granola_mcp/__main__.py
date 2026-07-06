"""Entry point for granola-mcp server."""

from granola_mcp.server import check_cli_version, create_server


def main() -> None:
    check_cli_version()
    server = create_server()
    server.run()


if __name__ == "__main__":
    main()
