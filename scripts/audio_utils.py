from pydub import AudioSegment, silence
import io
import time
import gc
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from upload_utils import move_file_to_folder, upload_to_soundcloud_with_metadata  # Import from the upload script
from error_handling import send_error_to_slack
import os
from dotenv import load_dotenv

load_dotenv()

def download_file(service, file_id):
    """Download a file by its ID and return as an AudioSegment."""

    # TODO: Add error handling to this function. Perhaps a timeout for downloading.
    start_time = time.time()
    request = service.files().get_media(fileId=file_id)
    output = io.BytesIO()
    downloader = MediaIoBaseDownload(output, request)

    done = False
    while not done:
        status, done = downloader.next_chunk()
        print(f"Downloaded {int(status.progress() * 100)}%")
        if done:
            print("Download complete.")
        else:
            print("Downloading...")

    output.seek(0)  # Ensure file pointer is at the beginning after download
    file_size = len(output.getvalue())  # Get the size of the downloaded file
    print(f"Downloaded file size: {file_size} bytes")
    end_time = time.time()
    print(f"Time taken to download file: {end_time - start_time:.2f} seconds")
    return AudioSegment.from_file(output)

def get_file_ids_from_folder(service, folder_id):
    query = f"'{folder_id}' in parents"
    response = service.files().list(q=query).execute()
    return {file['name']: file['id'] for file in response.get('files', [])}

def format_time(ms):
    seconds = ms // 1000
    minutes = seconds // 60
    hours = minutes // 60
    return f"{hours:02}:{minutes % 60:02}:{seconds % 60:02}"

def process_audio_files(service, folder_id, start_jingle, end_jingle):
    """Process audio files from the given folder."""
    file_ids = get_file_ids_from_folder(service, folder_id)

    for name, show_id in file_ids.items():
        file_extension = name.split('.')[-1].lower()
        if file_extension in ('wav', 'mp3'):
            try:
                start_time = time.time()
                date_str = name[:8]  # Extract "YYYYMMDD"
                time_str = name[9:13]  # Extract "HHMM"

                # Convert to datetime object
                date_time = datetime.strptime(f"{date_str} {time_str}", "%Y%m%d %H%M")

                # Add 15 minutes to the datetime object
                date_time += timedelta(minutes=15)

                # Format as "YYYYMMDDTHH15"
                timestamp = date_time.strftime("%Y%m%dT%H%M")
                show = download_file(service, show_id)
                print("beginning to process audio")
                if len(show) > 1800000:
                    # Detect silences longer than 5 seconds (3000 ms)
                    silent_ranges = silence.detect_silence(show, min_silence_len=5000, seek_step=100, silence_thresh=-50)

                    # Flatten the list of silent ranges
                    silent_ranges = [item for sublist in silent_ranges for item in sublist]

                    # Convert silent ranges to readable format
                    formatted_silent_ranges = [(format_time(start), format_time(end)) for start, end in zip(silent_ranges[::2], silent_ranges[1::2])]
                    print(f"Silent ranges (start, end): {formatted_silent_ranges}")

                    # Remove the silent ranges from the audio
                    segments = []
                    start = 0
                    for i in range(0, len(silent_ranges), 2):
                        segments.append(show[start:silent_ranges[i]])
                        start = silent_ranges[i + 1]
                    segments.append(show[start:])

                    # Concatenate the segments to form the final audio without long silences
                    trimmed_show = sum(segments, AudioSegment.silent(duration=0))

                    start_jingle_end = start_jingle[-5800:].fade_out(5800)
                    trimmed_start = trimmed_show[:5800].fade_in(5800)
                    blended_start = start_jingle_end.overlay(trimmed_start)

                    end_jingle_start = end_jingle[:7200].fade_in(7200)
                    trimmed_end = trimmed_show[-7200:].fade_out(7200)
                    blended_end = trimmed_end.overlay(end_jingle_start)

                    final_output = (
                        start_jingle[:-5800] +
                        blended_start +
                        trimmed_show[5800:-7200] +
                        blended_end +
                        end_jingle[7200:]
                    )

                    print("finished processing audio")

                    sc_link = upload_to_soundcloud_with_metadata(final_output, timestamp)
                    print(f"SoundCloud link: {sc_link}")
                    # Define the processed files folder ID (replace with actual ID)
                    PROCESSED_FOLDER_ID = os.getenv("BACKUP_FOLDER_ID")

                    # Move the file after successful upload
                    move_file_to_folder(service, show_id, PROCESSED_FOLDER_ID)

                    del show, trimmed_show, final_output
                    gc.collect()
            except Exception as e:
                error_message = f"Error processing audio {name}: {e}"
                send_error_to_slack(error_message)
                print(error_message)
                
                # TODO: Add retry logic
                continue

            end_time = time.time()
            print(f"Processed {name} in {end_time - start_time:.2f} seconds")
