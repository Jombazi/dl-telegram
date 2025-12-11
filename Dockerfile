FROM python:3.12-slim

# Install ffmpeg for video conversion
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot source
COPY . .

# Environment defaults (can still override via .env / env vars)
ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py"]
