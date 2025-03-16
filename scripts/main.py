from audio_utils import process_audio_files, download_file
from upload_utils import get_drive_service
from pydub import AudioSegment
import os

def main():
    """Coordinate the entire audio processing and upload pipeline."""
    try:
        # Authenticate Google Drive service
        print("Authenticating Google Drive service...")
        print(os.getenv('GOOGLE_DRIVE_PRIVATE_KEY'))
        drive_service = get_drive_service()
        print("Google Drive service authenticated.")

        # Google Drive folder IDs
        input_folder_id = os.getenv('INPUT_FOLDER_ID')
        output_folder_id = os.getenv('OUTPUT_FOLDER_ID')

        if not input_folder_id or not output_folder_id:
            raise ValueError("Ensure INPUT_FOLDER_ID and OUTPUT_FOLDER_ID are set in environment variables.")

        # Load jingles
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
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()
