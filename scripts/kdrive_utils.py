"""
Utility functions for interacting with Infomaniak kDrive API.
"""
import os
import requests
import io
from pydub import AudioSegment
from dotenv import load_dotenv

load_dotenv()

# kDrive API configuration
KDRIVE_API_TOKEN = os.getenv("KDRIVE_API_TOKEN")
KDRIVE_DRIVE_ID = os.getenv("KDRIVE_DRIVE_ID")
KDRIVE_API_BASE = "https://api.infomaniak.com/2/drive"


class KDriveClient:
    """Client for interacting with Infomaniak kDrive API."""

    def __init__(self, api_token, drive_id):
        self.api_token = api_token
        self.drive_id = drive_id
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }

    def _make_request(self, method, endpoint, **kwargs):
        """Make a request to the kDrive API."""
        url = f"{KDRIVE_API_BASE}/{self.drive_id}/{endpoint}"
        response = requests.request(method, url, headers=self.headers, **kwargs)
        response.raise_for_status()
        return response

    def get_file_info(self, file_id):
        """Get information about a file."""
        response = self._make_request("GET", f"files/{file_id}")
        return response.json()

    def download_file(self, file_id):
        """Download a file and return the raw bytes."""
        response = self._make_request("GET", f"files/{file_id}/download")
        return response.content

    def list_files_in_folder(self, folder_id):
        """List all files in a folder."""
        response = self._make_request("GET", f"files/{folder_id}/files")
        data = response.json()
        return data.get("data", [])

    def move_file(self, file_id, destination_folder_id):
        """Move a file to a different folder."""
        payload = {
            "file_ids": [file_id],
            "destination_directory_id": destination_folder_id
        }
        response = self._make_request("POST", "files/move", json=payload)
        return response.json()


# Global client instance
_kdrive_client = None


def get_kdrive_client():
    """Get or create the kDrive client instance."""
    global _kdrive_client

    if _kdrive_client is None:
        if not KDRIVE_API_TOKEN or not KDRIVE_DRIVE_ID:
            raise ValueError("KDRIVE_API_TOKEN and KDRIVE_DRIVE_ID must be set in environment variables")

        _kdrive_client = KDriveClient(KDRIVE_API_TOKEN, KDRIVE_DRIVE_ID)
        print("kDrive client initialized successfully")

    return _kdrive_client


def download_file_as_audio(file_id):
    """
    Download a file from kDrive and return as an AudioSegment.

    Args:
        file_id: The kDrive file ID

    Returns:
        AudioSegment: The downloaded audio file
    """
    client = get_kdrive_client()

    # Get file info to determine format
    file_info = client.get_file_info(file_id)
    filename = file_info.get("data", {}).get("name", "audio.mp3")
    file_extension = filename.split('.')[-1].lower()

    print(f"Downloading file: {filename} (ID: {file_id})")

    # Download the file content
    file_content = client.download_file(file_id)

    # Convert to BytesIO for pydub
    file_data = io.BytesIO(file_content)

    # Determine audio format
    if file_extension not in ['mp3', 'wav', 'flac', 'ogg', 'm4a']:
        file_extension = 'mp3'  # Default to mp3

    print(f"Converting to AudioSegment (format: {file_extension})...")
    audio = AudioSegment.from_file(file_data, format=file_extension)

    return audio


def get_file_ids_from_folder(folder_id):
    """
    Get all files from a kDrive folder.

    Args:
        folder_id: The kDrive folder ID

    Returns:
        list: List of dictionaries with 'id' and 'name' keys
    """
    client = get_kdrive_client()

    print(f"Fetching files from folder ID: {folder_id}")
    files = client.list_files_in_folder(folder_id)

    # Filter to only return actual files (not directories)
    file_list = []
    for item in files:
        if item.get("type") == "file":
            file_list.append({
                "id": item.get("id"),
                "name": item.get("name")
            })

    print(f"Found {len(file_list)} files in folder")
    return file_list


def move_file_to_folder(file_id, destination_folder_id):
    """
    Move a file to a different folder in kDrive.

    Args:
        file_id: The kDrive file ID to move
        destination_folder_id: The destination folder ID

    Returns:
        dict: Response from the API
    """
    client = get_kdrive_client()

    print(f"Moving file {file_id} to folder {destination_folder_id}")
    result = client.move_file(file_id, destination_folder_id)
    print(f"File moved successfully")

    return result
