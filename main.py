import json
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from entity import ChatRequest, ChatResponse
from agents.graph import graph
from agents.mcp_client import mcp_manager
import gradio as gr
from frontend import demo

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

conversation_history_messages = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    import os
    if os.environ.get("VERCEL"):
        logger.info("Running on Vercel. Bypassing MCP subprocess startup.")
        yield
    else:
        # Start the MCP server subprocesses
        logger.info("Initializing MCP Servers...")
        await mcp_manager.start()
        yield
        # Gracefully stop the MCP servers on shutdown
        logger.info("Shutting down MCP Servers...")
        await mcp_manager.stop()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app = gr.mount_gradio_app(app, demo, path="/")


@app.get("/hotels")
async def list_hotels():
    try:
        import os
        if os.environ.get("VERCEL"):
            from agents.tools import get_hotels
            return get_hotels.invoke({})
        result = await mcp_manager.call_tool("hotel", "list_hotels", {})
        if result.content and len(result.content) > 0:
            return json.loads(result.content[0].text)
        return []
    except Exception as e:
        logger.error(f"Error in list_hotels endpoint: {e}")
        return {"error": f"Failed to retrieve hotels: {str(e)}"}


@app.get("/flights")
async def list_flights():
    try:
        import os
        if os.environ.get("VERCEL"):
            from agents.tools import get_flights
            return get_flights.invoke({})
        result = await mcp_manager.call_tool("flight", "list_flights", {})
        if result.content and len(result.content) > 0:
            return json.loads(result.content[0].text)
        return []
    except Exception as e:
        logger.error(f"Error in list_flights endpoint: {e}")
        return {"error": f"Failed to retrieve flights: {str(e)}"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    recent_pairs = conversation_history_messages[-3:]
    flattened_messages = []
    for user_msg, assistant_msg in recent_pairs:
        flattened_messages.append(user_msg)
        flattened_messages.append(assistant_msg)
    flattened_messages.append(request.message)

    initial_state = {
        "messages": flattened_messages,
        "intent": "",
        "sub_action": "",
        "city": None,
        "check_in": None,
        "check_out": None,
        "origin": None,
        "destination": None,
        "flight_date": None,
        "hotel_id": None,
        "guest_name": None,
        "guest_email": None,
        "room_type": None,
        "flight_id": None,
        "passenger_name": None,
        "passenger_email": None,
        "hotel_results": [],
        "flight_results": [],
        "response_text": "",
    }

    try:
        result = await graph.ainvoke(initial_state)
        response_text = result.get("response_text", "Something went wrong. Please try again.")
    except Exception as e:
        logger.error(f"Error in graph.ainvoke: {e}")
        response_text = f"An error occurred while running the travel agent: {str(e)}"
        result = {}

    conversation_history_messages.append((request.message, response_text))

    return ChatResponse(
        response=response_text,
        hotels=result.get("hotel_results", []) or None,
        flights=result.get("flight_results", []) or None,
    )


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    async def sse_generator():
        recent_pairs = conversation_history_messages[-3:]
        flattened_messages = []
        for user_msg, assistant_msg in recent_pairs:
            flattened_messages.append(user_msg)
            flattened_messages.append(assistant_msg)
        flattened_messages.append(request.message)

        initial_state = {
            "messages": flattened_messages,
            "intent": "",
            "sub_action": "",
            "city": None,
            "check_in": None,
            "check_out": None,
            "origin": None,
            "destination": None,
            "flight_date": None,
            "hotel_id": None,
            "guest_name": None,
            "guest_email": None,
            "room_type": None,
            "flight_id": None,
            "passenger_name": None,
            "passenger_email": None,
            "hotel_results": [],
            "flight_results": [],
            "response_text": "",
        }

        active_node = ""
        final_state = None

        try:
            async for event in graph.astream_events(initial_state, version="v2"):
                kind = event["event"]

                # 1. Update status when nodes start
                if kind == "on_node_start":
                    active_node = event["name"]
                    status_msg = ""
                    if active_node == "router":
                        status_msg = "🔄 Routing travel query..."
                    elif active_node == "hotel_node":
                        status_msg = "🏨 Hotel Agent active. Analyzing suggestions..."
                    elif active_node == "flight_node":
                        status_msg = "✈️ Flight Agent active. Checking schedules..."
                    elif active_node == "unknown_node":
                        status_msg = "💬 Travel Assistant active..."
                    elif active_node == "generate_response":
                        status_msg = "📝 Formatting final itinerary..."

                    if status_msg:
                        yield f"data: {json.dumps({'type': 'status', 'content': status_msg})}\n\n"

                # 2. Update status when tools are called
                elif kind == "on_tool_start":
                    tool_name = event["name"]
                    yield f"data: {json.dumps({'type': 'status', 'content': f'🔍 Querying MCP tool: {tool_name}...'})}\n\n"

                # 3. Stream text tokens for conversation nodes
                elif kind == "on_chat_model_stream":
                    if active_node in ("hotel_node", "flight_node", "unknown_node"):
                        content = event["data"]["chunk"].content
                        if content:
                            yield f"data: {json.dumps({'type': 'token', 'content': content})}\n\n"

                # 4. Capture the final GraphState output
                elif kind == "on_chain_end":
                    output = event["data"].get("output")
                    if isinstance(output, dict) and "response_text" in output:
                        final_state = output

        except Exception as e:
            logger.error(f"Error in streaming event generator: {e}")
            yield f"data: {json.dumps({'type': 'error', 'content': f'Streaming error occurred: {str(e)}'})}\n\n"
            return

        if final_state:
            resp_text = final_state.get("response_text", "")
            conversation_history_messages.append((request.message, resp_text))
            
            # Send the final payload with structured results
            yield f"data: {json.dumps({
                'type': 'final',
                'response': resp_text,
                'hotels': final_state.get('hotel_results', []),
                'flights': final_state.get('flight_results', [])
            })}\n\n"
        else:
            yield f"data: {json.dumps({'type': 'error', 'content': 'Could not formulate travel recommendation.'})}\n\n"

    return StreamingResponse(sse_generator(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)