# syntax=docker/dockerfile:1.6
FROM python:3-slim AS runtime

ARG DENO_VERSION=v2.5.6

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y \
        ca-certificates \
        curl \
        ffmpeg \
        unzip \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL "https://github.com/denoland/deno/releases/download/${DENO_VERSION}/deno-x86_64-unknown-linux-gnu.zip" -o /tmp/deno.zip \
    && unzip /tmp/deno.zip -d /usr/local/bin \
    && rm /tmp/deno.zip \
    && chmod +x /usr/local/bin/deno

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV BOT_DENO_PATH=/usr/local/bin/deno \
    BOT_OUTPUT_FOLDER=/data/downloads \
    BOT_COOKIES_FILE=/data/cookies.txt

VOLUME ["/data"]

ENTRYPOINT ["python", "main.py"]
