#!/bin/bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored messages
print_message() {
    echo -e "${BLUE}>>> ${1}${NC}"
}

print_success() {
    echo -e "${GREEN}>>> ${1}${NC}"
}

print_error() {
    echo -e "${RED}>>> ${1}${NC}"
}

# Function to generate random string
generate_key() {
    python3 -c "import secrets; print(secrets.token_hex(16))"
}

# Create necessary directories
print_message "Creating directories..."
mkdir -p data config

# Generate API token and secret key if they don't exist
API_TOKEN=$(generate_key)
SECRET_KEY=$(generate_key)

# Create .env file
print_message "Setting up environment variables..."
cat > config/.env << EOL
# Whoop API Configuration
WHOOP_CLIENT_ID=
WHOOP_CLIENT_SECRET=
WHOOP_API_URL=
FLASK_SECRET_KEY=${SECRET_KEY}
API_TOKEN=${API_TOKEN}
EOL

# Set correct permissions
chmod 755 data config
chmod 644 config/.env

# Export current user's UID and GID for docker-compose
echo "UID=$(id -u)" > .env
echo "GID=$(id -g)" >> .env

# Ask for Home Assistant directory
print_message "Please enter the path to your Home Assistant config directory:"
read -p "Path (e.g., /home/user/homeassistant/config): " HA_PATH

# Validate Home Assistant directory
if [ ! -d "$HA_PATH" ]; then
    print_error "Directory does not exist: $HA_PATH"
    exit 1
fi

# Create custom_components directory if it doesn't exist
HA_CUSTOM_DIR="$HA_PATH/custom_components"
mkdir -p "$HA_CUSTOM_DIR"

# Copy custom component files
print_message "Installing Whoop custom component..."
WHOOP_COMPONENT_DIR="$HA_CUSTOM_DIR/whoop"
mkdir -p "$WHOOP_COMPONENT_DIR"

# Copy component files
cp -r custom_components/whoop/* "$WHOOP_COMPONENT_DIR/"

# Update sensor.py with API URL and token
print_message "Configuring component..."
sed -i "s|WHOOP_API_URL = None|WHOOP_API_URL = \"${WHOOP_API_URL}\"|" "$WHOOP_COMPONENT_DIR/sensor.py"
sed -i "s|API_TOKEN = None|API_TOKEN = \"${API_TOKEN}\"|" "$WHOOP_COMPONENT_DIR/sensor.py"

# Ask for Whoop API credentials
print_message "Please enter your Whoop API credentials:"
read -p "Client ID: " CLIENT_ID
read -p "Client Secret: " CLIENT_SECRET
read -p "API URL (e.g., https://your-domain.com): " API_URL

# Update .env file with provided credentials
sed -i "s|WHOOP_CLIENT_ID=|WHOOP_CLIENT_ID=${CLIENT_ID}|" config/.env
sed -i "s|WHOOP_CLIENT_SECRET=|WHOOP_CLIENT_SECRET=${CLIENT_SECRET}|" config/.env
sed -i "s|WHOOP_API_URL=|WHOOP_API_URL=${API_URL}|" config/.env

# Start Docker containers
print_message "Starting Docker containers..."
docker-compose down
docker-compose up -d

print_success "Setup completed successfully!"
echo
print_message "Next steps:"
echo "1. Restart Home Assistant"
echo "2. Go to Configuration -> Integrations"
echo "3. Click '+ ADD INTEGRATION'"
echo "4. Search for 'Whoop'"
echo "5. Enter your Whoop user ID"
echo
print_message "Your API Token (save this for reference):"
echo "$API_TOKEN"
echo
print_message "To authorize with Whoop, visit:"
echo "${API_URL}/auth"