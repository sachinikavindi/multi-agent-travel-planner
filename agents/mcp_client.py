import sys
import os
import logging
from typing import Dict, List, Any
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from contextlib import AsyncExitStack

logger = logging.getLogger(__name__)

class MCPManager:
    def __init__(self):
        self.exit_stack = AsyncExitStack()
        self.sessions: Dict[str, ClientSession] = {}
        self._is_started = False

    async def start(self):
        if self._is_started:
            return
        
        # Absolute paths to the servers
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        hotel_script = os.path.join(base_dir, "mcp_hotel_server.py")
        hotel_params = StdioServerParameters(
            command=sys.executable,
            args=[hotel_script],
            env=os.environ.copy()
        )
        
        flight_script = os.path.join(base_dir, "mcp_flight_server.py")
        flight_params = StdioServerParameters(
            command=sys.executable,
            args=[flight_script],
            env=os.environ.copy()
        )

        # 1. Connect to Hotel Server
        try:
            logger.info("Starting Hotel MCP Server subprocess...")
            read_h, write_h = await self.exit_stack.enter_async_context(stdio_client(hotel_params))
            session_h = await self.exit_stack.enter_async_context(ClientSession(read_h, write_h))
            await session_h.initialize()
            self.sessions["hotel"] = session_h
            logger.info("Hotel MCP Server connection established and initialized.")
        except Exception as e:
            logger.error(f"Failed to start Hotel MCP Server: {e}")

        # 2. Connect to Flight Server
        try:
            logger.info("Starting Flight MCP Server subprocess...")
            read_f, write_f = await self.exit_stack.enter_async_context(stdio_client(flight_params))
            session_f = await self.exit_stack.enter_async_context(ClientSession(read_f, write_f))
            await session_f.initialize()
            self.sessions["flight"] = session_f
            logger.info("Flight MCP Server connection established and initialized.")
        except Exception as e:
            logger.error(f"Failed to start Flight MCP Server: {e}")
            
        self._is_started = True

    async def stop(self):
        if not self._is_started:
            return
        logger.info("Stopping MCP Servers and closing connections...")
        await self.exit_stack.aclose()
        self.sessions.clear()
        self._is_started = False
        logger.info("MCP Servers stopped.")

    def get_session(self, server_name: str) -> ClientSession:
        session = self.sessions.get(server_name)
        if not session:
            raise RuntimeError(f"MCP server '{server_name}' is not running or failed to start.")
        return session

    async def call_tool(self, server_name: str, tool_name: str, arguments: Dict[str, Any]) -> Any:
        session = self.get_session(server_name)
        try:
            result = await session.call_tool(tool_name, arguments)
            return result
        except Exception as e:
            logger.error(f"Error calling tool '{tool_name}' on server '{server_name}': {e}")
            raise

mcp_manager = MCPManager()
