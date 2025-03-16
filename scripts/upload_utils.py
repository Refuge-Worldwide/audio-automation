from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google.oauth2 import service_account
import io
import os
import requests
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv, set_key, find_dotenv
from supabase import create_client, Client
import contentful_management
import requests
from error_handling import send_error_to_slack
from supabase import create_client, Client 

dotenv_path = find_dotenv()
load_dotenv(dotenv_path)

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
            "private_key": os.getenv('GOOGLE_DRIVE_PRIVATE_KEY'),
            "token_uri": "https://oauth2.googleapis.com/token"
        },
        scopes=SCOPES
    )
    return build('drive', 'v3', credentials=credentials)

def get_soundcloud_token():
    """Retrieve a valid SoundCloud OAuth token, refreshing if expired."""

    # Retrieve the access token, refresh token and expiration time from supbase
    response = supabase.from_("accessTokens").select("*").eq("application", "soundcloud").single().execute()
    access_token = response.data["token"]
    refresh_token = response.data["refresh_token"]
    expires_at = response.data["expires"]

    #convert expiration time to datetime object
    expires_at_date_object = datetime.strptime(expires_at, "%Y-%m-%dT%H:%M:%S%z")

    # If the access token has expired, refresh it
    if datetime.now(timezone.utc) >= expires_at_date_object:
        print("Access token expired, refreshing...")
        refresh_url = "https://secure.soundcloud.com/oauth/token"
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
            # Add buffer of 60 seconds to ensure we don't try an invalid token due to some delay
            expires_at = datetime.now() + timedelta(seconds=new_tokens["expires_in"] - 60)
            expires_at_str = expires_at.strftime("%Y-%m-%dT%H:%M:%S%z")

            """Update the SoundCloud token in Supabase."""
            data = {
                "token": access_token,
                "refresh_token": refresh_token,
                "expires": expires_at_str
            }
            response = supabase.from_("accessTokens").update(data).eq("application", "soundcloud").execute()
        
            print(f"New access token obtained: {access_token}")
            print(f"New refresh token obtained: {refresh_token}")
        else:
            error_message = "Failed to refresh access token"
            print(error_message)
            send_error_to_slack(error_message)
            return None

    return access_token

def upload_to_soundcloud(audio_segment, show_metadata):
    """Upload audio to SoundCloud."""
    import json
    def download_image(image_url):
        response = requests.get(image_url)
        response.raise_for_status()  # Raise an exception if the image download fails
        return response.content  # Return the raw image data

    # Image URL from Contentful show data
    image_url = "https:" + show_metadata["artwork"]

    # Download the image
    image_data = download_image(image_url)

    #
    try:
        # Convert the AudioSegment to a BytesIO object
        audio_file = io.BytesIO()
        audio_segment.export(audio_file, format="mp3", bitrate="192k")
        audio_file.seek(0)  # Reset file pointer

        # Get the SoundCloud token
        token = get_soundcloud_token()
        print(f"Using token: {token}")

        # Create the filename with the show name and title
        filename = f"{show_metadata['title']}.mp3"

        # Send the POST request to SoundCloud with the token in the Authorization header
        response = requests.post(
            "https://api.soundcloud.com/tracks",
            headers={"Authorization": f"OAuth {token}"},
            files={
                "track[asset_data]": (filename, audio_file, "audio/,mpeg"),
                "track[artwork_data]": ("artwork.png", image_data, "image/png")
                },
            data={
                "track[title]": show_metadata["title"],
                "track[description]": show_metadata["description"],
                "track[tag_list]": " ".join([f"\"{genre}\"" for genre in show_metadata["genres"]]),
                "track[sharing]": "public",
                "track[downloadable]": "false"
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
        error_message = f"Error uploading to SoundCloud: {e}"
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
        error_message = f"Error fetching show for timestamp {timestamp}: {e}"
        print(error_message)
        send_error_to_slack(error_message)
        return None

    
def fetch_show_details_from_contentful(timestamp):
    show = get_show_from_timestamp(timestamp)
    show_metadata = {}
    if show:
        show = show[0]
        date_obj = datetime.strptime(timestamp, "%Y%m%dT%H%M")
        formatted_date = date_obj.strftime("%d %b %Y")
        show_name, artists = show["title"].split(" | ")
        final_title = f"{show_name} - {artists} - {formatted_date}"

        show_metadata["entry_id"] = show["id"]
        show_metadata["title"] = final_title
        show_metadata["description"] = "🌐 Refuge Worldwide is a radio station and community space based in Berlin-Neukölln.\n➡️ More info, more music: www.refugeworldwide.com\n\nSupport us by becoming a member on Patreon for just 3€ a month: www.patreon.com/refugeworldwide"
        show_metadata["artwork"] = show["artwork"]
        show_metadata["genres"] = show["genres"]
        return show_metadata
    return None, None, None

def upload_to_soundcloud_with_metadata(audio_segment, timestamp):

    show_metadata = fetch_show_details_from_contentful(timestamp)
    if not show_metadata:
        print(f"No metadata found for timestamp: {timestamp}")
        return

    # Upload to SoundCloud
    sc_link = upload_to_soundcloud(audio_segment, show_metadata)
    entry_id = show_metadata["entry_id"]
    # Update Contentful entry with SoundCloud link
    update_show_sc_link(entry_id, sc_link)
    return sc_link

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


from googleapiclient.errors import HttpError

def move_file_to_folder(service, file_id, new_folder_id):
    """Move a file to a folder, even if it has no parents."""
    try:
        # Step 1: Get file metadata
        file_metadata = service.files().get(fileId=file_id, fields='id, name, parents').execute()
        parents = file_metadata.get('parents', [])

        print(f"Retrieved file metadata: {file_metadata}")

        if not parents:
            print(f"File {file_id} has NO parents. Copying to {new_folder_id}...")

            # Step 2: Create a copy in the target folder
            copied_file = service.files().copy(
                fileId=file_id,
                body={"name": file_metadata["name"], "parents": [new_folder_id]}
            ).execute()

            print(f"Copied file to new folder. New file ID: {copied_file['id']}")

            # Step 3: Delete the original file
            service.files().delete(fileId=file_id).execute()
            print(f"Deleted original file {file_id}")

            return  # Exit after copying and deleting

        # Step 4: Normal move operation if the file has parents
        current_folder_id = parents[0]
        print(f"Moving file {file_id} from {current_folder_id} to {new_folder_id}...")

        service.files().update(
            fileId=file_id,
            addParents=new_folder_id,
            removeParents=current_folder_id,
            fields="id, parents"
        ).execute()

        print(f"Successfully moved file {file_id} to folder {new_folder_id}")

    except HttpError as e:
        print(f"Google Drive API error: {e}")
    except Exception as e:
        print(f"Error moving file {file_id} to folder {new_folder_id}: {e}")

if __name__ == "__main__":
    service = get_drive_service()
    response = move_file_to_folder(service, "1v-D_oAvM7zujhNKSe5UL0XebJJA497JA", "1eLgeArBwyDZ6POMM2w4avZO4KfsUWPsV")
    if response:
        print(response)
    else:
        print("Failed to obtain response")