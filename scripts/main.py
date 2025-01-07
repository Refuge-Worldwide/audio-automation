print("Attempting to import audio_utils and pydub...")
from audio_utils import process_audio_files
print("Attempting to import audio_utils and pydub...")
from upload_utils import get_drive_service
print("Attempting to import audio_utils and pydub...")
from pydub import AudioSegment
print("Attempting to import audio_utils and pydub...")

import os
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))


def load_jingles():
    """Load the start and end jingles from the local file system."""
    start_jingle_path = os.getenv('START_JINGLE_PATH', 'start_jingle.mp3')
    end_jingle_path = os.getenv('END_JINGLE_PATH', 'end_jingle.mp3')

    if not os.path.exists(start_jingle_path) or not os.path.exists(end_jingle_path):
        raise FileNotFoundError("Ensure the start and end jingles exist in the specified paths.")
    
    start_jingle = AudioSegment.from_file(start_jingle_path)
    end_jingle = AudioSegment.from_file(end_jingle_path)

    return start_jingle, end_jingle

def main():
    """Coordinate the entire audio processing and upload pipeline."""
    try:
        # Authenticate Google Drive service
        drive_service = get_drive_service()

        # Google Drive folder IDs
        input_folder_id = os.getenv('INPUT_FOLDER_ID')
        output_folder_id = os.getenv('OUTPUT_FOLDER_ID')

        if not input_folder_id or not output_folder_id:
            raise ValueError("Ensure INPUT_FOLDER_ID and OUTPUT_FOLDER_ID are set in environment variables.")

        # Load jingles
        start_jingle, end_jingle = load_jingles()

        # Process audio files and upload results
        process_audio_files(
            service=drive_service,
            folder_id=input_folder_id,
            output_folder_id=output_folder_id,
            start_jingle=start_jingle,
            end_jingle=end_jingle
        )
        print("Audio processing and uploads completed successfully.")

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()
