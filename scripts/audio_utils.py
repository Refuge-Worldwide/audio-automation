from pydub import AudioSegment, silence
import io
import time
import gc
from datetime import datetime
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from upload_utils import get_show_from_timestamp, upload_to_soundcloud_with_metadata  # Import from the upload script
from error_handling import send_error_to_slack

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


def process_audio_files(service, folder_id, start_jingle, end_jingle):
    """Process audio files from the given folder."""
    def get_file_ids_from_folder(service, folder_id):
        query = f"'{folder_id}' in parents"
        response = service.files().list(q=query).execute()
        return {file['name']: file['id'] for file in response.get('files', [])}

    file_ids = get_file_ids_from_folder(service, folder_id)

    for name, show_id in file_ids.items():
        file_extension = name.split('.')[-1].lower()
        if file_extension in ('wav', 'mp3'):
            try:
                start_time = time.time()
                date_str = name[:8]
                time_str = name[9:13]
                date = datetime.strptime(date_str, "%Y%m%d")
                timestamp = f"{date.strftime('%d %b')} {time_str[:2]}:{time_str[2:]}"
                folder_name = date.strftime('%d %b')

                show = download_file(service, show_id)
                print("beginning to process audio")
                if len(show) > 1800000:
                    start_trim = silence.detect_leading_silence(show)
                    end_trim = silence.detect_leading_silence(show.reverse())
                    trimmed_show = show[start_trim:len(show) - end_trim]

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

                    print("finished to process audio")

                    sc_link = upload_to_soundcloud_with_metadata(final_output, timestamp)
                    print(f"SoundCloud link: {sc_link}")

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
