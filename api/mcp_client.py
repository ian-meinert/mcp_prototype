import traceback
from contextlib import AsyncExitStack
from typing import Optional

import structlog
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPClient:
    def __init__(self):
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.llm = None  # TODO: Figure out which LLM to use
        self.tools = []
        self.messages = []
        self.logger = structlog.get_logger()

    # connect to the MCP server
    async def connect_to_server(self, server_script_path: str):
        try:
            is_python = server_script_path.endswith(".py")
            is_js = server_script_path.endswith(".js")
            if not (is_python or is_js):
                raise ValueError("Server script must be a .py or .js file")

            command = "python" if is_python else "node"
            server_params = StdioServerParameters(
                command=command, args=[server_script_path], env=None
            )

            stdio_transport = await self.exit_stack.enter_async_context(
                stdio_client(server_params)
            )

            self.stdio, self.write = stdio_transport
            self.session = await self.exit_stack.enter_async_context(
                ClientSession(self.stdio, self.write)
            )

            await self.session.initialize()

            self.logger.info(
                "Connected to MCP server",
                server_script_path=server_script_path,
            )

            mcp_tools = await self.get_mcp_tools()
            self.tools = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "args": tool.args,
                }
                for tool in mcp_tools
            ]

            self.logger.info(
                "MCP tools loaded",
                tools=[tool["name"] for tool in self.tools],
            )

        except Exception as e:
            self.logger.error(f"Error connecting to server: {e}")
            raise

    # call mcp tool

    # call mcp tool list
    async def get_mcp_tools(self):
        try:
            response = await self.session.list_tools()
            return response.tools
        except Exception as e:
            self.logger.error(f"Error getting tools: {e}")
            raise

    # process query
    async def process_query(self, query: str):
        try:
            self.logger.info("Processing query", query=query)
            user_message = {
                "role": "user",
                "content": query,
            }
            self.messages = [user_message]

            while True:
                response = await self.call_llm()

                # the response is a text message
                if response.content[0].type == "text" and len(response.content) == 1:
                    assistant_message = {
                        "role": "assistant",
                        "content": response.content[0].text,
                    }
                    self.messages.append(assistant_message)
                    break

                assistant_message = {
                    "role": "assistant",
                    "content": response.to_dict()["content"],
                }
                self.messages.append(assistant_message)

                for content in response.content:
                    if content.type == "text":
                        self.messages.append(
                            {
                                "role": "assistant",
                                "content": content.text,
                            }
                        )
                    elif content.type == "tool_call":
                        tool_name = content.name
                        tool_args = content.input
                        tool_use_id = content.id

                        self.logger.info(
                            "Calling tool",
                            tool_name=tool_name,
                            tool_args=tool_args,
                            tool_use_id=tool_use_id,
                        )

                        try:
                            result = await self.session.call_tool(
                                tool_name=tool_name,
                                tool_args=tool_args,
                            )
                            self.logger.info(
                                "Tool call result",
                                tool_name=tool_name,
                                result=result[:100],
                            )

                            self.messages.append(
                                {
                                    "role": "user",
                                    "content": [
                                        {
                                            "type": "tool_result",
                                            "tool_use_id": tool_use_id,
                                            "content": result.content,
                                        }
                                    ],
                                }
                            )
                        except Exception as e:
                            self.logger.error(
                                "Error calling tool",
                                tool_name=tool_name,
                                error=str(e),
                            )
                            raise

                    else:
                        self.logger.error("Unknown content type")
                        raise ValueError("Unknown content type")

            return self.messages
        except Exception as e:
            self.logger.error(f"Error processing query: {e}")
            raise

    # call llm
    async def call_llm(self):
        try:
            self.logger.info("Calling LLM", messages=self.messages)
            response = self.llm.messages.create(
                messages=self.messages,
                tools=self.tools,
                max_tokens=1000,
                temperature=0.7,
                top_p=1.0,
                n=1,
            )
            return response
        except Exception as e:
            self.logger.error(f"Error calling LLM: {e}")
            raise

    # cleanup
    async def cleanup(self):
        try:
            await self.exit_stack.aclose()
            self.logger.info("Disconnected from MCP server")
        except Exception as e:
            self.logger.error(f"Error disconnecting from server: {e}")
            traceback.print_exc()
            raise

    ## extra

    # log conversation
