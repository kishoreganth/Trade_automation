# 🚀 Stock Trading Messages Dashboard

A real-time web dashboard to monitor and display corporate announcement messages from your stock trading automation system.

## ✨ Features

- **📊 Real-time Message Display**: Messages appear instantly via WebSocket
- **📋 Interactive Table**: Filter by symbol, sort by time, limit results
- **📈 Live Statistics**: Total messages, today's count, unique symbols
- **🔗 Direct File Access**: Click to view PDF attachments
- **💫 Modern UI**: Beautiful, responsive design with animations
- **🔄 Auto-reconnect**: WebSocket automatically reconnects if disconnected
- **💾 Persistent Storage**: All messages stored in SQLite database

## 🚀 Quick Start

### 1. Start the Dashboard
```bash
python start_dashboard.py
```
This will:
- Start the API server on `http://localhost:8000`
- Automatically open your browser to the dashboard
- Begin monitoring for messages

### 2. Test with Sample Data
```bash
python test_dashboard.py
```
Choose option 1 to send sample messages or option 2 for continuous testing.

### 3. Run Your Main Application
Your existing `nse_url_test.py` script will now automatically send messages to both:
- Telegram (as before)
- Local dashboard (new!)

## 🎯 How It Works

### Message Flow
```
Corporate Announcement → trigger_test_message() → Telegram + Local API → WebSocket → Dashboard
```

### Dashboard Components
1. **FastAPI Backend** (`api_server.py`)
   - Receives messages from `trigger_test_message()`
   - Stores in SQLite database
   - Broadcasts via WebSocket to frontend

2. **Enhanced Trigger Function** (`nse_url_test.py`)
   - Sends to Telegram (unchanged)
   - Also sends to local API (new)
   - Non-blocking, error-resilient

3. **Real-time Frontend** (embedded in `api_server.py`)
   - Live message table
   - Statistics dashboard
   - Connection status
   - Filtering and controls

## 📊 Dashboard Features

### Statistics Panel
- **Total Messages**: All messages received
- **Today's Messages**: Messages from today
- **Unique Symbols**: Number of different stock symbols
- **Last Message Time**: When the most recent message arrived

### Message Table
- **Time**: When the message was received
- **Symbol**: Stock symbol (e.g., RELIANCE, TCS)
- **Company**: Full company name
- **Description**: Corporate announcement details
- **File**: Direct link to PDF attachment
- **Chat ID**: Telegram chat where it was sent

### Controls
- **Symbol Filter**: Show only messages for specific symbols
- **Message Limit**: Display last 50/100/200 or all messages
- **Refresh**: Manually refresh the data
- **Clear All**: Remove all stored messages

## 🔧 Technical Details

### Dependencies Added
```
aiosqlite==0.19.0    # SQLite async support
websockets==12.0     # WebSocket communication
```

### Database Schema
```sql
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    message TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    symbol TEXT,
    company_name TEXT,
    description TEXT,
    file_url TEXT,
    raw_message TEXT
);
```

### API Endpoints
- `GET /`: Dashboard homepage
- `GET /api/messages`: Retrieve stored messages
- `POST /api/trigger_message`: Receive new messages
- `DELETE /api/messages`: Clear all messages
- `WebSocket /ws`: Real-time updates

## 🛠️ Troubleshooting

### Dashboard Not Loading?
1. Check if API server is running: `http://localhost:8000`
2. Look for error messages in terminal
3. Ensure port 8000 is not being used by another application

### Messages Not Appearing?
1. Verify your main script (`nse_url_test.py`) is running
2. Check terminal for "✅ Message sent to UI dashboard" confirmations
3. Look for any API connection errors in the logs

### WebSocket Connection Issues?
1. The dashboard automatically reconnects every 3 seconds
2. Check browser console for WebSocket errors
3. Firewall might be blocking WebSocket connections

## 📁 Files Overview

| File | Purpose |
|------|---------|
| `api_server.py` | FastAPI backend + embedded frontend |
| `start_dashboard.py` | Easy startup script |
| `test_dashboard.py` | Testing utility |
| `nse_url_test.py` | Modified to send to dashboard |
| `messages.db` | SQLite database (auto-created) |

## 🎉 Success!

Once everything is running, you'll see:
- 🌐 Dashboard at `http://localhost:8000`
- 📱 Messages still going to Telegram
- 📊 Real-time updates in the web interface
- 💾 All messages stored for historical analysis

The dashboard runs alongside your existing system without affecting Telegram functionality. If the dashboard goes down, your Telegram messages continue working normally!
