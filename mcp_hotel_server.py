import requests
from typing import List, Optional
from fastmcp import FastMCP

mcp = FastMCP("HotelServer")

HOTEL_API_BASE = "https://standing-fish-574.convex.site/hotels"


def _fetch_json(url: str, params: Optional[dict] = None) -> any:
    try:
        response = requests.get(url, params=params, timeout=10)
        return response.json()
    except Exception:
        return None


@mcp.tool()
def list_hotels() -> List[dict]:
    """
    Get a list of all available hotels.
    Use this when the user asks to show/list all hotels.
    """
    data = _fetch_json(HOTEL_API_BASE)
    if isinstance(data, dict):
        return data.get("hotels", [])
    return []


@mcp.tool()
def search_hotels(
    city: str,
    check_in: Optional[str] = None,
    check_out: Optional[str] = None,
) -> List[dict]:
    """
    Search for hotels by city and optional check-in/check-out dates.

    Args:
        city: Hotel city name. Example: Bangkok, Colombo, Singapore.
        check_in: Optional check-in date in YYYY-MM-DD format.
        check_out: Optional check-out date in YYYY-MM-DD format.
    """
    params = {"city": city}
    if check_in:
        params["checkIn"] = check_in
    if check_out:
        params["checkOut"] = check_out

    data = _fetch_json(f"{HOTEL_API_BASE}/search", params=params)
    if isinstance(data, dict):
        return data.get("hotels", [])
    return []


@mcp.tool()
def book_hotel(
    hotel_id: str,
    guest_name: str,
    guest_email: str,
    check_in_date: str,
    check_out_date: str,
    room_type: str,
) -> dict:
    """
    Book a hotel room.

    Args:
        hotel_id: ID of the hotel to book.
        guest_name: Full name of the guest.
        guest_email: Email of the guest.
        check_in_date: Check-in date (YYYY-MM-DD).
        check_out_date: Check-out date (YYYY-MM-DD).
        room_type: Type of room (single, double, suite).
    """
    payload = {
        "hotelId": hotel_id,
        "guestName": guest_name,
        "guestEmail": guest_email,
        "checkInDate": check_in_date,
        "checkOutDate": check_out_date,
        "roomType": room_type,
    }
    try:
        response = requests.post(f"{HOTEL_API_BASE}/book", json=payload, timeout=10)
        return response.json()
    except Exception as e:
        return {"error": f"Failed to connect to booking service: {str(e)}"}


if __name__ == "__main__":
    mcp.run()
