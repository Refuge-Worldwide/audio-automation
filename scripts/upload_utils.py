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
from kirby_utils import get_episode_by_timestamp
import json
import base64
import time

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

    # Retrieve the access token, refresh token and expiration time from supabase
    try:
        response = supabase.from_("accessTokens").select("*").eq("application", "soundcloud").execute()
        
        if not response.data or len(response.data) == 0:
            raise Exception("No SoundCloud token found in Supabase. Please run sc_token_insert.py first to initialize tokens.")
        
        token_data = response.data[0]
        access_token = token_data["token"]
        refresh_token = token_data["refresh_token"]
        expires_at = token_data["expires"]
    except Exception as e:
        error_message = f"Failed to retrieve SoundCloud token from Supabase: {e}"
        print(error_message)
        send_error_to_slack(error_message)
        raise

    #convert expiration time to datetime object
    expires_at_date_object = datetime.strptime(expires_at, "%Y-%m-%dT%H:%M:%S%z")

    # If the access token has expired, refresh it
    if datetime.now(timezone.utc) >= expires_at_date_object:
        print("Access token expired, refreshing...")
        refresh_url = "https://secure.soundcloud.com/oauth/token"
        
        client_id = os.getenv("SC_CLIENT_ID") or os.getenv("SOUNDCLOUD_CLIENT_ID")
        client_secret = os.getenv("SC_CLIENT_SECRET") or os.getenv("SOUNDCLOUD_CLIENT_SECRET")
        
        if not client_id or not client_secret:
            error_message = "SC_CLIENT_ID and SC_CLIENT_SECRET environment variables are required"
            print(error_message)
            send_error_to_slack(error_message)
            return None
        
        data = {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
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
            error_message = f"Failed to refresh access token: {response.status_code} - {response.text}"
            print(error_message)
            send_error_to_slack(error_message)
            return None

    return access_token

def upload_to_soundcloud(audio_file, show_metadata):
    """Upload audio to SoundCloud."""
    import json
    def download_image(image_url):
        response = requests.get(image_url)
        response.raise_for_status()  # Raise an exception if the image download fails
        return response.content  # Return the raw image data

    # Image URL from show metadata
    image_url = show_metadata.get("artwork", "")
    
    # Handle artwork URL - add https: if it's a protocol-relative URL
    # Skip artwork if running on localhost since SoundCloud can't access it
    if image_url:
        if "localhost" in image_url or image_url.startswith("/"):
            print("Warning: Artwork is on localhost, skipping (SoundCloud can't access local files)")
            image_url = None
        elif image_url.startswith("//"):
            image_url = "https:" + image_url
        elif not image_url.startswith("http"):
            print(f"Warning: Invalid artwork URL: {image_url}, skipping artwork")
            image_url = None

    # Download the image if we have a valid URL
    image_data = None
    if image_url:
        try:
            image_data = download_image(image_url)
        except Exception as e:
            print(f"Warning: Failed to download artwork: {e}, continuing without artwork")
            image_data = None

    #
    try:
        # Get the SoundCloud token
        token = get_soundcloud_token()
        print(f"Using token: {token}")

        # Create the filename with current timestamp
        current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{current_time}.mp3"

        # Prepare files dict - only include artwork if we have image data
        files_dict = {
            "track[asset_data]": (filename, audio_file, "audio/mpeg")
        }
        
        if image_data:
            files_dict["track[artwork_data]"] = ("artwork.png", image_data, "image/png")

        # Send the POST request to SoundCloud with the token in the Authorization header
        response = requests.post(
            "https://api.soundcloud.com/tracks",
            headers={"Authorization": f"OAuth {token}"},
            files=files_dict,
            data={
                "track[title]": show_metadata["title"],
                "track[description]": show_metadata["description"],
                "track[tag_list]": " ".join([f"\"{genre}\"" for genre in show_metadata.get("genres", [])]),
                "track[sharing]": "private",
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

# Function to update the SoundCloud link and audio file for a show in Contentful
def update_show(entry_id, name, sc_link, audio_file):
    """
    Update show entry with SoundCloud link and audio file.
    Routes to appropriate CMS based on CMS_TYPE environment variable.
    
    Args:
        entry_id: The ID/slug of the show entry
        name: Title of the show
        sc_link: URL of the uploaded SoundCloud track
        audio_file: BytesIO object containing the audio file
    """
    cms_type = os.getenv('CMS_TYPE', 'kirby').lower()
    
    if cms_type == 'kirby':
        _update_kirby_show(entry_id, sc_link)
    elif cms_type == 'contentful':
        _update_contentful_show(entry_id, name, sc_link, audio_file)
    else:
        print(f"Warning: Unsupported CMS_TYPE: {cms_type}. Skipping CMS update.")


def _update_kirby_show(entry_id, sc_link):
    """Update show in Kirby CMS with SoundCloud link."""
    from kirby_utils import update_episode
    
    try:
        update_episode(
            episode_id=entry_id,
            soundcloud_url=sc_link
        )
        print(f"Updated Kirby CMS for episode: {entry_id}")
    except Exception as e:
        print(f"Failed to update Kirby CMS: {e}")
        raise


def _update_contentful_show(entry_id, name, sc_link, audio_file):
    """Update show in Contentful CMS with SoundCloud link and audio file."""
    space_id = os.getenv('CONTENTFUL_SPACE_ID')
    environment_id = os.getenv('CONTENTFUL_ENVIRONMENT', 'master')
    token = os.getenv('CONTENTFUL_TOKEN')
    
    if not all([space_id, token]):
        print("Warning: Contentful credentials not configured. Skipping Contentful update.")
        return
    
    try:
        audio_file.seek(0)

        client = contentful_management.Client(token)
        space = client.spaces().find(space_id)
        environment = space.environments().find(environment_id)
        
        upload = space.uploads().create(audio_file)
        print(f"File uploaded with ID: {upload.sys['id']}")

        # Step 2: Create an asset and link the uploaded file
        asset = environment.assets().create(
            None,
            {
                "fields": {
                    "title": {
                        "en-US": name
                    },
                    "file": {
                        "en-US": {
                            "uploadFrom": {
                                "sys": {
                                    "type": "Link",
                                    "linkType": "Upload",
                                    "id": upload.sys['id']
                                }
                            },
                            "fileName": f"{name}.mp3",
                            "contentType": "audio/mpeg"
                        }
                    }
                }
            }
        )
        print(f"Asset created with ID: {asset.sys['id']}")

        asset.process()
        
        # TODO: Fix asset publishing, possibly have to wait for asset to finish
        # processing but asset.process() is not an async function.

        print(f"Audio file uploaded and published as asset: {asset.sys['id']}")

        # Step 2: Update the entry with the SoundCloud link and audio asset
        entry = environment.entries().find(entry_id)
        entry.fields('en-US')['mixcloudLink'] = sc_link
        entry.fields('en-US')['audioFile'] = {
            "sys": {
                "type": "Link",
                "linkType": "Asset",
                "id": asset.sys['id']
            }
        }
        entry.save()

        # Wait for asset to finish processing. It will have a URL when it has.
        # Will timeout after 240 seconds.
        start_time = time.time()
        while True:
            newAsset = environment.assets().find(asset.sys['id'])
            if 'file' in newAsset.fields() and 'url' in newAsset.fields()['file']:
                print(f"Asset processed successfully.")
                # Publish the asset
                newAsset.publish()
                break
            elapsed_time = time.time() - start_time
            if elapsed_time > 240:
                raise TimeoutError("Asset processing timed out after 240 seconds.")
                break
            print("Waiting for asset to be processed...")
            time.sleep(5)  # Wait for 5 seconds before checking again

        # Publish the show
        entry.publish()

        print(f"SoundCloud link and audio file updated for entry ID {entry_id}.")

    except Exception as e:
        error_message = f"Error updating show {entry_id} with SoundCloud link and audio file: {str(e)}"
        send_error_to_slack(error_message)
        print(error_message)

def find_asset_url():
    client = contentful_management.Client(CONTENTFUL_MANAGEMENT_API_TOKEN)
    space = client.spaces().find(CONTENTFUL_SPACE_ID)
    environment = space.environments().find(CONTENTFUL_ENV_ID)


    asset = environment.assets().find("46Qi3spciOmdruadxGHtO5")
    print(asset)
    if 'file' in asset.fields() and 'url' in asset.fields()['file']:
        print("YES WE HAVE A URL")

def delete_repeat_from_contentful(entry_id):
    """Delete a show from contentful, used when its a repeat on the schedule."""
    try:
        # Initialize the Contentful Management client
        client = contentful_management.Client(CONTENTFUL_MANAGEMENT_API_TOKEN)
        space = client.spaces().find(CONTENTFUL_SPACE_ID)
        environment = space.environments().find(CONTENTFUL_ENV_ID)

        # Find the show by ID
        entry = environment.entries().find(entry_id)

        # Unpublish the show, required so it can be deleted
        entry.unpublish()

        # Delete the show
        entry.delete()
        print(f"Entry with ID {entry_id} has been deleted successfully.")

    except Exception as e:
        error_message = f"Error deleting repeat show with ID {entry_id}: {str(e)}"
        send_error_to_slack(error_message)

def get_show_from_timestamp(timestamp):
    try:            
        api_url = os.getenv('WEBSITE_API_URL')
        if not api_url:
            raise ValueError("WEBSITE_API_URL environment variable is not set")
        
        # Ensure the URL ends with the correct endpoint
        base_url = api_url.rstrip('/')
        if not base_url.endswith('/api/episode-by-timestamp'):
            base_url = base_url.replace('/api/episode-by-timestamp', '') + '/api/episode-by-timestamp'
        
        response = requests.get(f"{base_url}?t={timestamp}")
        response.raise_for_status()  # Raise an exception for HTTP errors
        show = response.json()  # Parse the JSON response
        return show
    except requests.RequestException as e:
        error_message = f"Error fetching show for timestamp {timestamp}: {e}"
        print(error_message)
        send_error_to_slack(error_message)
        return None

    
def fetch_show_details(timestamp):
    """
    Fetch show details from CMS (Contentful or Kirby) by timestamp.
    
    Args:
        timestamp: Timestamp in format YYYYMMDD-HHMM
        
    Returns:
        Dictionary with show metadata or None if not found
    """
    cms_type = os.getenv('CMS_TYPE', 'kirby').lower()
    
    if cms_type == 'kirby':
        return _fetch_show_from_kirby(timestamp)
    elif cms_type == 'contentful':
        return _fetch_show_from_contentful(timestamp)
    else:
        raise ValueError(f"Unsupported CMS_TYPE: {cms_type}. Use 'contentful' or 'kirby'")


def _fetch_show_from_kirby(timestamp):
    """Fetch show details from Kirby CMS."""
    show = get_episode_by_timestamp(timestamp)
    
    if not show:
        error_message = f"No show found for timestamp {timestamp}"
        print(error_message)
        send_error_to_slack(error_message)
        return None
    
    show_metadata = {}
    
    try:
        date_obj = datetime.strptime(timestamp, "%Y%m%d-%H%M")
        formatted_date = date_obj.strftime("%d %b %Y")

        # Parse title - handle both "show | artist" and plain title formats
        # Ensure title is a string (handle None case)
        title = show.get("title") or ""
        if " | " in title:
            show_name, artists = title.split(" | ", 1)
            final_title = f"{show_name} - {artists} - {formatted_date}"
        else:
            final_title = f"{title} - {formatted_date}" if title else f"Unknown Show - {formatted_date}"

        show_metadata["entry_id"] = show.get("id") or show.get("slug", "")
        show_metadata["slug"] = show.get("slug", "")
        show_metadata["title"] = final_title

        # Get description from Kirby API and append website URL
        kirby_description = show.get("description") or ""
        show_metadata["description"] = f"{kirby_description}\n\nhttps://transition-radio.com/" if kirby_description else "https://transition-radio.com/"

        show_metadata["artwork"] = show.get("artwork") or ""
        show_metadata["genres"] = show.get("genres") or []

        return show_metadata

    except Exception as e:
        error_message = f"Error parsing show metadata for timestamp {timestamp}: {e}"
        print(error_message)
        send_error_to_slack(error_message)
        return None


def _fetch_show_from_contentful(timestamp):
    """Fetch show details from Contentful CMS."""
    space_id = os.getenv('CONTENTFUL_SPACE_ID')
    environment_id = os.getenv('CONTENTFUL_ENVIRONMENT', 'master')
    token = os.getenv('CONTENTFUL_TOKEN')
    
    if not all([space_id, token]):
        raise ValueError("Contentful credentials not configured. Set CONTENTFUL_SPACE_ID and CONTENTFUL_TOKEN.")
    
    try:
        client = contentful_management.Client(token)
        # Query entries by timestamp - adjust field name based on your content model
        entries = client.entries(space_id, environment_id).all({
            'content_type': 'show',
            'fields.timestamp': timestamp
        })
        
        if not entries or len(entries) == 0:
            error_message = f"No show found for timestamp {timestamp} in Contentful"
            print(error_message)
            send_error_to_slack(error_message)
            return None
        
        show = entries[0]
        date_obj = datetime.strptime(timestamp, "%Y%m%dT%H%M")
        formatted_date = date_obj.strftime("%d %b %Y")
        
        title = show.title if hasattr(show, 'title') else 'Unknown Show'
        
        show_metadata = {
            "entry_id": show.id,
            "slug": show.slug if hasattr(show, 'slug') else show.id,
            "title": f"{title} - {formatted_date}",
            "description": show.description if hasattr(show, 'description') else "",
            "artwork": show.artwork if hasattr(show, 'artwork') else "",
            "genres": show.genres if hasattr(show, 'genres') else []
        }
        
        return show_metadata
        
    except Exception as e:
        error_message = f"Error fetching from Contentful for timestamp {timestamp}: {e}"
        print(error_message)
        send_error_to_slack(error_message)
        return None

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