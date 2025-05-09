import os

import structlog
from dotenv import find_dotenv, load_dotenv
from fastapi import HTTPException
from pydantic_settings import BaseSettings

from .mcp_client import MCPClient

# Load environment variables from .env file
load_dotenv(find_dotenv())

logger = structlog.get_logger()


# Define the settings class
class Settings(BaseSettings):
    server_script_path: str = os.getenv("SERVER_SCRIPT_PATH", str())


settings = Settings()


async def lifespan(app):
    client = MCPClient()
    try:
        connected = await client.connect_to_server(settings.server_script_path)

        if not connected:
            logger.error("Failed to connect to MCP server")
            raise HTTPException(
                status_code=500,
                detail="Failed to connect to MCP server",
            )
        app.state.client = client
    except Exception as e:
        logger.error("Failed to connect to MCP server", error=str(e))
        raise e
    finally:
        # shutdown the client
        await client.cleanup()
        app.state.client = None
        logger.info("MCP client shutdown")
