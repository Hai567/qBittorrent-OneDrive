# Install qbittorrent + python3
# Python
sudo apt update && sudo apt upgrade
sudo add-apt-repository ppa:deadsnakes/ppa -y
sudo apt update
yes | sudo apt install python3.10
# Qbittorrent
yes | sudo apt install dirmngr ca-certificates software-properties-common apt-transport-https
sudo add-apt-repository ppa:qbittorrent-team/qbittorrent-stable -y
sudo apt update
yes | sudo apt install qbittorrent
# Rclone
sudo -v ; curl https://rclone.org/install.sh | sudo bash
# Ngrok tunnel
curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc \
  | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null \
  && echo "deb https://ngrok-agent.s3.amazonaws.com buster main" \
  | sudo tee /etc/apt/sources.list.d/ngrok.list \
  && sudo apt update \
  && sudo apt install ngrok
  
echo "Please enter your ngrok authtoken:"
read ngrok_token
ngrok config add-authtoken "$ngrok_token"