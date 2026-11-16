"""Launch the Tempo MCP server on stdio.

    python manage.py run_mcp

Stdio MCP transport: newline-delimited JSON-RPC 2.0 in, responses out. Point
any MCP client at this command; logs go to stderr only.
"""
import sys

from agent import mcp_server
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run the Tempo MCP server (stdio JSON-RPC 2.0) for external MCP clients."

    def handle(self, *args, **options):
        self.stderr.write("tempo MCP server ready on stdio (protocol 2024-11-05)")
        try:
            mcp_server.serve()
        except KeyboardInterrupt:
            sys.stderr.write("\nbye\n")
