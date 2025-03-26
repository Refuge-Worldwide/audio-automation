# Use an official lightweight Python image
FROM python:3.11-slim

# Set the working directory
WORKDIR /app

# Copy the Python script and requirements
COPY requirements.txt ./
COPY scripts/ ./scripts/

# Install ffmpeg
RUN apt-get -y update
RUN apt-get -y upgrade
RUN apt-get install -y ffmpeg

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Default command does nothing, script runs via Coolify cron job
CMD ["sleep", "infinity"]