# YT-DLP Telegram Bot

A Telegram bot that allows you to download videos from YouTube, Twitter, Reddit, and many other platforms using [yt-dlp](https://github.com/yt-dlp/yt-dlp).

## Features
- Download videos from supported platforms by simply sending a link.
- Upload downloaded files to Nextcloud (optional).
- Supports custom configurations via environment variables.

## Usage
1. Start the bot on Telegram.
2. Send a video URL directly to the bot.
3. Optionally, use `/download <url>` in group chats.

**Note:** The Telegram API limits files sent by bots to 50 MB. For larger files, consider enabling Nextcloud integration.

## Self-Hosting

### Prerequisites
- Docker and Docker Compose installed.
- A Telegram bot token. [Create one here](https://core.telegram.org/bots#botfather).

### Steps
1. Clone the repository:
   ```bash
   git clone https://github.com/EdisonJwa/yt-dlp-telegram.git
   cd yt-dlp-telegram
   ```

2. Create a `.env` file with the required environment variables. Refer to `example.config.py` for all available options.

3. Start the bot using Docker Compose:
   ```bash
   docker-compose up -d
   ```

4. The bot is now running and ready to use.

### Environment Variables
| Variable                  | Description                                      | Default Value       |
|---------------------------|--------------------------------------------------|---------------------|
| `BOT_TOKEN`               | Telegram bot token                               | **Required**        |
| `BOT_OUTPUT_FOLDER`       | Folder for downloaded files                      | `downloads`         |
| `BOT_COOKIES_FILE`        | Path to cookies file                             | `cookies.txt`       |
| `BOT_NEXTCLOUD_BASE_URL`  | Nextcloud base URL                               |                     |
| `BOT_NEXTCLOUD_USERNAME`  | Nextcloud username                               |                     |
| `BOT_NEXTCLOUD_PASSWORD`  | Nextcloud password                               |                     |

For a full list of variables, see `config_defaults.py`.

## Contributing
Contributions are welcome! Feel free to open issues or submit pull requests.

## License
This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
