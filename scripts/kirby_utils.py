"""
Utility functions for interacting with Kirby CMS API.
"""
import os
import requests
from dotenv import load_dotenv
from error_handling import send_error_to_slack

load_dotenv()

# Kirby CMS configuration
KIRBY_BASE_URL = os.getenv("KIRBY_BASE_URL")
KIRBY_API_KEY = os.getenv("KIRBY_API_KEY")


def _get_kirby_headers():
    """Get headers for Kirby API requests."""
    if not KIRBY_API_KEY:
        raise ValueError("KIRBY_API_KEY must be set in environment variables")

    return {
        "Authorization": f"Bearer {KIRBY_API_KEY}",
        "Content-Type": "application/json"
    }


def get_episode_by_timestamp(timestamp):
    """
    Fetch episode details from Kirby CMS by timestamp.

    Args:
        timestamp: Timestamp in format YYYYMMDD-HHMM

    Returns:
        Dictionary with episode data or None if not found
    """
    if not KIRBY_BASE_URL:
        raise ValueError("KIRBY_BASE_URL must be set in environment variables")

    try:
        # Construct the API endpoint
        url = f"{KIRBY_BASE_URL.rstrip('/')}/api/episode-by-timestamp"

        # Try to get headers, but don't fail if API key is not set (some endpoints might be public)
        headers = {}
        try:
            if KIRBY_API_KEY:
                headers = _get_kirby_headers()
        except:
            pass

        # Make the request with timestamp as query parameter
        response = requests.get(
            url,
            params={"t": timestamp},
            headers=headers,
            timeout=30
        )

        # Check if request was successful
        if response.status_code == 404:
            print(f"No episode found for timestamp: {timestamp}")
            return None

        response.raise_for_status()

        # Parse and return the JSON response
        episode_data = response.json()
        print(f"Successfully fetched episode: {episode_data.get('title', 'Unknown')}")
        print(f"Episode data keys: {list(episode_data.keys()) if episode_data else 'None'}")
        print(f"Episode data: {episode_data}")

        return episode_data

    except requests.exceptions.RequestException as e:
        error_message = f"Error fetching episode from Kirby for timestamp {timestamp}: {e}"
        print(error_message)
        send_error_to_slack(error_message)
        return None
    except Exception as e:
        error_message = f"Unexpected error fetching episode from Kirby: {e}"
        print(error_message)
        send_error_to_slack(error_message)
        return None


def update_episode(episode_id, soundcloud_url):
    """
    Update an episode in Kirby CMS with a SoundCloud URL.

    Args:
        episode_id: The episode ID/slug in Kirby
        soundcloud_url: The SoundCloud permalink URL

    Returns:
        Dictionary with updated episode data or None if failed
    """
    if not KIRBY_BASE_URL:
        raise ValueError("KIRBY_BASE_URL must be set in environment variables")

    try:
        # Construct the API endpoint
        url = f"{KIRBY_BASE_URL.rstrip('/')}/api/update-episode"

        # Prepare the update payload with ID in body
        payload = {
            "id": episode_id,
            "soundcloud_url": soundcloud_url
        }

        # Make the PATCH request to update the episode
        response = requests.patch(
            url,
            json=payload,
            headers=_get_kirby_headers(),
            timeout=30
        )

        response.raise_for_status()

        print(f"Successfully updated episode {episode_id} with SoundCloud URL")

        return response.json()

    except requests.exceptions.RequestException as e:
        error_message = f"Error updating episode {episode_id} in Kirby: {e}"
        print(error_message)
        send_error_to_slack(error_message)
        raise
    except Exception as e:
        error_message = f"Unexpected error updating episode in Kirby: {e}"
        print(error_message)
        send_error_to_slack(error_message)
        raise
