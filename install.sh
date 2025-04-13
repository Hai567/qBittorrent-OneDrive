# Install qbittorrent + python3
# Python
sudo apt update && sudo apt upgrade
sudo add-apt-repository ppa:deadsnakes/ppa -y
sudo apt update
sudo apt install python3.10
# Qbittorrent
sudo apt install dirmngr ca-certificates software-properties-common apt-transport-https
sudo add-apt-repository ppa:qbittorrent-team/qbittorrent-stable -y
sudo apt update
sudo apt install qbittorrent