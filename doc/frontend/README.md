# Frontend Architecture

This directory contains the separated frontend files for the Stock Trading Messages Dashboard.

## Structure

```
static/
├── index.html          # Main HTML structure
├── css/
│   └── styles.css      # All CSS styles
├── js/
│   └── dashboard.js    # All JavaScript functionality
└── README.md          # This file
```

## Features

- **Real-time Updates**: WebSocket connection for instant message display
- **Interactive Filtering**: Filter by symbol, option type, and message count
- **Responsive Design**: Modern UI with animations and hover effects
- **Message Management**: Clear all messages, refresh data
- **Statistics Dashboard**: Live counts and metrics

## Development

To modify the frontend:

1. **HTML Structure**: Edit `index.html`
2. **Styling**: Edit `css/styles.css`
3. **Functionality**: Edit `js/dashboard.js`

## API Integration

The frontend communicates with the FastAPI backend via:

- **WebSocket**: `/ws` - Real-time message updates
- **REST API**: `/api/messages` - Fetch/clear messages
- **Message Endpoint**: `/api/trigger_message` - Receive new messages

## Future Enhancements

This separated architecture allows for:

- Modern build tools (webpack, vite)
- Frontend frameworks (React, Vue, Angular)
- Component-based development
- Hot reload during development
- CSS preprocessors (SASS, LESS)
- TypeScript support
