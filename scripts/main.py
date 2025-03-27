from audio_utils import process_audio_files, download_file
from upload_utils import get_drive_service
from pydub import AudioSegment
import psutil
import threading
import os
import time
import logging
import builtins

def log_memory_usage_periodically():
    logger = setup_logging()  # Set up logging


    """Log memory usage every 10 seconds."""
    process = psutil.Process(os.getpid())
    while True:
        memory_info = process.memory_info()
        logger.info(f"[Memory Monitor] Memory usage: {memory_info.rss / 1024 ** 2:.2f} MB")
        time.sleep(1)  # Wait for 10 seconds before logging again

def setup_logging():
    """Set up logging to log to both console and a file."""
    logger = logging.getLogger("AudioAutomationLogger")
    logger.setLevel(logging.INFO)

    # Create a console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    # Create a file handler
    # file_handler = logging.FileHandler("server_logs.log")  # Logs will be saved to this file
    # file_handler.setLevel(logging.INFO)

    # Create a logging format
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)
    # file_handler.setFormatter(formatter)

    # Add handlers to the logger
    logger.addHandler(console_handler)
    # logger.addHandler(file_handler)

    # Override the built-in print function
    builtins.print = lambda *args, **kwargs: logger.info(" ".join(map(str, args)))

    return logger

def main():
    logger = setup_logging()  # Set up logging

    """Coordinate the entire audio processing and upload pipeline."""
    try:
        # Start memory monitoring in a separate thread
        memory_thread = threading.Thread(target=log_memory_usage_periodically, daemon=True)
        memory_thread.start()

        # Authenticate Google Drive service
        logger.info("Authenticating Google Drive service...")
        drive_service = get_drive_service()
        logger.info("Google Drive service authenticated.")

        # Google Drive folder IDs
        input_folder_id = os.getenv('INPUT_FOLDER_ID')
        output_folder_id = os.getenv('OUTPUT_FOLDER_ID')

        if not input_folder_id or not output_folder_id:
            raise ValueError("Ensure INPUT_FOLDER_ID and OUTPUT_FOLDER_ID are set in environment variables.")

        # Load jingles as audio segment
        start_jingle, end_jingle = download_file(drive_service, os.getenv('START_JINGLE_ID')),  download_file(drive_service, os.getenv('END_JINGLE_ID'))

        # Process audio files and upload results
        process_audio_files(
            service=drive_service,
            folder_id=input_folder_id,
            start_jingle=start_jingle,
            end_jingle=end_jingle
        )
        print("Audio processing and uploads completed successfully.")

    except Exception as e:
        logger.error(f"An error occurred: {e}")

if __name__ == "__main__":
    main()
