from audio_utils import process_audio_files, download_file
from upload_utils import find_asset_url
from kdrive_utils import get_kdrive_client
from pydub import AudioSegment
import psutil
import threading
import os
import time
from dotenv import load_dotenv

load_dotenv()

def log_memory_usage_periodically():
    """Log memory usage every 10 seconds."""
    process = psutil.Process(os.getpid())
    while True:
        memory_info = process.memory_info()
        print(f"[Memory Monitor] Memory usage: {memory_info.rss / 1024 ** 2:.2f} MB")
        time.sleep(10)  # Wait for 10 seconds before logging again

def main():
    """Coordinate the entire audio processing and upload pipeline."""
    try:
        # Start memory monitoring in a separate thread
        memory_thread = threading.Thread(target=log_memory_usage_periodically, daemon=True)
        memory_thread.start()

        # Authenticate kDrive service
        print("Connecting to kDrive...")
        kdrive_client = get_kdrive_client()
        print("kDrive client initialized.")

        # kDrive folder IDs
        input_folder_id = os.getenv('KDRIVE_INPUT_FOLDER_ID')

        if not input_folder_id:
            raise ValueError("Ensure KDRIVE_INPUT_FOLDER_ID is set in environment variables.")

        input_folder_id = int(input_folder_id)

        # Load start jingle from kDrive
        start_jingle_id = os.getenv('KDRIVE_START_JINGLE_ID')

        if not start_jingle_id:
            raise ValueError("KDRIVE_START_JINGLE_ID must be set in environment variables.")

        print(f"Loading start jingle from kDrive (file ID: {start_jingle_id})...")
        start_jingle = download_file(int(start_jingle_id))

        # Process audio files and upload results
        process_audio_files(
            folder_id=input_folder_id,
            start_jingle=start_jingle,
            end_jingle=None
        )
        print("Audio processing and uploads completed successfully.")

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()
