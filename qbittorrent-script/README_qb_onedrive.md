# qBittorrent to OneDrive Uploader

This Python script automatically uploads completed torrents from qBittorrent to OneDrive using rclone, verifies the upload was successful, and then cleans up by removing the torrent from qBittorrent and deleting the files from disk.

## Features

-   Automatically uploads completed torrents to OneDrive using rclone
-   Verifies the upload was successful before cleanup
-   Deletes the torrent from qBittorrent after successful upload
-   Removes the downloaded files from disk to free up space
-   Preserves category structure (if used in qBittorrent)
-   Configurable via JSON file

## Requirements

-   Python 3.7 or higher
-   `requests` library
-   qBittorrent with Web UI enabled
-   rclone installed and configured with OneDrive remote

## Installation

1. Clone or download this repository
2. Install the required dependencies:

```bash
pip install requests
```

3. Ensure rclone is installed and configured:

    - Download from [rclone.org](https://rclone.org/downloads/)
    - Set up OneDrive remote by running: `rclone config`
    - Follow the prompts to create a remote named "onedrive" (or change name in config)
    - Verify configuration with: `rclone listremotes`

4. Ensure qBittorrent Web UI is enabled:

    - Open qBittorrent and go to Tools > Options > Web UI
    - Check "Web UI" and set a username and password
    - Note the port (default is 8080)

5. Edit the `config.json` file to match your setup:

```json
{
    "qbittorrent": {
        "host": "localhost",
        "port": 8080,
        "username": "admin",
        "password": "adminadmin"
    },
    "rclone": {
        "remote_name": "onedrive",
        "remote_path": "Torrents"
    },
    "auto_delete": {
        "delete_from_client": true,
        "delete_content": true
    }
}
```

## Setting up in qBittorrent

Configure qBittorrent to run this script when a torrent completes downloading:

1. Open qBittorrent
2. Go to Tools > Options > Downloads
3. Scroll down to "Run external program on torrent completion"
4. Enter the following command:

```
python /path/to/qbittorrent_upload_to_onedrive.py "%I" "%N" "%L"
```

Replace `/path/to/` with the actual path to where you saved the script.

qBittorrent will pass these parameters to the script:

-   `%I`: The torrent hash
-   `%N`: The torrent name
-   `%L`: The category/label (optional)

## How It Works

1. When a torrent completes in qBittorrent, it runs the script with the torrent hash, name, and optional category
2. The script:
    - Connects to qBittorrent's Web API to get more information about the torrent
    - Locates the downloaded content on disk
    - Uses rclone to upload the content to OneDrive
    - Verifies that the upload was successful
    - Removes the torrent from qBittorrent (but not its files, as we handle that separately)
    - Deletes the content files from disk

## Manual Usage

You can also run the script manually for a specific torrent:

```bash
python qbittorrent_upload_to_onedrive.py "TORRENT_HASH" "TORRENT_NAME" "CATEGORY"
```

-   `TORRENT_HASH`: The hash of the torrent to process
-   `TORRENT_NAME`: The name of the torrent
-   `CATEGORY`: (Optional) The category/label of the torrent

## Troubleshooting

Check the log file `qbittorrent_onedrive_upload.log` for detailed information about any errors.

Common issues:

1. **Unable to connect to qBittorrent**

    - Make sure the Web UI is enabled
    - Check that the host, port, username, and password in config.json are correct

2. **rclone not found**

    - Make sure rclone is installed and in your PATH
    - You can specify the full path to rclone in the code if needed

3. **OneDrive remote not configured**

    - Run `rclone config` to set up the OneDrive remote
    - Make sure the remote name in config.json matches what you configured

4. **Permission errors**
    - Make sure the script has permissions to access the download location
    - Check that it has permissions to delete files if auto-delete is enabled

## License

This script is provided under the MIT License. Feel free to modify and distribute as needed.
