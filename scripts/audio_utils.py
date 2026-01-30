from pydub import AudioSegment, silence
import io
import time
import gc
import requests
from datetime import datetime, timedelta
from kdrive_utils import get_kdrive_client, download_file_as_audio, get_file_ids_from_folder as kdrive_get_files, move_file_to_folder as kdrive_move_file
from upload_utils import upload_to_soundcloud, fetch_show_details, update_show, delete_repeat_from_contentful
from error_handling import send_error_to_slack
import os
from dotenv import load_dotenv

load_dotenv()

def download_file(file_id):
    """Download a file by its ID from kDrive and return as an AudioSegment."""
    start_time = time.time()

    # Use kDrive client to download
    audio = download_file_as_audio(file_id)

    end_time = time.time()
    print(f"Time taken to download file: {end_time - start_time:.2f} seconds")
    return audio

def download_file_from_url(url):
    """Download an audio file from a URL and return as an AudioSegment."""
    start_time = time.time()

    print(f"Downloading file from URL: {url}")
    response = requests.get(url, stream=True)

    if response.status_code != 200:
        raise Exception(f"Failed to download file from URL: {response.status_code}")

    # Read content into BytesIO
    file_data = io.BytesIO()
    for chunk in response.iter_content(chunk_size=8192):
        if chunk:
            file_data.write(chunk)

    file_data.seek(0)

    # Determine audio format from URL
    file_extension = url.split('.')[-1].split('?')[0].lower()  # Handle query params
    if file_extension not in ['mp3', 'wav', 'flac', 'ogg', 'm4a']:
        file_extension = 'mp3'  # Default to mp3

    print(f"Converting to AudioSegment (format: {file_extension})...")
    audio = AudioSegment.from_file(file_data, format=file_extension)

    end_time = time.time()
    print(f"Time taken to download and process file: {end_time - start_time:.2f} seconds")
    return audio

def format_time(ms):
    seconds = ms // 1000
    minutes = seconds // 60
    hours = minutes // 60
    return f"{hours:02}:{minutes % 60:02}:{seconds % 60:02}"

def process_audio_files(folder_id, start_jingle, end_jingle):
    """Process audio files from the given kDrive folder."""
    files = kdrive_get_files(folder_id)
    PROCESSED_FOLDER_ID = int(os.getenv("KDRIVE_BACKUP_FOLDER_ID"))

    for file_info in files:
        file_id = file_info['id']
        filename = file_info['name']
        file_extension = filename.split('.')[-1].lower()
        
        if file_extension in ('wav', 'mp3'):
            try:
                start_time = time.time()
                
                # Extract timestamp from filename (format: YYYYMMDD-HHMM or YYYYMMDD_HHMM)
                # Remove file extension first
                name_without_ext = filename.rsplit('.', 1)[0]
                
                # Check if filename follows expected format (YYYYMMDD-HHMM or YYYYMMDD_HHMM)
                if len(name_without_ext) < 13 or not name_without_ext[:8].isdigit():
                    print(f"Skipping {filename} - filename doesn't match expected format YYYYMMDD-HHMM or YYYYMMDD_HHMM")
                    continue
                
                # Handle both dash and underscore separators
                if name_without_ext[8] in ['-', '_']:
                    date_str = name_without_ext[:8]  # Extract "YYYYMMDD"
                    time_str = name_without_ext[9:13]  # Extract "HHMM"
                else:
                    print(f"Skipping {filename} - invalid separator at position 8")
                    continue

                # Convert to datetime object
                date_time = datetime.strptime(f"{date_str} {time_str}", "%Y%m%d %H%M")

                # Add 15 minutes to the datetime object
                date_time += timedelta(minutes=15)

                # Format as "YYYYMMDD-HHMM"
                timestamp = date_time.strftime("%Y%m%d-%H%M")
                print(f"Processing file: {filename}")
                print(f"Timestamp: {timestamp}")
                show = download_file(file_id)

                # If show length is short then don't process
                # if len(show) < 1800000:
                #     print("Not processing show as its too small")
                #     kdrive_move_file(show_id, PROCESSED_FOLDER_ID)
                #     continue

                # Fetch metadata about show based on timestamp
                show_metadata = fetch_show_details(timestamp)

                # If no show metadata found, skip this file and move to processed folder
                if not show_metadata:
                    print(f"No show metadata found for timestamp {timestamp}, skipping file and moving to processed folder")
                    kdrive_move_file(file_id, PROCESSED_FOLDER_ID)
                    continue

                # If the show is a repeat then delete from contentful and don't process
                if "(r)" in show_metadata['title']:
                    print("Deleting show as its a repeat")
                    delete_repeat_from_contentful(show_metadata["entry_id"])
                    kdrive_move_file(file_id, PROCESSED_FOLDER_ID)
                    continue

                print("beginning to process audio")

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

                # Get the length of the start jingle
                jingle_length = len(start_jingle)
                print(f"Start jingle length: {jingle_length} ms ({jingle_length / 1000:.2f} seconds)")

                # Combine start jingle with the show - no blending, just concatenate
                if end_jingle is not None:
                    # Legacy behavior: add end jingle
                    end_jingle_start = end_jingle[:7200].fade_in(7200)
                    trimmed_end = trimmed_show[-7200:].fade_out(7200)
                    blended_end = trimmed_end.overlay(end_jingle_start)

                    final_output = (
                        start_jingle +
                        trimmed_show[:-7200] +
                        blended_end +
                        end_jingle[7200:]
                    )
                else:
                    # No end jingle: just add start jingle and fade out the end
                    final_output = (
                        start_jingle +
                        trimmed_show.fade_out(2000)  # Fade out last 2 seconds
                    )

                print("finished processing audio")

                # Convert the AudioSegment to a BytesIO object
                audio_file = io.BytesIO()
                final_output.export(audio_file, format="mp3", bitrate="192k")
                audio_file.seek(0)  # Reset file pointer

                # Validate the BytesIO object content
                if audio_file.getbuffer().nbytes == 0:
                    raise ValueError("CCCC The exported audio file is empty. Please check the export operation.")

                # Upload to soundcloud
                sc_link = upload_to_soundcloud(audio_file, show_metadata)

                # Update show on CMS (Contentful or Kirby). Uploading audio file and updating soundcloud link
                entry_id = show_metadata["entry_id"]
                entry_title = show_metadata["title"]
                update_show(entry_id, entry_title, sc_link, audio_file)

                print(f"SoundCloud link: {sc_link}")

                # Move the file after successful upload
                kdrive_move_file(file_id, PROCESSED_FOLDER_ID)

                del show, trimmed_show, final_output, audio_file
                gc.collect()
            except Exception as e:
                error_message = f"Error processing audio {filename}: {e}"
                send_error_to_slack(error_message)
                print(error_message)
                
                # TODO: Add retry logic
                continue

            end_time = time.time()
            print(f"Processed {filename} in {end_time - start_time:.2f} seconds")
