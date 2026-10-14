# Etech-AI Analytics Chatbot UI

A modern, production-ready React + TypeScript UI for the LangGraph-based analytics chatbot.

## Features

- ✅ **Real-time WebSocket streaming** - Character-by-character streaming with immediate rendering
- ✅ **Thinking panel** - Shows AI reasoning steps and tool execution in real-time
- ✅ **Rich data display** - SQL results, visualizations (Plotly.js), document retrieval
- ✅ **Conversation management** - Multi-turn conversations with history
- ✅ **Responsive design** - Works on desktop, tablet, and mobile
- ✅ **Type-safe** - Full TypeScript coverage for all WebSocket events
- ✅ **Modern UI** - Built with Tailwind CSS and Framer Motion animations

## Tech Stack

- **React 18** - UI framework
- **TypeScript** - Type safety
- **Vite** - Build tool and dev server
- **Tailwind CSS** - Styling
- **Zustand** - State management
- **Framer Motion** - Animations
- **Plotly.js** - Data visualizations
- **React Markdown** - Markdown rendering

## Project Structure

```
webapp-react/
├── src/
│   ├── components/           # React components
│   │   ├── ChatInput.tsx    # Message input area
│   │   ├── ChatMessage.tsx  # Message bubbles
│   │   ├── RetrievalCard.tsx    # Document retrieval display
│   │   ├── Sidebar.tsx      # Conversation history sidebar
│   │   ├── SQLResultCard.tsx    # SQL results table
│   │   ├── ThinkingPanel.tsx    # Right-side thinking panel
│   │   ├── ToolCard.tsx     # Individual tool execution card
│   │   ├── VisualizationCard.tsx # Plotly chart renderer
│   │   └── WelcomeScreen.tsx    # Initial landing screen
│   │
│   ├── services/            # Services
│   │   └── websocket.ts     # WebSocket client
│   │
│   ├── store/               # State management
│   │   └── chatStore.ts     # Zustand store
│   │
│   ├── types/               # TypeScript types
│   │   └── websocket.types.ts   # All WebSocket event types
│   │
│   ├── App.tsx              # Main app component
│   ├── main.tsx             # Entry point
│   └── index.css            # Global styles
│
├── index.html               # HTML template
├── package.json             # Dependencies
├── tsconfig.json            # TypeScript config
├── vite.config.ts           # Vite config
└── tailwind.config.js       # Tailwind config
```

## Getting Started

### 1. Install Dependencies

```bash
cd webapp-react
npm install
```

### 2. Development Mode

```bash
npm run dev
```

This starts the Vite dev server on `http://localhost:3000` with hot module replacement.

### 3. Build for Production

```bash
npm run build
```

This creates optimized production files in `../webapp-build/`.

### 4. Preview Production Build

```bash
npm run preview
```

## WebSocket Events

The UI handles all backend WebSocket events:

| Event Type | Content Type | Description |
|------------|--------------|-------------|
| `start` | `answer`, `optimised_question` | Begin new content block |
| `stream` | `null` | Stream answer text |
| `stream` | `tools` | Tool execution started |
| `stream` | `tool_consolidation` | Tool processing status |
| `stream` | `tool_result` | Tool execution completed |
| `stream` | `visualization` | Plotly.js chart data |
| `stream` | `sql` | SQL query results |
| `stream` | `retrieval` | RAG document retrieval |
| `end` | `answer` | Content block complete |
| `error` | `null` | Error occurred |
| `ping` | `null` | Connection keep-alive |

## State Management

Uses Zustand with localStorage persistence:

- **Conversations** - Full conversation history
- **Messages** - User and assistant messages
- **Thinking Steps** - Real-time tool execution tracking
- **Rich Content** - Visualizations, SQL results, retrieved documents
- **UI State** - Sidebar, thinking panel visibility

## Components

### ThinkingPanel
Shows AI reasoning in real-time on the right side:
- Tool execution steps
- Status indicators (running, completed, failed)
- Expandable cards with details
- SQL queries and error messages

### ChatMessage
Displays user and assistant messages:
- Markdown rendering for rich text
- Inline visualizations
- SQL result tables
- Retrieved document cards
- Streaming indicator

### VisualizationCard
Renders Plotly.js charts:
- Interactive charts (zoom, pan, hover)
- Expand to fullscreen
- Download as PNG
- Supports all Plotly chart types

### SQLResultCard
Displays SQL query results:
- Sortable table
- Show/hide SQL query
- Copy query to clipboard
- Pagination for large results

### RetrievalCard
Shows RAG document retrieval:
- Expandable documents
- Relevance scores
- Source metadata
- Date filtering indicator

## Integration with Backend

### FastAPI Static File Serving

Update `run.py` to serve the built React app:

```python
from fastapi.staticfiles import StaticFiles
from pathlib import Path

webapp_build_dir = Path(__file__).parent / "webapp-build"

# Serve React app
app.mount("/ui", StaticFiles(directory=str(webapp_build_dir), html=True), name="ui")

# Serve root as well
@app.get("/")
async def root():
    return RedirectResponse(url="/ui")
```

### WebSocket Endpoint

The UI connects to: `ws://localhost:8000/workflows/stream`

Ensure your FastAPI app has this endpoint available.

## Environment Variables

No environment variables needed for the frontend. All configuration is handled via:

1. **WebSocket URL**: Auto-detected based on `window.location.host`
2. **Protocol**: Auto-switches between `ws://` and `wss://` based on HTTP/HTTPS

## Customization

### Branding

Update branding in:
- `src/components/Sidebar.tsx` - Logo and brand name
- `index.html` - Page title
- `tailwind.config.js` - Primary colors

### Example Prompts

Edit example prompts in:
- `src/components/WelcomeScreen.tsx` - `examplePrompts` array

### Styling

All styling uses Tailwind CSS. Customize in:
- `tailwind.config.js` - Theme colors, animations
- `src/index.css` - Global styles and custom CSS

## Performance

- **Code Splitting**: Automatic with Vite
- **Tree Shaking**: Removes unused code
- **Lazy Loading**: Components load on demand
- **Optimized Bundle**: ~200KB gzipped (production)

## Browser Support

- Chrome/Edge (latest)
- Firefox (latest)
- Safari (latest)
- Mobile browsers (iOS Safari, Chrome Mobile)

## Troubleshooting

### WebSocket Connection Issues

1. Check backend is running: `http://localhost:8000`
2. Verify WebSocket endpoint: `/workflows/stream`
3. Check browser console for errors

### Build Issues

1. Clear node_modules: `rm -rf node_modules && npm install`
2. Clear cache: `rm -rf dist && npm run build`

### Styling Issues

1. Rebuild Tailwind: `npx tailwindcss -i ./src/index.css -o ./dist/output.css`
2. Check PostCSS config: `postcss.config.js`

## License

MIT
