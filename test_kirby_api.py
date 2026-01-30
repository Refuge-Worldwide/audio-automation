#!/usr/bin/env python3
"""
Test script to verify Kirby API connectivity and episode fetching.
"""
import sys
import os

# Add scripts directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'scripts'))

from kirby_utils import get_episode_by_timestamp
from dotenv import load_dotenv

load_dotenv()

def test_kirby_connection():
    """Test the Kirby API connection with a sample timestamp."""
    print("=" * 60)
    print("Testing Kirby API Connection")
    print("=" * 60)

    # Get configuration
    kirby_base_url = os.getenv("KIRBY_BASE_URL")
    kirby_api_key = os.getenv("KIRBY_API_KEY")

    print(f"\nConfiguration:")
    print(f"KIRBY_BASE_URL: {kirby_base_url}")
    print(f"KIRBY_API_KEY: {'Set' if kirby_api_key else 'Not set'}")

    # Test with the timestamp from your error message
    test_timestamp = "20240316-1330"

    print(f"\nTesting with timestamp: {test_timestamp}")
    print(f"Expected URL: {kirby_base_url}/api/episode-by-timestamp?t={test_timestamp}")
    print("-" * 60)

    try:
        episode = get_episode_by_timestamp(test_timestamp)

        if episode:
            print("\n✓ Successfully fetched episode!")
            print(f"\nEpisode data structure:")
            print(f"  Keys: {list(episode.keys())}")
            print(f"\nEpisode details:")
            for key, value in episode.items():
                if isinstance(value, str) and len(value) > 100:
                    print(f"  {key}: {value[:100]}... (truncated)")
                else:
                    print(f"  {key}: {value}")
        else:
            print("\n✗ No episode found or API returned None")

    except Exception as e:
        print(f"\n✗ Error occurred: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 60)

if __name__ == "__main__":
    test_kirby_connection()
