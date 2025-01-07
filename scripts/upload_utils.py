from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google.oauth2 import service_account
import io
import os
import requests
from datetime import datetime, timedelta
import psycopg2
from dotenv import load_dotenv
load_dotenv()

# Load environment variables
SCOPES = ['https://www.googleapis.com/auth/drive']
SUPABASE_URL = "https://oviucrnsbztpafeijwbt.supabase.co"

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
    """Fetch the SoundCloud token and refresh it if expired."""
    conn = psycopg2.connect(
        host=SUPABASE_URL,
        dbname="postgres",
        user="postgres",
        password=os.getenv("SUPABASE_TOKEN"),
        port=5432
    )

    with conn.cursor() as cur:
        cur.execute("SELECT token, refresh_token, expires FROM accessTokens WHERE application = 'soundcloud' LIMIT 1;")
        result = cur.fetchone()
        token, refresh_token, expires = result
        now = datetime.now()

        if now >= expires:
            response = requests.post(
                "https://api.soundcloud.com/oauth2/token",
                data={
                    "client_id": os.getenv("SC_CLIENT_ID"),
                    "client_secret": os.getenv("SC_CLIENT_SECRET"),
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token
                }
            )
            response.raise_for_status()
            data = response.json()

            cur.execute(
                """UPDATE accessTokens
                SET token = %s, refresh_token = %s, expires = %s
                WHERE application = 'soundcloud';""",
                (data['access_token'], data['refresh_token'], datetime.now() + timedelta(seconds=data['expires_in']))
            )
            conn.commit()

            return data['access_token']
        return token

def upload_to_soundcloud(audio_file_path, title, description):
    """Upload audio to SoundCloud."""
    token = get_soundcloud_token()
    with open(audio_file_path, 'rb') as audio_file:
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
        response.raise_for_status()
        data = response.json()
        return data['permalink_url']

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
