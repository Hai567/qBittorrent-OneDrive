# qBittorrent to OneDrive Uploader

A Python-based automation tool that monitors your qBittorrent downloads and automatically uploads completed downloads to OneDrive using rclone.

## Features

-   **Automated Uploads**: Automatically detects completed qBittorrent downloads and uploads them to OneDrive
-   **Category Support**: Maintains your qBittorrent category structure on OneDrive
-   **Resilient Operation**: Includes retry logic, fault tolerance, and detailed logging
-   **Failed Upload Management**: Tracks failed uploads for later retry
-   **Configurable Settings**: Easily customize behavior via a simple configuration file

## Requirements

-   Python 3.7+
-   qBittorrent with Web UI enabled
-   rclone installed and configured with OneDrive

## Installation

1. Ensure you have Python 3.7 or higher installed
2. Clone or download this repository
3. Install the required Python packages:

```
pip install -r requirements.txt
```

4. Make sure rclone is installed and configured with OneDrive
5. Ensure qBittorrent Web UI is enabled and accessible

### Setting Up qBittorrent Web UI

1. Open qBittorrent and go to Tools > Options
2. Navigate to Web UI
3. Check "Enable Web UI"
4. Set your username and password
5. Note the port number (default is 8080)

### Setting Up rclone

1. Download and install rclone from [rclone.org](https://rclone.org/downloads/)
2. Configure OneDrive access by running:

```
rclone config
```

3. Follow the prompts to create a new remote named "onedrive" (or another name of your choice)
4. Verify your configuration by running:

```
rclone listremotes
```

Your OneDrive remote should be listed (e.g., `onedrive:`)

## Configuration

The script uses a JSON configuration file. You can create a default configuration by running:

```
python a.py --setup
```

This will create a `config.json` file that you can edit with your settings:

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
    "check_interval": 300,
    "use_categories": true,
    "max_upload_failures": 3,
    "continue_on_errors": false
}
```

### Configuration Options

| Option                 | Description                                                  |
| ---------------------- | ------------------------------------------------------------ |
| `qbittorrent.host`     | Hostname or IP address of the qBittorrent Web UI             |
| `qbittorrent.port`     | Port of the qBittorrent Web UI                               |
| `qbittorrent.username` | Username for qBittorrent Web UI                              |
| `qbittorrent.password` | Password for qBittorrent Web UI                              |
| `rclone.remote_name`   | Name of your rclone remote for OneDrive                      |
| `rclone.remote_path`   | Path within your OneDrive where files should be uploaded     |
| `check_interval`       | How often to check for completed torrents (in seconds)       |
| `use_categories`       | If true, maintain qBittorrent category structure on OneDrive |
| `max_upload_failures`  | Maximum number of retry attempts for failed uploads          |
| `continue_on_errors`   | Continue running even if initial connection checks fail      |

## Usage

To start the uploader service:

```
python a.py
```

### Command-Line Options

| Option                                            | Description                                        |
| ------------------------------------------------- | -------------------------------------------------- |
| `--setup`                                         | Create default configuration file and exit         |
| `--config PATH`                                   | Specify a custom configuration file path           |
| `--validate`                                      | Validate configuration without running the service |
| `--log-level {DEBUG,INFO,WARNING,ERROR,CRITICAL}` | Set logging verbosity                              |

Examples:

```
python a.py --log-level DEBUG
python a.py --config my_custom_config.json
python a.py --validate
```

## How It Works

1. The script connects to qBittorrent's Web API and queries for completed downloads
2. For each completed download that hasn't been processed yet:
    - The script determines the local file path
    - Uses rclone to upload the content to OneDrive
    - Tracks successful uploads to avoid duplicate processing
3. If an upload fails, it's tracked for later retry
4. The script repeats this process at the configured interval

## Logs

The script logs its activity to both the console and a log file named `qbit_rclone.log`. You can adjust the logging level with the `--log-level` command-line option.

## Running as a Service

### Windows

To run as a Windows service, you can use NSSM (Non-Sucking Service Manager):

1. Download NSSM from [nssm.cc](https://nssm.cc/download)
2. Install the service by opening a command prompt as administrator and running:

```
nssm install "qBittorrent to OneDrive Uploader" "C:\path\to\python.exe" "C:\path\to\a.py"
```

3. Set the working directory to the script's directory:

```
nssm set "qBittorrent to OneDrive Uploader" AppDirectory "C:\path\to\script\directory"
```

### Linux

To run as a Linux systemd service:

1. Create a service file:

```
sudo nano /etc/systemd/system/qbit-onedrive.service
```

2. Add the following content (adjusting paths as needed):

```
[Unit]
Description=qBittorrent to OneDrive Uploader
After=network.target

[Service]
User=your_username
WorkingDirectory=/path/to/script/directory
ExecStart=/usr/bin/python3 /path/to/script/directory/a.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

3. Enable and start the service:

```
sudo systemctl daemon-reload
sudo systemctl enable qbit-onedrive
sudo systemctl start qbit-onedrive
```

## Troubleshooting

-   **Can't connect to qBittorrent**: Verify Web UI is enabled and credentials are correct
-   **rclone not found**: Make sure rclone is installed and in your PATH
-   **Upload failures**: Check that rclone is properly configured with OneDrive
-   **Permission errors**: Ensure the script has access to both download locations and the config files

## License

This project is released under the MIT License.

## Acknowledgements

-   [qBittorrent](https://www.qbittorrent.org/)
-   [rclone](https://rclone.org/)
-   [Python Requests Library](https://requests.readthedocs.io/)
