# qBittorrent to OneDrive Uploader

A Python script that automatically uploads completed torrents from qBittorrent to OneDrive using rclone, then cleans up the local files.

## Requirements

-   Python 3.6 or higher
-   qBittorrent with WebUI enabled
-   rclone properly configured with OneDrive remote named "onedrive"
-   Requests library (`pip install requests`)

## Setup

1. Install the required Python package:

    ```
    pip install requests
    ```

2. Configure rclone with your OneDrive account if you haven't already:

    ```
    rclone config
    ```

    Follow the prompts to set up a remote named "onedrive".

3. Create a `config.json` file (or copy the example):

    ```json
    {
        "qbittorrent": {
            "host": "http://localhost:8080",
            "username": "admin",
            "password": "adminadmin"
        },
        "onedrive": {
            "remote_name": "onedrive",
            "target_path": "Torrents"
        },
        "logging": {
            "log_file": "qbit-rclone.log",
            "log_level": "INFO"
        },
        "rclone": {
            "options": ["--progress"]
        }
    }
    ```

4. Edit the configuration to match your settings:

    - Update qBittorrent WebUI details (host, username, password)
    - Change the OneDrive remote name and target path if needed
    - Adjust logging settings and rclone options as desired

5. Make the script executable:
    ```
    chmod +x qbit-script.py
    ```

## Configure qBittorrent

1. Open qBittorrent
2. Go to Tools > Options > Downloads
3. Scroll down to "Run external program on torrent completion"
4. Enter the following command:

    ```
    python /path/to/qbit-script.py -name "%N" -hash "%I" -lcp "%F"
    ```

    Replace `/path/to/` with the actual path to the script.

5. (Optional) If you want to use a different config file location:
    ```
    python /path/to/qbit-script.py -name "%N" -hash "%I" -lcp "%F" -config "/path/to/custom-config.json"
    ```

## Configuration Options

The `config.json` file contains the following sections:

### qBittorrent

-   `host`: The URL of your qBittorrent WebUI
-   `username`: Your qBittorrent WebUI username
-   `password`: Your qBittorrent WebUI password

### OneDrive

-   `remote_name`: The name of your rclone remote for OneDrive
-   `target_path`: The folder path within OneDrive to store torrents

### Logging

-   `log_file`: Path to the log file
-   `log_level`: Logging level (INFO, DEBUG, WARNING, ERROR)

### Rclone

-   `options`: Array of additional options to pass to rclone

## How It Works

When a torrent completes:

1. qBittorrent calls the script with the torrent's name, hash, and local path
2. The script uploads the content to OneDrive in the configured folder
3. It verifies the upload was successful
4. It deletes the local content
5. It removes the torrent from qBittorrent

## Logging

The script creates a log file (by default `qbit-rclone.log`) in the same directory as the script, which tracks all operations and errors.

## Troubleshooting

-   If uploads fail, check your rclone configuration
-   Ensure qBittorrent WebUI is enabled and accessible
-   Verify the credentials in your config.json are correct
-   Check the log file for detailed error messages
