import json
import logging
from typing import Optional, Literal, Dict, Any, List

from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage

from .llm import llm
from .prompts import get_system_prompt_for_unknown_node, get_system_prompt_with_history
from .entity import GraphState
from .mcp_client import mcp_manager
from langchain_mcp_adapters.tools import load_mcp_tools

logger = logging.getLogger(__name__)

# System prompts for specific agent personalities
SYSTEM_PROMPT_FOR_HOTEL_AGENT = """
You are a professional hotel booking assistant. Your job is to help users find, list, and book hotels.
You have access to the following tools via the Hotel MCP Server:
- list_hotels: Get a list of all available hotels.
- search_hotels: Search for hotels in a specific city, with optional check-in and check-out dates.
- book_hotel: Book a hotel room for a guest.

Rules:
1. When searching for hotels, use the `search_hotels` tool. If the user asks for all hotels generally, use `list_hotels`.
2. To book a hotel, you MUST obtain all of the following: `hotel_id`, `guest_name`, `guest_email`, `check_in_date`, `check_out_date`, and `room_type`. If any of these are missing, DO NOT call the tool; instead, ask the user politely to provide the missing details.
3. If no hotels are found or if the tools return empty results, inform the user clearly and ask if they would like to search for a different city or dates.
4. Keep your answers friendly, conversational, and direct. Do not invent hotel details.
"""

SYSTEM_PROMPT_FOR_FLIGHT_AGENT = """
You are a professional flight booking assistant. Your job is to help users find, list, and book flights.
You have access to the following tools via the Flight MCP Server:
- list_flights: Get a list of all available flights.
- search_flights: Search for flights from an origin to a destination, with an optional travel date.
- book_flight: Book a flight ticket for a passenger.

Rules:
1. When searching for flights, use the `search_flights` tool. If the user asks for all flights generally, use `list_flights`.
2. To book a flight, you MUST obtain all of the following: `flight_id`, `passenger_name`, and `passenger_email`. If any of these are missing, DO NOT call the tool; instead, ask the user politely to provide the missing details.
3. Both origin and destination are required for flight search. If the user only provides one, ask for the other before searching.
4. If no flights are found or if the tools return empty results, inform the user clearly.
5. Keep your answers friendly, conversational, and direct.
"""


class TravelExtraction(BaseModel):
    intent: Literal["hotel", "flight", "unknown"] = Field(
        default="unknown",
        description="Main user intent: hotel, flight, or unknown."
    )

    sub_action: Literal["search", "list_all", "book", "general"] = Field(
        default="general",
        description="Action type: search, list_all, book or general."
    )

    city: Optional[str] = Field(
        default=None,
        description="Hotel city name. Example: Mumbai, Colombo, Bangkok."
    )

    check_in: Optional[str] = Field(
        default=None,
        description="Hotel check-in date in YYYY-MM-DD format. Null if not provided."
    )

    check_out: Optional[str] = Field(
        default=None,
        description="Hotel check-out date in YYYY-MM-DD format. Null if not provided."
    )

    origin: Optional[str] = Field(
        default=None,
        description="Flight origin city or airport code. Example: BOM, CMB, Mumbai."
    )

    destination: Optional[str] = Field(
        default=None,
        description="Flight destination city or airport code. Example: DEL, BKK, Delhi."
    )

    flight_date: Optional[str] = Field(
        default=None,
        description="Flight date in YYYY-MM-DD format. Null if not provided."
    )

    hotel_id: Optional[str] = Field(
        default=None,
        description="ID of the hotel to book. Null if not provided."
    )

    guest_name: Optional[str] = Field(
        default=None,
        description="Guest full name for hotel booking. Null if not provided."
    )

    guest_email: Optional[str] = Field(
        default=None,
        description="Guest email for hotel booking. Null if not provided."
    )

    room_type: Optional[str] = Field(
        default=None,
        description="Hotel room type such as single, double, or suite. Null if not provided."
    )

    flight_id: Optional[str] = Field(
        default=None,
        description="ID of the flight to book. Null if not provided."
    )

    passenger_name: Optional[str] = Field(
        default=None,
        description="Passenger full name for flight booking. Null if not provided."
    )

    passenger_email: Optional[str] = Field(
        default=None,
        description="Passenger email for flight booking. Null if not provided."
    )


travel_extractor = llm.with_structured_output(TravelExtraction)


async def router(state: GraphState) -> dict:
    user_message = state["messages"][-1]
    history_messages = state["messages"][:-1]
    
    system_prompt = get_system_prompt_with_history("\n".join(history_messages))

    invocation_messages = [SystemMessage(content=system_prompt)]
    for i in range(0, len(history_messages), 2):
        invocation_messages.append(HumanMessage(content=history_messages[i]))
        if i + 1 < len(history_messages):
            invocation_messages.append(AIMessage(content=history_messages[i + 1]))
    invocation_messages.append(HumanMessage(content=user_message))

    try:
        extracted = await travel_extractor.ainvoke(invocation_messages)
        data = extracted.dict()
    except Exception as e:
        logger.error(f"Error in router extraction: {e}")
        data = {
            "intent": "unknown",
            "sub_action": "general",
        }

    return {
        "intent": data.get("intent", "unknown"),
        "sub_action": data.get("sub_action", "general"),

        "city": data.get("city"),
        "check_in": data.get("check_in"),
        "check_out": data.get("check_out"),

        "origin": data.get("origin"),
        "destination": data.get("destination"),
        "flight_date": data.get("flight_date"),

        "hotel_id": data.get("hotel_id"),
        "guest_name": data.get("guest_name"),
        "guest_email": data.get("guest_email"),
        "room_type": data.get("room_type"),

        "flight_id": data.get("flight_id"),
        "passenger_name": data.get("passenger_name"),
        "passenger_email": data.get("passenger_email"),

        "hotel_results": [],
        "flight_results": [],
        "response_text": "",
    }


async def run_mcp_agent(server_name: str, system_prompt_text: str, state: GraphState) -> dict:
    import os
    if os.environ.get("VERCEL"):
        from agents.tools import (
            get_hotels, search_hotel, book_hotel,
            get_flights, search_flights, book_flight
        )
        if server_name == "hotel":
            tools = [get_hotels, search_hotel, book_hotel]
        elif server_name == "flight":
            tools = [get_flights, search_flights, book_flight]
        else:
            tools = []
    else:
        # E3: Graceful External-Failure Handling
        try:
            session = mcp_manager.get_session(server_name)
        except Exception as e:
            logger.error(f"MCP server '{server_name}' connection error: {e}")
            return {
                "response_text": f"Error: The {server_name} service is currently unavailable. Please try again later.",
                "hotel_results": [],
                "flight_results": [],
            }

        try:
            tools = await load_mcp_tools(session)
        except Exception as e:
            logger.error(f"Failed to load tools from MCP server '{server_name}': {e}")
            return {
                "response_text": f"Error: Failed to retrieve capabilities from the {server_name} service.",
                "hotel_results": [],
                "flight_results": [],
            }

    tool_map = {tool.name: tool for tool in tools}
    model_with_tools = llm.bind_tools(tools)

    history_messages = state["messages"][:-1]
    user_message = state["messages"][-1]

    messages = [SystemMessage(content=system_prompt_text)]
    for i in range(0, len(history_messages), 2):
        messages.append(HumanMessage(content=history_messages[i]))
        if i + 1 < len(history_messages):
            messages.append(AIMessage(content=history_messages[i + 1]))
    messages.append(HumanMessage(content=user_message))

    hotel_results = []
    flight_results = []

    for step in range(5):
        try:
            response = await model_with_tools.ainvoke(messages)
        except Exception as e:
            logger.error(f"Error during LLM invocation in '{server_name}' agent: {e}")
            return {
                "response_text": f"Error: The assistant encountered an issue processing your request.",
                "hotel_results": hotel_results,
                "flight_results": flight_results,
            }

        messages.append(response)

        if not response.tool_calls:
            return {
                "response_text": response.content,
                "hotel_results": hotel_results,
                "flight_results": flight_results,
            }

        # Process tool calls
        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            tool_id = tool_call["id"]

            tool_obj = tool_map.get(tool_name)
            if tool_obj:
                try:
                    tool_result = await tool_obj.ainvoke(tool_args)
                    
                    # Try to parse search results into structured fields for frontend styling
                    try:
                        parsed = None
                        if isinstance(tool_result, str):
                            parsed = json.loads(tool_result)
                        else:
                            parsed = tool_result
                            
                        if isinstance(parsed, list):
                            if server_name == "hotel":
                                hotel_results.extend(parsed)
                            elif server_name == "flight":
                                flight_results.extend(parsed)
                    except Exception:
                        pass
                        
                    messages.append(ToolMessage(content=str(tool_result), tool_call_id=tool_id))
                except Exception as e:
                    logger.error(f"Error executing tool '{tool_name}': {e}")
                    messages.append(ToolMessage(
                        content=f"Error executing request: {str(e)}", 
                        tool_call_id=tool_id
                    ))
            else:
                messages.append(ToolMessage(
                    content=f"Error: Tool '{tool_name}' is not supported.", 
                    tool_call_id=tool_id
                ))

    return {
        "response_text": "I encountered an execution loop. Please simplify your booking instructions.",
        "hotel_results": hotel_results,
        "flight_results": flight_results,
    }


async def hotel_node(state: GraphState) -> dict:
    return await run_mcp_agent("hotel", SYSTEM_PROMPT_FOR_HOTEL_AGENT, state)


async def flight_node(state: GraphState) -> dict:
    return await run_mcp_agent("flight", SYSTEM_PROMPT_FOR_FLIGHT_AGENT, state)


async def unknown_node(state: GraphState) -> dict:
    user_message = state["messages"][-1]
    history_messages = state["messages"][:-1]

    system_prompt = get_system_prompt_for_unknown_node("\n".join(history_messages))

    invocation_messages = [SystemMessage(content=system_prompt)]
    for i in range(0, len(history_messages), 2):
        invocation_messages.append(HumanMessage(content=history_messages[i]))
        if i + 1 < len(history_messages):
            invocation_messages.append(AIMessage(content=history_messages[i + 1]))
    invocation_messages.append(HumanMessage(content=user_message))

    try:
        response = await llm.ainvoke(invocation_messages)
        return {
            "hotel_results": [],
            "flight_results": [],
            "response_text": response.content,
        }
    except Exception as e:
        logger.error(f"Error in unknown node: {e}")
        return {
            "hotel_results": [],
            "flight_results": [],
            "response_text": f"I couldn't process that general query: {str(e)}",
        }


async def generate_response(state: GraphState) -> dict:
    # If the response text is already set by the agents, return it.
    if state.get("response_text"):
        return {"response_text": state["response_text"]}
        
    return {"response_text": "I couldn't find any travel details matching your request."}


def route_after_extraction(state: GraphState) -> str:
    intent = state.get("intent", "unknown")
    if intent == "hotel":
        return "hotel"
    if intent == "flight":
        return "flight"
    return "unknown"