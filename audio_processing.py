from pydub import AudioSegment, silence
import io
import gc
import time  # Import time module for timing functions
from datetime import datetime  # Import for date parsing
from decouple import config
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

# Set up authentication using service account credentials
SCOPES = ['https://www.googleapis.com/auth/drive']
SERVICE_ACCOUNT_FILE = 'service_credentials.json'

credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES)

service = build('drive', 'v3', credentials=credentials)

# Function to find a folder by name within a specific parent folder
def find_folder_by_name(folder_name, parent_id):
    query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and '{parent_id}' in parents"
    response = service.files().list(q=query, spaces='drive').execute()
    folders = response.get('files', [])
    return folders[0]['id'] if folders else None

# Function to create a new folder in Google Drive or find it if it already exists
def create_or_get_folder(folder_name, parent_id):
    # Check if the folder already exists
    folder_id = find_folder_by_name(folder_name, parent_id)
    if folder_id:
        print(f"Folder '{folder_name}' already exists with ID: {folder_id}")
        return folder_id

    # Folder does not exist, so create it
    folder_metadata = {
        'name': folder_name,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [parent_id]
    }
    folder = service.files().create(body=folder_metadata, fields='id').execute()
    print(f"Created new folder '{folder_name}' with ID: {folder.get('id')}")
    return folder.get('id')

# Function to download a file by its ID and return as AudioSegment
def download_file(file_id):
    start_time = time.time()
    request = service.files().get_media(fileId=file_id)
    output = io.BytesIO()
    downloader = MediaIoBaseDownload(output, request)

    done = False
    while not done:
        status, done = downloader.next_chunk()
        print(f"Downloaded {int(status.progress() * 100)}%.")

    output.seek(0)
    end_time = time.time()
    print(f"Time taken to download file: {end_time - start_time:.2f} seconds")
    return AudioSegment.from_file(output)

# Function to ensure the audio file is in WAV format
def ensure_wav_format(audio_segment, file_extension):
    start_time = time.time()
    if file_extension.lower() != "wav":
        wav_output = io.BytesIO()
        audio_segment.export(wav_output, format="wav")
        wav_output.seek(0)
        end_time = time.time()
        print(f"Time taken to convert to WAV format: {end_time - start_time:.2f} seconds")
        return AudioSegment.from_wav(wav_output)
    end_time = time.time()
    print(f"Time taken to check WAV format: {end_time - start_time:.2f} seconds")
    return audio_segment

# Function to list files in a Google Drive folder and return their IDs
def get_file_ids_from_folder(folder_id):
    start_time = time.time()
    query = f"'{folder_id}' in parents"
    response = service.files().list(q=query).execute()
    files = response.get('files', [])
    
    end_time = time.time()
    print(f"Time taken to get file IDs from folder: {end_time - start_time:.2f} seconds")
    return {file['name']: file['id'] for file in files}

# Function to upload an audio file with metadata to Google Drive
def upload_to_drive(audio_segment, filename, folder_id, timestamp):
    start_time = time.time()

    file_stream = io.BytesIO()
    tags = {'artist': 'Radio Show', 'date': timestamp}
    audio_segment.export(file_stream, format="mp3", bitrate="192k", tags=tags)
    file_stream.seek(0)

    file_metadata = {
        'name': filename,
        'parents': [folder_id]
    }

    media = MediaIoBaseUpload(file_stream, mimetype='audio/mp3', resumable=True)
    uploaded_file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id'
    ).execute()

    end_time = time.time()
    print(f"Time taken to upload file '{filename}': {end_time - start_time:.2f} seconds")
    print(f"File '{filename}' uploaded to Google Drive with ID: {uploaded_file.get('id')}")

# Function to process audio files
def process_audio_files(folder_id, output_folder_id, start_jingle_wav, end_jingle_wav):
    file_ids = get_file_ids_from_folder(folder_id)

    # Process each show file
    for name, show_id in file_ids.items():
        file_extension = name.split('.')[-1]
        if file_extension.lower() in ('wav', 'mp3', 'ogg', 'flac'):
            try:
                start_time = time.time()
                date_str = name[:8]
                time_str = name[9:13]
                date = datetime.strptime(date_str, "%Y%m%d")
                timestamp = f"{date.strftime('%d %b')} {time_str[:2]}:{time_str[2:]}"

                folder_name = date.strftime('%d %b')
                day_folder_id = create_or_get_folder(folder_name, output_folder_id)

                show = download_file(show_id)
                if len(show) > 13000:
                    start_trim = silence.detect_leading_silence(show)
                    end_trim = silence.detect_leading_silence(show.reverse())
                    trimmed_show = show[start_trim:len(show) - end_trim]

                    start_jingle_end = start_jingle_wav[-5800:].fade_out(5800)
                    trimmed_start = trimmed_show[:5800].fade_in(5800)
                    blended_start = start_jingle_end.overlay(trimmed_start)

                    end_jingle_start = end_jingle_wav[:7200].fade_in(7200)
                    trimmed_end = trimmed_show[-7200:].fade_out(7200)
                    blended_end = trimmed_end.overlay(end_jingle_start)

                    final_output = (
                        start_jingle_wav[:-5800] +
                        blended_start +
                        trimmed_show[5800:-7200] +
                        blended_end +
                        end_jingle_wav[7200:]
                    )

                    output_filename = f"final_show_with_jingle_{name}"
                    upload_to_drive(final_output, output_filename, day_folder_id, timestamp)

                    del show, trimmed_show, final_output
                    gc.collect()
            except Exception as e:
                print(f"Error processing {name}: {e}")

        end_time = time.time()
        print(f"Total time taken to process files: {end_time - start_time:.2f} seconds")

# Folder IDs for the shows and the output folder
folder_id = config('FOLDER_ID')
output_folder_id = config('OUTPUT_FOLDER_ID')

# Fixed IDs for jingles
start_jingle_id = config('START_JINGLE_ID')
end_jingle_id = config('END_JINGLE_ID')

# Download jingles
start_jingle = download_file(start_jingle_id)
end_jingle = download_file(end_jingle_id)

# Ensure jingles are in WAV format once before processing audio files
start_jingle_wav = ensure_wav_format(start_jingle, "wav")
end_jingle_wav = ensure_wav_format(end_jingle, "wav")

# Process audio files from the specified folder and output to the target folder, passing jingles
process_audio_files(folder_id, output_folder_id, start_jingle_wav, end_jingle_wav)
