import json
import os
import httpx
import gradio as gr

API_HOST = os.environ.get("TRAVEL_PLANNER_API_HOST", "http://127.0.0.1:8000")
STREAM_API_URL = f"{API_HOST}/chat/stream"


def format_hotels_markdown(hotels):
    if not hotels:
        return ""
    md = ["\n\n### 🏨 Recommended Hotels\n"]
    md.append("| Hotel ID | Hotel Name | Location | Price/Night | Availability |")
    md.append("| :--- | :--- | :--- | :--- | :--- |")
    for h in hotels:
        h_id = h.get("_id", "N/A")
        name = h.get("name", "N/A")
        city_data = h.get("city", "N/A")
        city = city_data.get("name", city_data) if isinstance(city_data, dict) else city_data
        price = h.get("price", h.get("pricePerNight", "N/A"))
        currency = h.get("currency", "USD")
        rooms = h.get("availableRooms", h.get("available_rooms", "N/A"))
        md.append(f"| `{h_id}` | **{name}** | {city} | {currency} {price} | {rooms} rooms |")
    return "\n".join(md) + "\n"


def format_flights_markdown(flights):
    if not flights:
        return ""
    md = ["\n\n### ✈️ Flight Options\n"]
    md.append("| Flight ID | Airline | Flight No | Route | Date & Time | Price | Seats |")
    md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for f in flights:
        f_id = f.get("_id", "N/A")
        airline = f.get("airline", "N/A")
        f_no = f.get("flightNumber", f.get("flight_number", "N/A"))
        
        origin_data = f.get("origin", "N/A")
        orig = origin_data.get("airport", origin_data) if isinstance(origin_data, dict) else origin_data
        dest_data = f.get("destination", "N/A")
        dest = dest_data.get("airport", dest_data) if isinstance(dest_data, dict) else dest_data
        
        f_date = f.get("flightDate", f.get("date", "N/A"))
        dep_time = f.get("departureTime", "N/A")
        arr_time = f.get("arrivalTime", "N/A")
        price = f.get("price", "N/A")
        currency = f.get("currency", "USD")
        seats = f.get("availableSeats", "N/A")
        
        md.append(f"| `{f_id}` | **{airline}** | {f_no} | {orig} ➡️ {dest} | {f_date} ({dep_time}-{arr_time}) | {currency} {price} | {seats} |")
    return "\n".join(md) + "\n"


async def call_chat_api_stream(message: str):
    headers = {"Content-Type": "application/json"}
    payload = {"message": message}
    
    try:
        async with httpx.AsyncClient() as client:
            async with client.stream("POST", STREAM_API_URL, json=payload, headers=headers, timeout=60.0) as response:
                if response.status_code != 200:
                    yield {"type": "error", "content": f"Backend returned HTTP error code: {response.status_code}"}
                    return
                
                async for line in response.iter_lines():
                    if line.startswith("data: "):
                        data_str = line[len("data: "):].strip()
                        if data_str:
                            try:
                                yield json.loads(data_str)
                            except Exception as e:
                                yield {"type": "error", "content": f"Parsing stream chunk failed: {str(e)}"}
    except Exception as exc:
        yield {"type": "error", "content": f"Could not connect to the backend agent server. Details: {str(exc)}"}


async def respond(message, history):
    if history is None:
        history = []
    
    if not message.strip():
        return

    # Add user message to history
    history = history + [{"role": "user", "content": message}]
    yield history

    assistant_msg = ""
    # Append initial status indicator
    history = history + [{"role": "assistant", "content": "⏳ Initializing agent..."}]
    yield history

    try:
        async for event in call_chat_api_stream(message):
            ev_type = event.get("type")
            
            if ev_type == "status":
                status_text = event.get("content", "")
                if not assistant_msg:
                    history[-1]["content"] = f"*{status_text}*"
                    yield history
                
            elif ev_type == "token":
                token = event.get("content", "")
                assistant_msg += token
                history[-1]["content"] = assistant_msg
                yield history
                
            elif ev_type == "final":
                text_response = event.get("response", "")
                hotels = event.get("hotels", [])
                flights = event.get("flights", [])
                
                final_md = text_response
                if hotels:
                    final_md += format_hotels_markdown(hotels)
                if flights:
                    final_md += format_flights_markdown(flights)
                
                history[-1]["content"] = final_md
                yield history
                
            elif ev_type == "error":
                err_text = event.get("content", "")
                assistant_msg += f"\n\n⚠️ **System Warning**: {err_text}"
                history[-1]["content"] = assistant_msg
                yield history
                
    except Exception as e:
        assistant_msg += f"\n\n❌ **Connection Error**: {str(e)}"
        history[-1]["content"] = assistant_msg
        yield history


# Premium ocean-travel theme styling
custom_css = """
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&family=Plus+Jakarta+Sans:wght@300;400;600;700&display=swap');

body, .gradio-container {
    font-family: 'Plus Jakarta Sans', 'Outfit', sans-serif !important;
    background: radial-gradient(circle at 50% 0%, #0f1e36 0%, #050a14 100%) !important;
    color: #f1f5f9 !important;
}

h1 {
    font-family: 'Outfit', sans-serif !important;
    font-weight: 800 !important;
    letter-spacing: -0.5px !important;
    background: linear-gradient(135deg, #38bdf8 0%, #0ea5e9 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}

.panel-card {
    background: rgba(15, 23, 42, 0.6) !important;
    border: 1px solid rgba(56, 189, 248, 0.15) !important;
    backdrop-filter: blur(16px) !important;
    border-radius: 16px !important;
    box-shadow: 0 4px 30px rgba(0, 0, 0, 0.4) !important;
    padding: 18px !important;
}

.button-primary {
    background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%) !important;
    color: white !important;
    font-weight: 600 !important;
    border: none !important;
    border-radius: 8px !important;
    transition: all 0.3s ease !important;
}

.button-primary:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 4px 12px rgba(14, 165, 233, 0.4) !important;
}

.suggestion-pill {
    background: rgba(30, 41, 59, 0.7) !important;
    border: 1px solid rgba(255, 255, 255, 0.08) !important;
    border-radius: 20px !important;
    padding: 6px 12px !important;
    cursor: pointer !important;
    transition: background 0.2s ease !important;
    color: #38bdf8 !important;
    font-size: 13px !important;
}

.suggestion-pill:hover {
    background: rgba(56, 189, 248, 0.15) !important;
}

table {
    border-collapse: collapse;
    width: 100%;
    margin-top: 15px;
    background: rgba(15, 23, 42, 0.4);
    border-radius: 8px;
    overflow: hidden;
}

th, td {
    padding: 10px 14px !important;
    text-align: left;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

th {
    background-color: rgba(14, 165, 233, 0.15) !important;
    color: #38bdf8 !important;
    font-weight: 600;
}

tr:hover {
    background-color: rgba(255, 255, 255, 0.03);
}
"""





def main():
    with gr.Blocks(title="Global Travel Agent Dashboard") as demo:
        gr.Markdown(
            """
            # ✈️ Global Travel Planner
            ### Intelligent Multi-Agent Travel Assistant powered by MCP Tools
            """
        )

        with gr.Column(elem_classes="panel-card"):
            chatbot = gr.Chatbot(
                elem_id="chatbot-area"
            )
            with gr.Row():
                message = gr.Textbox(
                    label="Your query",
                    placeholder="e.g. Find me hotels in Bangkok or flights from CMB to BKK on 2026-08-01",
                    scale=9
                )
                submit = gr.Button("Send", scale=1, elem_classes="button-primary")

        # Trigger responses
        submit.click(respond, inputs=[message, chatbot], outputs=[chatbot])
        message.submit(respond, inputs=[message, chatbot], outputs=[chatbot])



    demo.launch(server_name="0.0.0.0", server_port=7860, css=custom_css)


if __name__ == "__main__":
    main()
