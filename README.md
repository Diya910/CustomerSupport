# ShopAssist AI - Refund Processing Agent

**An AI-powered refund processing system** that evaluates customer refund requests against a dynamic policy retrieved from a vector knowledge base, enforces decisions consistently, and provides full audit trails with reasoning logs.

Built by **Diya**

---

## Screenshots

### Welcome Screen
The landing page shows quick-start examples and the conversation sidebar.

![Welcome Screen](screenshots/welcome-screen.png)

### Chat Interface
Real-time streaming chat with tool execution cards showing each workflow step (customer lookup, order lookup, policy search, refund history check, decision recording).

![Chat Interface](screenshots/chat-interface.png)

### Admin Dashboard
Full audit log with 37 decisions, LangSmith reasoning traces with cost/latency, and filter controls. Auto-refreshes every 10 seconds without flickering.

![Admin Dashboard](screenshots/admin-dashboard.png)

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture (HLD)](#architecture-hld)
3. [Detailed Design (LLD)](#detailed-design-lld)
4. [Tech Stack](#tech-stack)
5. [Prerequisites](#prerequisites)
6. [Environment Setup](#environment-setup)
7. [Installation](#installation)
8. [Running the Application](#running-the-application)
9. [Policy Ingestion](#policy-ingestion)
10. [Demo Credentials](#demo-credentials)
11. [Features](#features)
12. [Project Structure](#project-structure)
13. [API Endpoints](#api-endpoints)
14. [Policy Retrieval (RAG Pipeline)](#policy-retrieval-rag-pipeline)
15. [CRM Data Model](#crm-data-model)

---

## Overview

ShopAssist AI is a full-stack AI refund agent built with:
- A **LangGraph ReAct agent** that follows a strict mandatory workflow (identify customer, find order, check history, retrieve policy, evaluate, record decision, respond)
- **Retrieval-Augmented Generation (RAG)** — the refund policy lives in an OpenSearch Serverless vector index and is retrieved fresh every turn; there are no hardcoded policy rules in the system prompt
- **Real-time streaming** via WebSocket with tool execution visualization
- **Text-to-Speech** for voice responses (edge-tts with ordered sentence-level streaming)
- **Admin Dashboard** with full decision audit log and LangSmith reasoning traces
- **15 curated CRM profiles** with 16 orders covering all policy edge cases
- **Parallel tool execution** — independent actions fire simultaneously for faster responses

---

## Architecture (HLD)

```
                         +──────────────────────────────────+
                         |         React Frontend           |
                         |  (Chat + Admin Dashboard + TTS)  |
                         +──────────────┬───────────────────+
                                        | WebSocket / REST
                         +──────────────▼───────────────────+
                         |        FastAPI Backend           |
                         |  (main.py — port 8000)          |
                         +───┬──────────┬──────────┬───────+
                             |          |          |
              +--------------+   +------+------+   +-------------+
              |                  |             |                  |
    +---------▼--------+ +------▼------+ +----▼----+   +---------▼--------+
    | LangGraph Agent  | |  OpenSearch | | Postgres|   |   LangSmith      |
    | (ReAct Cycle)    | |  Serverless | |   DB    |   |  (Tracing)       |
    |                  | |  (Policy    | | (CRM +  |   +------------------+
    | Claude Sonnet 4  | |   Vector DB)| | Orders) |
    | via AWS Bedrock  | +-------------+ +---------+
    +------------------+
              |
    +---------▼---------+
    | Amazon Titan       |
    | Embed v2 (1024d)   |
    +--------------------+
              |
    +---------▼---------+
    | Cohere Rerank      |
    | v3.5 (Bedrock)     |
    +--------------------+
```

**Data Flow:**
1. User sends a refund request via WebSocket
2. FastAPI routes to the LangGraph agent
3. Agent executes the mandatory workflow (parallel where dependencies allow):
   - Identifies customer (PostgreSQL)
   - Looks up order (PostgreSQL)
   - Retrieves policy (OpenSearch hybrid search + Cohere reranking)
   - Checks refund history (PostgreSQL)
4. Agent evaluates eligibility against the retrieved policy (VERDICT: DENY/APPROVE/CONDITIONAL)
5. Records decision (approve/deny) with full reasoning to PostgreSQL
6. Streams response tokens back via WebSocket
7. Frontend renders chat + optional TTS audio
8. Admin dashboard polls decisions and LangSmith traces every 10 seconds

---

## Detailed Design (LLD)

### Agent Workflow (per refund request)

```
User Message
    │
    ▼
┌─────────────────────┐
│  Intent Classifier   │──── SOCIAL/CAPABILITY/OFF_TOPIC → respond directly
│  (in system prompt)  │──── ORDER_LOOKUP → check status only
│                      │──── ANALYTICS → text-to-SQL query
└────────┬────────────┘
         │ REFUND_REQUEST
         ▼
┌─────────────────────┐
│   ACKNOWLEDGE       │  "I'll look up your account and order..."
└────────┬────────────┘
         │
         ▼  (parallel when data is available)
┌─────────────────────────────────────────────────────┐
│  IDENTIFY CUSTOMER  │  FIND ORDER  │  LOAD POLICY   │
│   (PostgreSQL)      │  (PostgreSQL)│  (OpenSearch)   │
└────────┬────────────┴──────┬───────┴────────────────┘
         │                    │
         ▼                    ▼ (needs order_id from above)
┌─────────────────────┐
│  CHECK REFUND HISTORY│
│   (PostgreSQL)       │
└────────┬─────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│           EVALUATE ELIGIBILITY           │
│                                          │
│  Apply retrieved policy rules:           │
│  1. Automatic denials (flagged, digital, │
│     already returned, undelivered,       │
│     outside window)                      │
│  2. Automatic approvals (cancelled,      │
│     wrong item)                          │
│  3. Conditional (defective within window │
│     → troubleshoot first)               │
│                                          │
│  Output: VERDICT = DENY | APPROVE |      │
│          CONDITIONAL                     │
└────────┬────────────────────────────────┘
         │
         ├──── DENY → record denial → respond
         ├──── APPROVE → record approval → respond
         └──── CONDITIONAL → troubleshoot → wait for user
                              → then record → respond
```

### Vector Search Pipeline (Policy Retrieval)

```
Query: "return window standard tier refund"
    │
    ▼
┌──────────────────────┐
│  Amazon Titan Embed  │  → 1024-dim vector
│  v2                  │
└────────┬─────────────┘
         │
         ▼ (parallel)
┌────────────────┐  ┌────────────────┐
│  k-NN Vector   │  │  BM25 Lexical  │
│  Search (HNSW  │  │  Search        │
│  faiss engine) │  │                │
└───────┬────────┘  └───────┬────────┘
        │                    │
        └────────┬───────────┘
                 ▼
┌────────────────────────┐
│  Reciprocal Rank Fusion │  (weighted merge)
└────────┬───────────────┘
         │
         ▼
┌────────────────────────┐
│  Cohere Rerank v3.5    │  (Bedrock Rerank API)
└────────┬───────────────┘
         │
         ▼
Top-K policy passages (with relevance scores)
```

### WebSocket Message Protocol

```
Client → Server:  { question, thread_id, language, namespace }

Server → Client (stream events):
  { type: "stream", content_type: null,            message: "token..." }      # text token
  { type: "stream", content_type: "status_before", message: {tool info} }     # tool starting
  { type: "stream", content_type: "tool_start",    message: {tool info} }     # tool executing
  { type: "stream", content_type: "tool_end",      message: {result} }        # tool completed
  { type: "end",    content_type: "answer" }                                   # turn complete
```

### Voice Pipeline (full loop)

```
┌─── Speech-to-Text (Input) ───┐       ┌─── Text-to-Speech (Output) ───┐
│                               │       │                                │
│ User clicks mic               │       │ Streaming tokens arrive        │
│   → browser requests mic      │       │   → sentence boundary detect   │
│   → Web Speech API starts     │       │   → parallel /tts POST per     │
│   → interim transcription     │       │     sentence (edge-tts → MP3)  │
│   → final text in input       │       │   → ordered audio queue        │
│   → user presses Enter        │       │     (monotonic seq numbers)    │
│                               │       │   → sequential playback        │
└───────────────────────────────┘       └────────────────────────────────┘
```

Key behaviors:
- Content resets (acknowledgement wiped mid-turn) are detected — offset resyncs, no prefix drop
- Stop button immediately silences playback and aborts pending fetches
- Conversation switch aborts all in-flight audio and active mic recording
- Backend returns 204 for unspeakable content (symbols only) — frontend skips gracefully
- Mic auto-stops when: user types, user submits, agent starts streaming, conversation switches

---

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| LLM | Claude Sonnet 4 (AWS Bedrock) | Agent reasoning + decisions |
| Embeddings | Amazon Titan Embed Text v2 (1024d) | Policy vectorization |
| Reranking | Cohere Rerank v3.5 (Bedrock) | Result relevance scoring |
| Agent Framework | LangGraph 1.2.6 | ReAct cycle orchestration |
| Vector DB | OpenSearch Serverless (AOSS) | Policy storage + hybrid search |
| Relational DB | PostgreSQL | CRM, orders, refund decisions |
| Backend | FastAPI 0.138 + Uvicorn | REST + WebSocket server |
| Frontend | React 18 + TypeScript + Tailwind CSS | Chat UI + Admin dashboard |
| State Mgmt | Zustand | Frontend state |
| TTS | edge-tts (Microsoft Edge voices) | Voice responses |
| Observability | LangSmith | Agent traces, token/cost tracking |
| Checkpointing | langgraph-checkpoint-postgres | Conversation persistence |
| Auth | JWT (python-jose) + bcrypt | Token-based authentication |

---

## Prerequisites

- **Python 3.11+** (tested on 3.13)
- **Node.js 18+** (tested on 24.x)
- **npm 9+** (tested on 11.x)
- **AWS Account** with:
  - Bedrock model access enabled for: Claude Sonnet 4, Amazon Titan Embed Text v2, Cohere Rerank v3.5
  - OpenSearch Serverless collection (type: VECTORSEARCH)
  - PostgreSQL instance (with the CRM schema seeded — can be any PostgreSQL 14+)
  - IAM credentials with permissions for: bedrock, bedrock-agent-runtime, aoss, s3
- **LangSmith account** (optional but recommended for traces)

---

## Environment Setup

Create a `.env` file in the project root:

```env
# ─── AWS Credentials ───
AWS_ACCESS_KEY_ID=your_aws_access_key
AWS_SECRET_ACCESS_KEY=your_aws_secret_key
AWS_REGION_NAME=us-east-1

# ─── PostgreSQL ───
POSTGRES_HOST=your-postgres-host.example.com
POSTGRES_PORT=5432
POSTGRES_DATABASE=test
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_password
POSTGRES_SSLMODE=require
POSTGRES_SCHEMA=public

# ─── OpenSearch Serverless ───
OPENSEARCH_URL=your-collection-id.region.aoss.amazonaws.com
OPENSEARCH_PORT=443
OPENSEARCH_USE_SSL=true
OPENSEARCH_VERIFY_CERTS=true
OPENSEARCH_AUTH_METHOD=aws_sigv4
OPENSEARCH_INDEX_NAME=test_wp
POLICY_OPENSEARCH_INDEX_NAME=test_wp
POLICY_OPENSEARCH_NAMESPACE=shopassist
VECTOR_DATABASE_TO_USE=opensearch

# ─── LangSmith (Tracing) ───
LANGSMITH_API_KEY=your_langsmith_key
LANGSMITH_ENDPOINT=https://aws.smith.langchain.com
LANGSMITH_PROJECT=WorkPodd
LANGSMITH_TRACING=true

# ─── Checkpointing (conversation persistence) ───
CHECKPOINT_TYPE=postgres
CHECKPOINT_POSTGRES_HOST=your-postgres-host.example.com
CHECKPOINT_POSTGRES_PORT=5432
CHECKPOINT_POSTGRES_DATABASE=test
CHECKPOINT_POSTGRES_USER=postgres
CHECKPOINT_POSTGRES_PASSWORD=your_password
CHECKPOINT_POSTGRES_SSLMODE=require

# ─── Auth ───
JWT_SECRET_KEY=your_secret_key_minimum_32_characters

# ─── TTS Voice ───
TTS_VOICE=en-US-AriaNeural

# ─── Store ───
STORE_TYPE=postgres
STORE_POSTGRES_URI=postgresql://postgres:password@host:5432/test?sslmode=require
```

---

## Installation

```bash
# 1. Clone the repository
git clone <repository-url>
cd WorkPodd

# 2. Create and activate Python virtual environment
python3 -m venv .venv
source .venv/bin/activate        # macOS/Linux
# .venv\Scripts\activate         # Windows

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Install frontend dependencies
cd webapp-react
npm install
cd ..

# 5. Copy and fill environment variables
cp .env.example .env
# Edit .env with your AWS credentials, DB host, etc.
```

---

## Running the Application

```bash
# Make sure virtual environment is active
source .venv/bin/activate

# Start the application
python main.py
```

**What happens on startup:**
1. Builds the React frontend (outputs to `webapp-build/`)
2. Validates the PostgreSQL database connection and schema
3. Runs SQL validation queries against all refund tool sections
4. Initializes the LangGraph agent with 12 bound tools
5. Starts Uvicorn on **http://localhost:8000**

**First-time setup checklist:**
- [ ] PostgreSQL database is running and accessible
- [ ] Database schema is seeded (customers, orders tables with 15 profiles + 16 orders)
- [ ] OpenSearch Serverless collection exists with the policy index
- [ ] Policy PDF has been ingested (upload via the Admin sidebar once the app is running)
- [ ] `.env` is filled with all required values

---

## Policy Ingestion

The refund policy PDF is ingested into OpenSearch via the app's built-in ingestion pipeline:

1. Start the application (`python main.py`)
2. Log in as `admin`
3. In the left sidebar, click **Upload PDF** under "KNOWLEDGE BASE DOCUMENTS"
4. Select `ShopAssist_Refund_Policy.pdf`
5. The system chunks the PDF, generates embeddings (Amazon Titan Embed v2), and indexes into OpenSearch

This creates the vector index (`test_wp`) with namespace `shopassist`. The agent retrieves from this index on every refund request.

---

## Demo Credentials

| Username | Password | Role | Access |
|----------|----------|------|--------|
| `admin` | `admin123` | Admin | Chat + Admin Dashboard (reasoning logs, audit trail, LangSmith traces) |
| `agent` | `agent123` | Agent | Chat only |

---

## Features

### Chat Interface
- Real-time token-by-token streaming via WebSocket
- Tool execution cards showing each workflow step with status indicators
- Conversation history in the sidebar (persisted via LangGraph checkpointing)
- Quick-start example prompts on the welcome screen
- **Microphone voice input (STT)** — click the mic button to speak; browser transcribes speech to text in real-time (Web Speech API, works in Chrome/Edge)
- **Voice output (TTS)** — toggle speaker icon to hear the agent's responses spoken aloud
- Full voice conversation loop: speak → agent processes → agent speaks back
- Dark mode support
- Response timing display (time-to-first-byte / total)

### Agent Capabilities
- **15 CRM customer profiles** with varied tiers (standard/premium/VIP), flagged accounts, and refund histories
- **14 policy rules** enforced dynamically from the retrieved policy document:
  - Return windows by tier (standard 30d / premium 45d / VIP 60d)
  - Digital product non-refundable
  - Cancelled order auto-approve
  - Wrong item received (full refund regardless of window)
  - Flagged account denial (flag reason never disclosed)
  - Already-returned denial
  - Undelivered order denial
  - Defective item within window (troubleshoot first, then approve)
  - Defective item outside window (deny + manufacturer warranty referral)
  - Partial refund for customer-damaged items (up to 30% deduction)
  - Serial refund pattern monitoring (3+ refunds)
  - Item not received (route to support for carrier investigation)
  - Processing times by payment method (credit card / debit / PayPal / gift card)
  - Return shipping responsibility by scenario
- **Parallel tool execution** — independent actions fire simultaneously (verified in logs: 3 tools in one message)
- **VERDICT gate** — explicit DENY/APPROVE/CONDITIONAL determination before any action is taken; prevents the model from drifting into wrong decisions
- **Manipulation resistance** — prompt injection, fake supervisor claims, policy-override pressure, chargeback threats all silently deflected
- **Returns analytics** via text-to-SQL (natural language questions about return rates, trends, categories)
- **Escalation to human** when the customer requests a supervisor

### Admin Dashboard
- Total/approved/denied/pending decision counts with filter buttons
- Full audit table: customer, tier, order, amount requested vs approved, reason, denial detail, expandable agent reasoning
- Live LangSmith traces with run type, latency, token count, cost per run, and direct links
- Auto-refreshes every 10 seconds (silent background refresh — no flickering)
- Manual refresh button for immediate updates
- "View reasoning" expands the full step-by-step policy evaluation trace

### Voice Pipeline (STT + TTS)
**Speech-to-Text (Microphone Input):**
- Browser-native Web Speech API (no extra backend or API key needed)
- Real-time interim transcription displayed in the input field as user speaks
- Auto-stops on silence (non-continuous mode)
- Graceful fallback: mic button hidden if browser doesn't support STT (e.g. Firefox)
- Edge cases handled: permission denied (no flash), typing stops mic, submit stops mic, streaming starts stops mic, rapid double-click prevented, conversation-switch cleanup

**Text-to-Speech (Voice Output):**
- Sentence-level streaming — audio starts while the response is still generating
- Ordered playback with parallel fetches (monotonic sequence numbers — no out-of-order speech)
- Synced with on-screen text (no prefix drop, no duplication)
- Immediate silence on Stop button press
- Graceful handling of unspeakable content (symbols, empty text → 204 skip)
- Conversation-switch cleanup prevents audio bleed
- Backend buffered response (not streaming) for clean error handling

---

## Project Structure

```
WorkPodd/
├── main.py                          # FastAPI app, /tts endpoint, React build, startup
├── requirements.txt                 # Python dependencies (pinned versions)
├── .env                             # Environment variables (not committed)
├── screenshots/                     # UI screenshots for this README
│   ├── welcome-screen.png
│   ├── chat-interface.png
│   └── admin-dashboard.png
│
├── workflows/                       # Backend application code
│   ├── routes.py                    # WebSocket agent endpoint + REST routes
│   ├── service.py                   # Message generator orchestration
│   ├── generator.py                 # WebSocket stream processor (astream_events v2)
│   ├── graphs.py                    # LangGraph agent graph + model invocation
│   ├── tools.py                     # All 12 agent tools (refund, analytics, escalation)
│   ├── helper.py                    # Tool-call routing logic
│   ├── utils.py                     # Model binding utilities
│   ├── state_schema.py              # LangGraph state schema
│   ├── models.py                    # Pydantic request/response models
│   │
│   ├── prompts/
│   │   ├── agent_prompts.py         # Master agent system prompt (dynamic, no hardcoded policy)
│   │   └── utility_prompts.py       # Tool orchestration prompt
│   │
│   ├── auth/
│   │   ├── routes.py                # POST /auth/token, /auth/register (demo users)
│   │   ├── utils.py                 # JWT creation + bcrypt password hashing
│   │   ├── models.py                # Auth request/response models
│   │   └── db.py                    # Auth DB interface (MongoDB — optional)
│   │
│   └── core/
│       ├── settings.py              # All configuration (Pydantic Settings + env)
│       ├── llm.py                   # LLM + embedding model factory (Bedrock)
│       ├── handler.py               # Retry/backoff decorator
│       ├── store.py                 # LangGraph memory store setup
│       ├── token_handler.py         # Token counting utility
│       │
│       ├── db/
│       │   ├── client.py            # PostgreSQL query executor (all refund SQL)
│       │   ├── models.py            # DB models
│       │   └── utils.py             # Connection utilities
│       │
│       ├── vector_db/
│       │   ├── doc_search.py        # Document search orchestrator
│       │   ├── retrieval.py         # High-level retrieval (search + rerank)
│       │   ├── reranker.py          # Bedrock Cohere reranker
│       │   ├── sanitization.py      # Index/namespace name sanitization
│       │   └── opensearch_utils/
│       │       ├── client.py        # OpenSearch async client (hybrid search, index management)
│       │       └── utils.py         # Ingestion push utilities
│       │
│       ├── ingestion/
│       │   ├── routes.py            # POST /ingestion/ingest, GET /ingestion/documents
│       │   ├── models.py            # Ingestion models
│       │   └── utils.py             # PDF chunking + embedding pipeline
│       │
│       └── loader/
│           ├── file_loader.py       # PDF/document file loading
│           └── utils.py             # Loader utilities
│
├── webapp-react/                    # Frontend source (React + TypeScript + Tailwind)
│   ├── package.json                 # Frontend dependencies
│   ├── vite.config.ts               # Vite build config (outputs to ../webapp-build)
│   ├── tailwind.config.js           # Tailwind CSS config
│   └── src/
│       ├── App.tsx                   # Main app with tab routing (Chat/Admin)
│       ├── main.tsx                  # React entry point
│       ├── components/
│       │   ├── AdminDashboard.tsx    # Audit log + LangSmith traces + auto-refresh
│       │   ├── ChatInput.tsx         # Input + voice toggle + stop button
│       │   ├── ChatMessage.tsx       # Message rendering with timing badges
│       │   ├── Sidebar.tsx           # Conversations + document upload
│       │   ├── ToolExecutionCard.tsx # Collapsible tool step visualization
│       │   ├── WelcomeScreen.tsx     # Landing page with example prompts
│       │   └── ThinkingDots.tsx      # Loading animation
│       ├── services/
│       │   ├── websocket.ts          # WebSocket client + message routing
│       │   ├── streamingTts.ts       # TTS: ordered sentence-level playback
│       │   └── auth.ts              # JWT auth service
│       ├── store/
│       │   └── chatStore.ts          # Zustand state (messages, streaming, tools)
│       └── types/
│           └── websocket.types.ts    # TypeScript WebSocket message types
│
└── webapp-build/                    # Production React build (auto-generated, not committed)
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| **WebSocket** | `/ws/agent` | Real-time agent chat (streaming tokens + tool events) |
| POST | `/auth/token` | Login — returns JWT access token |
| POST | `/auth/register` | Registration (disabled in demo mode) |
| POST | `/ingestion/ingest` | Upload + ingest a PDF into the vector knowledge base |
| GET | `/ingestion/documents` | List all ingested policy documents |
| GET | `/workflows/refunds/decisions` | Audit log — all refund decisions with reasoning |
| GET | `/workflows/traces` | LangSmith trace data (latency, tokens, cost) |
| POST | `/tts` | Text-to-speech — returns MP3 audio (or 204 for unspeakable text) |
| POST | `/presigned-url` | Generate S3 presigned URL for file upload |
| GET | `/` | Serve the React SPA |

---

## Policy Retrieval (RAG Pipeline)

The refund policy is a PDF (`ShopAssist_Refund_Policy.pdf`) that has been chunked, embedded, and indexed in OpenSearch Serverless via the ingestion API.

| Property | Value |
|----------|-------|
| Index | `test_wp` |
| Namespace | `shopassist` |
| Vector field | `vector` (knn_vector, 1024 dimensions) |
| ANN method | HNSW, faiss engine, cosinesimil |
| Search | Hybrid (k-NN vector + BM25 lexical) |
| Fusion | Reciprocal Rank Fusion (weighted) |
| Reranking | Cohere Rerank v3.5 via Bedrock |

The agent retrieves the policy fresh on every refund request. The system prompt contains **NO hardcoded policy values** — all decisions (windows, deductions, processing times, return-shipping rules) come exclusively from the retrieved text. If the policy PDF is updated and re-ingested, the agent's behavior changes immediately.

---

## CRM Data Model

### Customers (15 profiles)

| ID | Name | Tier | Flagged | Test Purpose |
|----|------|------|---------|--------------|
| 1 | Alice Johnson | Standard | No | Defective within window (headphones) |
| 2 | Bob Martinez | Standard | No | Outside-window denial |
| 3 | Carol White | VIP | No | VIP 60-day window approval |
| 4 | David Kim | Standard | No | Undelivered order denial |
| 5 | Eva Patel | Premium | Yes | Flagged account (excessive refunds) |
| 6 | Frank Lee | Standard | No | Digital product denial |
| 7 | Grace Turner | VIP | No | High-value electronics + troubleshoot |
| 8 | Henry Davis | Standard | No | Cancelled order auto-approve |
| 9 | Irene Chen | Standard | No | Already-returned status denial |
| 10 | James Wilson | Premium | No | Wrong item received |
| 11 | Karen Brown | Standard | No | Defective within window (appliance) |
| 12 | Liam Murphy | Standard | No | Defective OUTSIDE window denial |
| 13 | Maria Garcia | Standard | No | Partial refund (worn clothing) |
| 14 | Noah Anderson | Standard | Yes | Chargeback fraud flag |
| 15 | Olivia Thompson | Premium | No | Premium 45-day window |

### Database Schema

```sql
CREATE TABLE customers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100),
    email VARCHAR(150) UNIQUE,
    account_tier VARCHAR(20),       -- standard | premium | vip
    is_flagged BOOLEAN DEFAULT false,
    flag_reason TEXT,
    total_refunds_issued INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    order_number VARCHAR(50) UNIQUE,
    customer_id INTEGER REFERENCES customers(id),
    product_name VARCHAR(200),
    category VARCHAR(50),
    amount DECIMAL(10,2),
    status VARCHAR(30),             -- delivered | shipped | cancelled | returned
    ordered_at TIMESTAMP,
    delivered_at TIMESTAMP,
    is_digital BOOLEAN DEFAULT false,
    payment_method VARCHAR(50)
);

CREATE TABLE refund_requests (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(id),
    order_id INTEGER REFERENCES orders(id),
    decision VARCHAR(20),           -- approved | denied | pending
    denial_reason TEXT,
    agent_reasoning TEXT,
    amount_requested DECIMAL(10,2),
    amount_approved DECIMAL(10,2) DEFAULT 0,
    refund_reason TEXT,
    requested_at TIMESTAMP DEFAULT NOW(),
    decided_at TIMESTAMP
);
```

---

## License

Proprietary - Diya

---

*Built with LangGraph, AWS Bedrock, OpenSearch Serverless, and React by Diya*
