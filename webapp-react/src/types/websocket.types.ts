// ===== WebSocket Event Types =====

export type ContentType =
  | 'answer'
  | 'tools'
  | 'tool_start'
  | 'tool_step'
  | 'tool_end'
  | 'tool_llm_start'
  | 'tool_llm_token'
  | 'tool_llm_end'
  | 'tool_status_start'
  | 'tool_status_token'
  | 'tool_status_end'
  | 'status_before'
  | 'agent_thinking'
  | 'processing'
  | 'usage_stats'
  | null;

export type MessageType =
  | 'start'
  | 'stream'
  | 'end'
  | 'error'
  | 'ping';

// ===== Tool Messages =====

export interface ToolMessage {
  type: 'tool';
  tool_key: string;
  tool_name: string;
  tool_content: string;
}



export interface ToolLLMStartMessage {
  tool_key: string;
  tool_name: string;
  llm_type: string;
}

export interface ToolLLMTokenMessage {
  tool_key: string;
  token: string;
  token_type: string;
}

export interface ToolLLMEndMessage {
  tool_key: string;
  tool_name: string;
  content: string;
}

// ===== WebSocket Messages =====

export interface BaseWebSocketMessage {
  type: MessageType;
  content_type: ContentType;
  message: string | ToolMessage | Record<string, any>;
}

export interface StartMessage extends BaseWebSocketMessage {
  type: 'start';
  content_type: ContentType;
  message: '';
}

export interface StreamMessage extends BaseWebSocketMessage {
  type: 'stream';
  content_type: ContentType;
  message: string | ToolMessage | Record<string, any>;
}

export interface EndMessage extends BaseWebSocketMessage {
  type: 'end';
  content_type: ContentType;
  message: '';
}

export interface ErrorMessage extends BaseWebSocketMessage {
  type: 'error';
  content_type: null;
  message: string;
}

export interface PingMessage extends BaseWebSocketMessage {
  type: 'ping';
  content_type: null;
  message: string;
}

export type WebSocketMessage =
  | StartMessage
  | StreamMessage
  | EndMessage
  | ErrorMessage
  | PingMessage;

// ===== Request Types =====

export interface ChatRequest {
  question: string;
  language: string;
  thread_id: string;
  namespace?: string;
  graph_initialization?: boolean;
}

// ===== UI State Types =====

export interface ToolExecution {
  tool_key: string;
  tool_name: string;
  tool_id?: string;
  tool_description?: string;
  steps: Array<{
    id: string;
    content: string;
    timestamp: number;
    type: 'progress' | 'success' | 'info' | 'error' | 'input';
    isStreaming?: boolean;
  }>;
  llm_stream: {
    isStreaming: boolean;
    content: string;
    llm_type: string;
  };
  isExecuting: boolean;
  startTime: number;
  endTime?: number;
}

export interface UsageStats {
  input_tokens: number;
  output_tokens: number;
  cache_read: number;
  cache_creation: number;
}

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  tool_executions?: ToolExecution[];
  is_streaming?: boolean;
  agent_thinking?: string;
  response_time?: number | null;
  total_response_time?: number | null;
  usage_stats?: UsageStats | null;
  feedback?: 'positive' | 'negative';
}

export interface Conversation {
  id: string;
  thread_id: string;
  title: string;
  messages: Message[];
  created_at: number;
  updated_at: number;
}

// ===== User Types =====

export interface User {
  emp_id: string;
  token?: string;
  role?: string;
  avatar?: string;
}
