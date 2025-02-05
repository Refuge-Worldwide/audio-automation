from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google.oauth2 import service_account
import io
import os
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client, Client
import contentful_management
import requests
from error_handling import send_error_to_slack

load_dotenv()

url: str = os.getenv("SUPABASE_URL")
key: str = os.getenv("SUPABASE_TOKEN")
supabase: Client = create_client(url, key)

CONTENTFUL_SPACE_ID = os.getenv('CONTENTFUL_SPACE_ID')
CONTENTFUL_ENV_ID = os.getenv('CONTENTFUL_ENV_ID')
CONTENTFUL_MANAGEMENT_API_TOKEN = os.getenv('CONTENTFUL_MANAGEMENT_API_TOKEN')

# Load environment variables
SCOPES = ['https://www.googleapis.com/auth/drive']
SUPABASE_URL = os.getenv("SUPABASE_URL")

def get_drive_service():
    """Authenticate and return a Google Drive service instance."""
    credentials = service_account.Credentials.from_service_account_info(
        {
            "type": "service_account",
            "client_email": os.getenv('GOOGLE_DRIVE_CLIENT_EMAIL'),
            "private_key": os.getenv('GOOGLE_DRIVE_PRIVATE_KEY').replace('\\n', '\n'),
            "token_uri": "https://oauth2.googleapis.com/token"
        },
        scopes=SCOPES
    )
    return build('drive', 'v3', credentials=credentials)


def get_soundcloud_token():
    """Retrieve a valid SoundCloud OAuth token, refreshing if expired."""
    # Retrieve the access token and refresh token (stored securely)
    access_token = os.getenv("SC_ACCESS_TOKEN")
    refresh_token = os.getenv("SC_REFRESH_TOKEN")
    expires_at = datetime.now() + timedelta(seconds=3599)

    # If the access token has expired, refresh it
    if datetime.now() >= expires_at:
        print("Access token expired, refreshing...")
        refresh_url = "https://api.soundcloud.com/oauth2/token"
        data = {
            "grant_type": "refresh_token",
            "client_id": os.getenv("SC_CLIENT_ID"),
            "client_secret": os.getenv("SC_CLIENT_SECRET"),
            "refresh_token": refresh_token
        }
        response = requests.post(refresh_url, data=data)

        if response.status_code == 200:
            new_tokens = response.json()
            access_token = new_tokens["access_token"]
            refresh_token = new_tokens["refresh_token"]
            expires_at = datetime.now() + timedelta(seconds=new_tokens["expires_in"])

            # Save the new access token and expiration time (you may store it in DB or environment)
            os.environ["SC_ACCESS_TOKEN"] = access_token
            os.environ["SC_REFRESH_TOKEN"] = refresh_token
            os.environ["TOKEN_EXPIRATION_TIME"] = str(int(expires_at.timestamp()))
            print(f"New access token obtained: {access_token}")
        else:
            error_message = "Failed to refresh access token"
            print(error_message)
            send_error_to_slack(error_message)
            return None

    return access_token

def upload_to_soundcloud(audio_segment, title, description):
    """Upload audio to SoundCloud."""
    import json

    try:
        # Convert the AudioSegment to a BytesIO object
        audio_file = io.BytesIO()
        audio_segment.export(audio_file, format="mp3", bitrate="192k")
        audio_file.seek(0)  # Reset file pointer

        # Get the SoundCloud token
        token = get_soundcloud_token()
        print(f"Using token: {token}")

        # Send the POST request to SoundCloud with the token in the Authorization header
        response = requests.post(
            "https://api.soundcloud.com/tracks",
            headers={"Authorization": f"OAuth {token}"},
            files={"track[asset_data]": audio_file},
            data={
                "track[title]": title,
                "track[description]": description,
                "track[sharing]": "private",
                "track[downloadable]": "true"
            }
        )

        # Print response for debugging
        print(f"Response status code: {response.status_code}")
        print(f"Response text: {response.text}")

        # Raise an exception if the request failed
        response.raise_for_status()

        # Get the response data and return the permalink
        data = response.json()
        return data['permalink_url']

    except requests.exceptions.RequestException as e:
        error_message = "Error uploading to SoundCloud: {e}"
        send_error_to_slack(error_message)
        print(error_message)
        raise

# Function to update the SoundCloud link for a show in Contentful
def update_show_sc_link(entry_id, sc_link):
    try: 
        client = contentful_management.Client(CONTENTFUL_MANAGEMENT_API_TOKEN)
        space = client.spaces().find(CONTENTFUL_SPACE_ID)
        environment = space.environments().find(CONTENTFUL_ENV_ID)

        entry = environment.entries().find(entry_id)
        entry.fields('en-US')['mixcloudLink'] = sc_link
        entry.save()
        entry.publish()
        print(f"SoundCloud link updated for entry ID {entry_id}.")
    
    except Exception as e:
        error_message = f"Error updating show {entry_id} with SoundCloud link: {str(e)}"
        send_error_to_slack(error_message)
        print(error_message)


def get_show_from_timestamp(timestamp):
    try:
        api_key = os.getenv('WEBSITE_API_KEY')
        headers = {'Authorization': f'Bearer {api_key}'}
        response = requests.get(f"https://refugeworldwide.com/api/shows/by-timestamp?t={timestamp}", headers=headers)
        response.raise_for_status()  # Raise an exception for HTTP errors
        show = response.json()  # Parse the JSON response
        return show
    except requests.RequestException as e:
        error_message = "Error fetching show for timestamp {timestamp}: {e}"
        print(error_message)
        send_error_to_slack(error_message)
        return None
    
def fetch_show_details_from_contentful(timestamp):
    show = get_show_from_timestamp(timestamp)
    if show:
        show_name = show.fields('en-US').get('name', 'Unknown Show')
        show_description = show.fields('en-US').get('description', 'No description available.')
        show_image = show.fields('en-US').get('image', {}).get('url', None)
        return show_name, show_description, show_image
    return None, None, None

def upload_to_soundcloud_with_metadata(audio_segment, timestamp):
    """Upload audio to SoundCloud with metadata and update Contentful."""
    show_metadata = fetch_show_details_from_contentful(timestamp)

    if not show_metadata:
        print(f"No metadata found for timestamp: {timestamp}")
        return

    title = show_metadata['title']
    description = show_metadata['description']
    entry_id = show_metadata['entry_id']

    # Upload to SoundCloud
    sc_link = upload_to_soundcloud(audio_segment, title, description)

    # Update Contentful entry with SoundCloud link
    update_show_sc_link(entry_id, sc_link)
    print(f"SoundCloud link updated in Contentful for entry {entry_id}")

def upload_to_drive(service, audio_segment, filename, folder_id, timestamp):
    """Upload an audio file to Google Drive."""
    file_stream = io.BytesIO()
    tags = {'artist': 'Radio Show', 'date': timestamp}
    audio_segment.export(file_stream, format="mp3", bitrate="192k", tags=tags)
    file_stream.seek(0)

    file_metadata = {
        'name': filename,
        'parents': [folder_id]
    }

    media = MediaIoBaseUpload(file_stream, mimetype='audio/mp3', resumable=True)
    service.files().create(body=file_metadata, media_body=media, fields='id').execute()


# if __name__ == "__main__":
#     response = get_show_fields()
#     if response:
#         print("SoundCloud Token:", response)
#     else:
#         print("Failed to obtain a valid token.")

