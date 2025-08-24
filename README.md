## Features

- **Real-time Monitoring**: Utilizes Rich to display live status updates, including connection status, uptime, latency, and point tracking.
- **Automatic Reconnection**: Automatically attempts to reconnect if the connection to the Teneo websocket is lost.
- **Logging**: Comprehensive logging to track activity and errors.

## Installation

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/your-username/TeneoNode.git
   cd TeneoNode
   ```

2. **Install Requirements**:
   Ensure you have Python installed, then install the required packages:
   ```bash
   pip install -r requirements.txt
   ```

3. **Edit Configuration File**:
   Open the `config.json` file and replace the placeholder with your Teneo access token:
   ```json
   {
     "access_token": "your_access_token_here",
     "ws_url": "wss://secure.ws.teneo.pro/websocket",
     "version": "v0.2"
   }
   ```

## Usage

Run the TeneoNode application:

```bash
python run.py
```

## Support
IG: [instagram.com/xxiv.uname](https://instagram.com/xxiv.uname)
