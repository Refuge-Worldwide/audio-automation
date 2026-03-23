#!/usr/bin/env python3
"""
Script to download audio from Soundcloud/Mixcloud for shows missing audio files in Contentful.
- Fetches all shows from Contentful
- Filters shows without audioFile field
- Skips shows with (r) in the title (repeats)
- Downloads audio from mixcloudLink using yt-dlp (for Soundcloud/Mixcloud links)
"""

import os
import sys
import re
import subprocess
import logging
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv
import contentful_management
import time

# Load environment variables
load_dotenv()

# Setup logging
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)
log_filename = LOG_DIR / f"download_audio_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

# Configure logging to both file and console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_filename),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

CONTENTFUL_SPACE_ID = os.getenv('CONTENTFUL_SPACE_ID')
CONTENTFUL_ENV_ID = os.getenv('CONTENTFUL_ENV_ID')
CONTENTFUL_MANAGEMENT_API_TOKEN = os.getenv('CONTENTFUL_MANAGEMENT_API_TOKEN') or os.getenv('CONTENTFUL_MANAGEMENT_ACCESS_TOKEN')

# Create downloads directory if it doesn't exist
DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)


def is_soundcloud_link(url):
    """Check if the URL is a Soundcloud link."""
    return 'soundcloud.com' in url.lower()


def is_mixcloud_link(url):
    """Check if the URL is a Mixcloud link."""
    return 'mixcloud.com' in url.lower()


def has_repeat_marker(title):
    """Check if the title contains (r) marker indicating a repeat."""
    return '(r)' in title.lower()


def download_audio_with_ytdlp(url, output_path):
    """
    Download audio from URL using yt-dlp.

    Args:
        url: The URL to download from
        output_path: Path where the audio file should be saved

    Returns:
        bool: True if download was successful, False otherwise
    """
    try:
        # yt-dlp options for audio download with best quality
        cmd = [
            'yt-dlp',
            '-f', 'bestaudio',  # Select best available audio stream
            '--extract-audio',
            '--audio-format', 'mp3',
            '--audio-quality', '0',  # Best quality for conversion
            '--embed-thumbnail',  # Embed thumbnail if available
            '--add-metadata',  # Add metadata to the file
            '--output', str(output_path),
            '--progress',  # Show progress
            url
        ]

        logger.info(f"Starting download from: {url}")
        logger.debug(f"Command: {' '.join(cmd)}")

        # Run yt-dlp without capturing output so progress is shown in real-time
        result = subprocess.run(cmd, text=True)

        if result.returncode == 0:
            logger.info(f"✓ Successfully downloaded to: {output_path}")
            # Verify file exists
            if Path(output_path).exists():
                file_size = Path(output_path).stat().st_size / (1024 * 1024)  # MB
                logger.info(f"  File size: {file_size:.2f} MB")
            return True
        else:
            logger.error(f"✗ Download failed with return code: {result.returncode}")
            return False

    except Exception as e:
        error_message = f"Error downloading audio from {url}: {str(e)}"
        logger.error(error_message)
        return False


def get_shows_without_audio():
    """
    Fetch all shows from Contentful that don't have an audioFile field.

    Returns:
        list: List of show entries missing audio files
    """
    try:
        logger.info("Connecting to Contentful...")
        client = contentful_management.Client(CONTENTFUL_MANAGEMENT_API_TOKEN)
        space = client.spaces().find(CONTENTFUL_SPACE_ID)
        environment = space.environments().find(CONTENTFUL_ENV_ID)
        logger.info("✓ Connected to Contentful successfully")

        # Fetch all entries of content type 'show', ordered by creation date (newest first)
        # Note: You may need to adjust 'show' to match your actual content type ID
        # Filter to only get shows from yesterday or earlier, without audio file, but with mixcloudLink
        yesterday = (datetime.now() - timedelta(days=1)).replace(hour=23, minute=59, second=59).isoformat()
        logger.info(f"Fetching shows from yesterday or earlier without audio but with mixcloudLink...")
        entries = environment.entries().all({
            'content_type': 'show',
            'limit': 1000,
            'order': '-sys.createdAt',  # Newest first
            'fields.date[lt]': yesterday,  # Only shows from yesterday or earlier
            'fields.audioFile[exists]': 'false',  # Without audio file
            'fields.mixcloudLink[exists]': 'true'  # With mixcloudLink
        })
        logger.info(f"✓ Retrieved {len(entries)} shows matching criteria")

        # Debug: Log the first entry's fields to see what's available
        if entries and len(entries) > 0:
            first_entry = entries[0]
            logger.info(f"DEBUG: First entry fields: {list(first_entry.fields('en-US').keys())}")

        return entries

    except Exception as e:
        error_message = f"Error fetching shows from Contentful: {str(e)}"
        logger.error(error_message)
        return []


def sanitize_filename(filename):
    """
    Sanitize filename by removing/replacing invalid characters.

    Args:
        filename: The filename to sanitize

    Returns:
        str: Sanitized filename
    """
    # Remove invalid characters
    filename = re.sub(r'[<>:"/\\|?*]', '', filename)
    # Replace spaces with underscores
    filename = filename.replace(' ', '_')
    return filename


def upload_audio_to_contentful(entry_id, title, audio_file):
    """
    Upload audio file to Contentful as an asset and link it to a show entry.

    Args:
        entry_id: The Contentful entry ID of the show
        title: The title of the show (used as asset name)
        audio_file: The audio file object (opened in 'rb' mode)
    """
    audio_file.seek(0)

    client = contentful_management.Client(CONTENTFUL_MANAGEMENT_API_TOKEN)
    space = client.spaces().find(CONTENTFUL_SPACE_ID)
    environment = space.environments().find(CONTENTFUL_ENV_ID)

    # Step 1: Upload the file
    upload = space.uploads().create(audio_file)
    logger.info(f"File uploaded with ID: {upload.sys['id']}")

    # Step 2: Create an asset and link the uploaded file
    asset = environment.assets().create(
        None,
        {
            "fields": {
                "title": {
                    "en-US": title
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
                        "fileName": f"{title}.mp3",
                        "contentType": "audio/mpeg"
                    }
                }
            }
        }
    )
    logger.info(f"Asset created with ID: {asset.sys['id']}")

    asset.process()
    logger.info(f"Audio file processing initiated for asset: {asset.sys['id']}")

    # Step 3: Update the entry with the audio asset
    entry = environment.entries().find(entry_id)
    entry.fields('en-US')['audioFile'] = {
        "sys": {
            "type": "Link",
            "linkType": "Asset",
            "id": asset.sys['id']
        }
    }
    entry.save()

    # Step 4: Wait for asset to finish processing (it will have a URL when ready)
    # Will timeout after 600 seconds (10 minutes) to handle large files
    start_time = time.time()
    while True:
        newAsset = environment.assets().find(asset.sys['id'])
        if 'file' in newAsset.fields() and 'url' in newAsset.fields()['file']:
            logger.info(f"Asset processed successfully")
            # Publish the asset
            newAsset.publish()
            break
        elapsed_time = time.time() - start_time
        if elapsed_time > 600:
            raise TimeoutError("Asset processing timed out after 600 seconds")
        logger.info("Waiting for asset to be processed...")
        time.sleep(5)

    # Step 5: Publish the show entry
    entry.publish()
    logger.info(f"Show entry {entry_id} published with audio file")


def process_shows():
    """
    Main function to process shows and download missing audio.
    """
    logger.info("=" * 80)
    logger.info("Starting download process for shows missing audio files...")
    logger.info("=" * 80)
    logger.info(f"Log file: {log_filename}")
    logger.info(f"Download directory: {DOWNLOAD_DIR.absolute()}")

    shows = get_shows_without_audio()

    if not shows:
        logger.info("No shows found without audio files.")
        return

    processed_count = 0
    skipped_repeats = 0
    skipped_wrong_platform = 0
    downloaded_count = 0
    failed_count = 0
    uploaded_count = 0
    upload_failed_count = 0

    for idx, entry in enumerate(shows, 1):
        fields = entry.fields('en-US')
        entry_id = entry.sys['id']
        title = fields.get('title', 'Untitled')

        # Debug: Log all field keys for the first few entries
        if idx <= 3:
            logger.info(f"DEBUG: Entry {idx} has fields: {list(fields.keys())}")

        mixcloud_link = fields.get('mixcloud_link', '')

        logger.info("\n" + "-" * 80)
        logger.info(f"[{idx}/{len(shows)}] Processing: {title}")
        logger.info(f"Entry ID: {entry_id}")

        # Skip if title contains (r) - repeat marker
        if has_repeat_marker(title):
            logger.info(f"⊘ Skipping - Repeat show marked with (r)")
            skipped_repeats += 1
            continue

        # Check if it's a Soundcloud or Mixcloud link
        if not (is_soundcloud_link(mixcloud_link) or is_mixcloud_link(mixcloud_link)):
            logger.warning(f"⊘ Skipping - Link is not from Soundcloud or Mixcloud: {mixcloud_link}")
            skipped_wrong_platform += 1
            continue

        # Determine platform
        platform = "soundcloud" if is_soundcloud_link(mixcloud_link) else "mixcloud"
        logger.info(f"Platform: {platform.upper()}")
        logger.info(f"Link: {mixcloud_link}")

        # Create sanitized filename
        safe_filename = sanitize_filename(title)
        output_file = DOWNLOAD_DIR / f"{safe_filename}.mp3"

        # Check if file already exists
        if output_file.exists():
            logger.info(f"⊘ File already exists locally, skipping download: {output_file}")
            downloaded_count += 1  # Count as downloaded since we have it
            file_already_existed = True
        else:
            logger.info(f"Output file: {output_file}")
            # Download the audio
            success = download_audio_with_ytdlp(mixcloud_link, output_file)
            file_already_existed = False

            if success:
                downloaded_count += 1
                logger.info(f"✓ [{idx}/{len(shows)}] Download completed successfully")
            else:
                failed_count += 1
                logger.error(f"✗ [{idx}/{len(shows)}] Download failed")
                processed_count += 1
                continue

        # Upload the file to Contentful (whether it was just downloaded or already existed)
        try:
            logger.info(f"Uploading audio file to Contentful for entry {entry_id}...")
            with open(output_file, 'rb') as audio_file:
                upload_audio_to_contentful(entry_id, title, audio_file)
            uploaded_count += 1
            logger.info(f"✓ [{idx}/{len(shows)}] Successfully uploaded to Contentful")

            # Clean up: delete the local file after successful upload
            try:
                output_file.unlink()
                logger.info(f"✓ Cleaned up local file: {output_file}")
            except Exception as cleanup_error:
                logger.warning(f"⚠ Could not delete local file {output_file}: {cleanup_error}")
        except Exception as e:
            upload_failed_count += 1
            logger.error(f"✗ [{idx}/{len(shows)}] Upload to Contentful failed: {str(e)}")

        processed_count += 1

    # Print summary
    logger.info("\n" + "=" * 80)
    logger.info("SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Total shows matching criteria: {len(shows)}")
    logger.info(f"Processed: {processed_count}")
    logger.info(f"Successfully downloaded: {downloaded_count}")
    logger.info(f"Failed downloads: {failed_count}")
    logger.info(f"Successfully uploaded to Contentful: {uploaded_count}")
    logger.info(f"Failed uploads to Contentful: {upload_failed_count}")
    logger.info(f"Skipped (repeats): {skipped_repeats}")
    logger.info(f"Skipped (wrong platform): {skipped_wrong_platform}")
    logger.info("=" * 80)

    if downloaded_count > 0:
        logger.info(f"\nDownloaded files saved to: {DOWNLOAD_DIR.absolute()}")

    logger.info(f"\nFull log saved to: {log_filename}")


if __name__ == "__main__":
    try:
        logger.info(f"Script started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        process_shows()
        logger.info(f"Script completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    except KeyboardInterrupt:
        logger.warning("\n\nProcess interrupted by user.")
        sys.exit(0)
    except Exception as e:
        error_message = f"Unexpected error in main process: {str(e)}"
        logger.exception(error_message)
        sys.exit(1)
