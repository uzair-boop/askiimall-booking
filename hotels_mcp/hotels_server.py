import json
import httpx
import logging
import signal
import sys
import argparse
from typing import Dict, List, Any, Optional
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv
import os
from fastapi import FastAPI

# Load environment variables
load_dotenv()

# Initialize MCP
mcp = FastMCP("hotels")

# Mount Streamable HTTP App
app = FastAPI()
app.mount("/mcp", mcp.streamable_http_app)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("hotels-mcp-server")

# Initialize FastMCP server
mcp = FastMCP("hotels")

# Constants — FIXED TO BOOKING.COM RAPIDAPI
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
RAPIDAPI_HOST = "booking-com.p.rapidapi.com"   # FIXED

# Validate required environment variables
if not RAPIDAPI_KEY:
    logger.error("RAPIDAPI_KEY environment variable is not set. Please create a .env file with your API key.")
    sys.exit(1)

# ======================================================================
#   ASYNC REQUEST HELPER (kept same signature; only URL structure fixed)
# ======================================================================
async def make_rapidapi_request(endpoint: str, params: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Make a request to the RapidAPI with proper error handling."""
    url = f"https://{RAPIDAPI_HOST}{endpoint}"
    
    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": RAPIDAPI_HOST
    }
    
    logger.info(f"Making API request to {endpoint} with params: {params}")
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, params=params, timeout=30.0)
            response.raise_for_status()
            logger.info(f"API request to {endpoint} successful")
            return response.json()
        except Exception as e:
            logger.error(f"API request to {endpoint} failed: {str(e)}")
            return {"error": str(e)}

# ======================================================================
#  SEARCH DESTINATIONS — FIXED TO /v1/hotels/locations
# ======================================================================
@mcp.tool()
async def search_destinations(query: str) -> str:
    """Search for hotel destinations by name."""
    logger.info(f"Searching for destinations with query: {query}")

    # FIXED ENDPOINT
    endpoint = "/v1/hotels/locations"

    params = {"name": query, "locale": "en-gb"}
    
    result = await make_rapidapi_request(endpoint, params)
    
    if "error" in result:
        logger.error(f"Error in search_destinations: {result['error']}")
        return f"Error fetching destinations: {result['error']}"
    
    formatted_results = []
    
    if isinstance(result, list):
        destinations_count = len(result)
        logger.info(f"Found {destinations_count} destinations for query: {query}")
        for destination in result:
            dest_info = (
                f"Name: {destination.get('name', 'Unknown')}\n"
                f"Type: {destination.get('dest_type', 'Unknown')}\n"
                f"City ID: {destination.get('dest_id', 'N/A')}\n"
                f"Country: {destination.get('country', 'Unknown')}\n"
                f"Coordinates: {destination.get('latitude', 'N/A')}, {destination.get('longitude', 'N/A')}\n"
            )
            formatted_results.append(dest_info)
        
        return "\n---\n".join(formatted_results) if formatted_results else "No destinations found matching your query."
    else:
        logger.warning(f"Unexpected response format from API for query: {query}")
        return "Unexpected response format from the API."

# ======================================================================
#  GET HOTELS — FIXED TO /v1/hotels/search
# ======================================================================
@mcp.tool()
async def get_hotels(destination_id: str, checkin_date: str, checkout_date: str, adults: int = 2) -> str:
    """Get hotels for a specific destination."""

    logger.info(f"Getting hotels for destination_id: {destination_id}, checkin: {checkin_date}, checkout: {checkout_date}, adults: {adults}")

    # FIXED ENDPOINT
    endpoint = "/v1/hotels/search"

    params = {
        "adults_number": adults,
        "units": "metric",
        "page_number": 0,
        "checkin_date": checkin_date,
        "checkout_date": checkout_date,
        "dest_type": "city",
        "dest_id": destination_id,
        "order_by": "popularity",
        "include_adjacency": "true",
        "room_number": 1,
        "filter_by_currency": "USD",
        "locale": "en-gb"
    }
    
    result = await make_rapidapi_request(endpoint, params)
    
    if "error" in result:
        logger.error(f"Error in get_hotels: {result['error']}")
        return f"Error fetching hotels: {result['error']}"
    
    formatted_results = []

    # Booking.com response is an object with "result" list
    hotels = result.get("result", [])

    if isinstance(hotels, list):
        hotels_count = len(hotels)
        logger.info(f"Found {hotels_count} hotels for destination: {destination_id}")

        for hotel in hotels[:10]:

            # --- Price (use min_total_price since gross_price is always null) ---
            price_value = hotel.get("min_total_price")
            currency = hotel.get("currency_code") or hotel.get("currencycode") or ""
            if price_value is None:
                price_display = "N/A"
            else:
                price_display = f"{price_value} {currency}".strip()

            # --- URL with filters applied ---
            base_url = hotel.get("url", "")
            if base_url:
                final_url = (
                    f"{base_url}"
                    f"?checkin={checkin_date}"
                    f"&checkout={checkout_date}"
                    f"&group_adults={adults}"
                    f"&no_rooms=1"
                    f"&group_children=0"
                )
            else:
                final_url = "N/A"

            # --- Main Image (pick best available) ---
            main_image = (
                hotel.get("max_1440_photo_url")
                or hotel.get("max_photo_url")
                or hotel.get("main_photo_url")
                or "N/A"
            )

            hotel_info = (
                f"Name: {hotel.get('hotel_name', 'Unknown')}\n"
                f"Rating: {hotel.get('review_score', 'N/A')}/10\n"
                f"Address: {hotel.get('address', 'N/A')}\n"
                f"Price: {price_display}\n"
                f"Coordinates: {hotel.get('latitude', 'N/A')}, {hotel.get('longitude', 'N/A')}\n"
                f"Stars: {hotel.get('class', 'N/A')}\n"
                f"URL: {final_url}\n"
                f"Image: {main_image}\n"
            )

            formatted_results.append(hotel_info)

        return "\n---\n".join(formatted_results) if formatted_results else "No hotels found for these dates."
    else:
        logger.warning(f"Unexpected response format from API for destination: {destination_id}")
        return "Unexpected response format from the API."

# ======================================================================
#  Shutdown + Main (unchanged)
# ======================================================================
def handle_shutdown(signum, frame):
    """Handle shutdown signals gracefully."""
    logger.info("Received shutdown signal, shutting down gracefully...")
    sys.exit(0)


def main():
    import uvicorn
    uvicorn.run(
        "hotels_mcp.hotels_server:app",
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )


app = mcp.streamable_http_app()
print([route.path for route in app.routes])

if __name__ == "__main__":
    main()
