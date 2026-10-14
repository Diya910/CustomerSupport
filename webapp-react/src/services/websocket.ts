import { useChatStore } from '../store/chatStore';
import type {
  WebSocketMessage,
  ChatRequest,
  ToolMessage,
  ToolLLMStartMessage,
  ToolLLMTokenMessage,
  ToolLLMEndMessage,
} from '../types/websocket.types';

class WebSocketService {
  private ws: WebSocket | null = null;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 20;
  private baseReconnectDelay = 3000;
  private maxReconnectDelay = 30000;
  private isConnecting = false;
  private shouldReconnect = true;
  private messageQueue: ChatRequest[] = [];
  private tokenBuffer = '';
  private rafId: number | null = null;
  private toolStartQueue: Array<{ toolKey: string; toolName: string; toolId: string; toolDescription: string }> = [];
  private toolStartTimer: ReturnType<typeof setTimeout> | null = null;

  connect() {
    if (this.ws?.readyState === WebSocket.OPEN || this.isConnecting) {
      return;
    }

    this.shouldReconnect = true;
    this.isConnecting = true;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const token = useChatStore.getState().user?.token;
    const tokenParam = token ? `?auth_token=${encodeURIComponent(token)}` : '';
    const basePath = import.meta.env.BASE_URL.replace(/\/$/, '');
    const baseUrl = `${protocol}//${window.location.host}${basePath}/workflows/stream${tokenParam}`;

    try {
      this.ws = new WebSocket(baseUrl);

      this.ws.onopen = () => {
        this.isConnecting = false;
        this.reconnectAttempts = 0;
        useChatStore.getState().setConnected(true);

        while (this.messageQueue.length > 0) {
          const message = this.messageQueue.shift();
          if (message) {
            this.sendMessage(message);
          }
        }
      };

      this.ws.onmessage = (event) => {
        try {
          const data: WebSocketMessage = JSON.parse(event.data);
          this.handleMessage(data);
        } catch (error) {
          console.error('Failed to parse WebSocket message:', error);
        }
      };

      this.ws.onerror = () => {
        this.isConnecting = false;
      };

      this.ws.onclose = () => {
        this.isConnecting = false;
        this.ws = null;
        this.stopFlushLoop();
        useChatStore.getState().setConnected(false);

        const store = useChatStore.getState();
        if (store.isStreaming || store.isWaitingForResponse) {
          if (store.currentMessage) {
            store.completeAssistantMessage();
          } else {
            store.setStreaming(false);
            store.setWaitingForResponse(false);
            store.setProcessing(false);
            store.setAgentThinking(null);
            useChatStore.setState({ currentToolExecutions: new Map() });
          }
        }

        if (this.shouldReconnect && this.reconnectAttempts < this.maxReconnectAttempts) {
          this.reconnectAttempts++;
          const delay = Math.min(this.baseReconnectDelay * Math.pow(2, this.reconnectAttempts - 1), this.maxReconnectDelay);
          setTimeout(() => this.connect(), delay);
        } else if (!this.shouldReconnect) {
          this.messageQueue = [];
        }
      };
    } catch (error) {
      console.error('Failed to create WebSocket connection:', error);
      this.isConnecting = false;
    }
  }

  disconnect() {
    this.shouldReconnect = false;
    this.stopFlushLoop();
    this.messageQueue = [];
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  sendMessage(request: ChatRequest) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this.messageQueue.push(request);
      this.connect();
      return;
    }

    try {
      this.ws.send(JSON.stringify(request));
    } catch (error) {
      console.error('Failed to send message:', error);
    }
  }

  sendCancel() {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: 'cancel' }));
    }
  }

  private handleMessage(data: WebSocketMessage) {
    switch (data.type) {
      case 'ping':
        break;

      case 'start':
        this.handleStart(data);
        break;

      case 'stream':
        this.handleStream(data);
        break;

      case 'end':
        this.handleEnd(data);
        break;

      case 'error':
        this.handleError(data);
        break;
    }
  }

  private handleStart(data: WebSocketMessage) {
    const store = useChatStore.getState();

    switch (data.content_type) {
      case 'answer':
        this.stopFlushLoop();
        if (!store.currentMessage && !store.isStreaming) {
          store.startAssistantMessage();
        }
        break;
    }
  }

  private streamHandlers: Record<string, (message: any) => void> = {
    'tool_start': (m) => this.handleToolStart(m),
    'status_before': (m) => this.handleStatusBefore(m),
    'tool_step': (m) => this.handleToolStep(m),
    'tool_end': (m) => this.handleToolEnd(m),
    'tools': (m) => this.handleToolStream(m),
    'agent_thinking': (m) => this.handleAgentThinking(m),
    'tool_llm_start': (m) => this.handleToolLLMStart(m),
    'tool_llm_token': (m) => this.handleToolLLMToken(m),
    'tool_llm_end': (m) => this.handleToolLLMEnd(m),
    'tool_status_start': (m) => this.handleToolStatusStart(m),
    'tool_status_token': (m) => this.handleToolStatusToken(m),
    'tool_status_end': (m) => this.handleToolStatusEnd(m),
    'processing': (m) => this.handleProcessing(m),
    'answer': (m) => this.handleAnswerStream(m),
    'usage_stats': (m) => this.handleUsageStats(m),
  };

  private startFlushLoop() {
    if (this.rafId !== null) return;
    const flush = () => {
      if (this.tokenBuffer.length > 0) {
        const chunk = this.tokenBuffer;
        this.tokenBuffer = '';
        useChatStore.setState((state) => {
          if (!state.currentMessage) return state;
          return {
            currentMessage: {
              ...state.currentMessage,
              content: state.currentMessage.content + chunk,
            },
          };
        });
      }
      this.rafId = requestAnimationFrame(flush);
    };
    this.rafId = requestAnimationFrame(flush);
  }

  private stopFlushLoop() {
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId);
      this.rafId = null;
    }
    if (this.tokenBuffer.length > 0) {
      const chunk = this.tokenBuffer;
      this.tokenBuffer = '';
      useChatStore.setState((state) => {
        if (!state.currentMessage) return state;
        return {
          currentMessage: {
            ...state.currentMessage,
            content: state.currentMessage.content + chunk,
          },
        };
      });
    }
  }

  private handleAnswerStream(message: any) {
    if (typeof message !== 'string' || !message) return;
    const state = useChatStore.getState();
    if (!state.currentMessage) {
      state.startAssistantMessage();
    }
    this.tokenBuffer += message;
    this.startFlushLoop();
  }

  private handleStream(data: WebSocketMessage) {
    if (data.content_type === null || data.content_type === undefined) {
      if (typeof data.message === 'string') {
        const state = useChatStore.getState();
        if (!state.currentMessage) {
          useChatStore.getState().startAssistantMessage();
        }

        if (state.firstByteTime === null && state.requestStartTime) {
          useChatStore.setState({
            firstByteTime: Date.now() - state.requestStartTime,
            isProcessing: false,
            agentThinking: state.agentThinking === '...' ? null : state.agentThinking,
          });
        } else if (state.isProcessing || state.agentThinking === '...') {
          useChatStore.setState({
            isProcessing: false,
            agentThinking: state.agentThinking === '...' ? null : state.agentThinking,
          });
        }

        this.tokenBuffer += data.message;
        this.startFlushLoop();
      }
      return;
    }

    const handler = this.streamHandlers[data.content_type];
    if (handler) {
      handler(data.message);
    }
  }

  private handleEnd(data: WebSocketMessage) {
    this.stopFlushLoop();
    const store = useChatStore.getState();

    if (data.content_type === 'answer') {
      store.completeAssistantMessage();
      if (store.isStreaming || store.isWaitingForResponse || store.isProcessing) {
        store.setStreaming(false);
        store.setWaitingForResponse(false);
        store.setProcessing(false);
        store.setAgentThinking(null);
        useChatStore.setState({ currentToolExecutions: new Map(), requestStartTime: null });
      }
    }

    if (data.content_type === null || data.content_type === undefined) {
      if (store.isStreaming || store.isWaitingForResponse || store.isProcessing) {
        if (store.currentMessage) {
          store.completeAssistantMessage();
        } else {
          store.setStreaming(false);
          store.setWaitingForResponse(false);
          store.setProcessing(false);
          store.setAgentThinking(null);
          useChatStore.setState({ currentToolExecutions: new Map() });
        }
      }
    }
  }

  private handleError(data: WebSocketMessage) {
    this.stopFlushLoop();
    const store = useChatStore.getState();
    const errorMessage = typeof data.message === 'string' ? data.message : 'Unknown error';
    store.addErrorMessage(errorMessage);
  }

  private handleStatusBefore(message: any) {
    const store = useChatStore.getState();
    const statusMessage = message?.status_message;
    if (!statusMessage) return;

    if (!store.currentMessage && !store.isStreaming) {
      store.startAssistantMessage();
    }

    store.stampFirstByte();
    if (store.isProcessing) {
      store.setProcessing(false);
    }

    if (store.agentThinking) {
      store.clearMessageContent();
    } else {
      store.promoteToAgentThinking(statusMessage);
    }

    const toolKey = message?.tool_key;
    const toolName = message?.tool_name;
    if (toolKey !== undefined && toolName) {
      store.startToolExecution(String(toolKey), toolName, message?.tool_id);
    }
  }

  private handleToolStart(message: any) {
    const toolKey = message?.tool_key !== undefined ? String(message.tool_key) : `tool-${Date.now()}`;
    const toolName = message?.tool_name || 'Unknown Tool';
    const toolId = message?.tool_id || '';
    const toolDescription = message?.tool_description || '';

    const store = useChatStore.getState();
    if (!store.currentMessage && !store.isStreaming) {
      store.startAssistantMessage();
    }

    this.toolStartQueue.push({ toolKey, toolName, toolId, toolDescription });
    if (!this.toolStartTimer) {
      this.processToolStartQueue();
    }
  }

  private processToolStartQueue() {
    if (this.toolStartQueue.length === 0) {
      this.toolStartTimer = null;
      return;
    }

    const { toolKey, toolName, toolId, toolDescription } = this.toolStartQueue.shift()!;

    useChatStore.setState((state) => {
      let firstByteTime = state.firstByteTime;
      if (firstByteTime === null && state.requestStartTime) {
        firstByteTime = Date.now() - state.requestStartTime;
      }

      const newExecutions = new Map(state.currentToolExecutions);
      const existing = newExecutions.get(toolKey);
      if (!existing) {
        newExecutions.set(toolKey, {
          tool_key: toolKey,
          tool_name: toolName,
          tool_id: toolId,
          tool_description: toolDescription,
          steps: [],
          llm_stream: { isStreaming: false, content: '', llm_type: '' },
          isExecuting: true,
          startTime: Date.now(),
        });
      } else {
        newExecutions.set(toolKey, { ...existing, tool_id: toolId || existing.tool_id, tool_description: toolDescription || existing.tool_description, isExecuting: true });
      }

      return {
        firstByteTime,
        isProcessing: false,
        currentToolExecutions: newExecutions,
      };
    });

    if (this.toolStartQueue.length > 0) {
      this.toolStartTimer = setTimeout(() => this.processToolStartQueue(), 150);
    } else {
      this.toolStartTimer = null;
    }
  }

  private handleToolStep(message: any) {
    const toolKey = message?.tool_key !== undefined ? String(message.tool_key) : null;
    const stepContent = message?.step_content;
    if (!toolKey || !stepContent) return;

    useChatStore.getState().addToolStep(toolKey, stepContent, message?.step_type || 'info');
  }

  private handleToolEnd(message: any) {
    const toolKey = message?.tool_key !== undefined ? String(message.tool_key) : null;
    if (!toolKey) return;
    useChatStore.getState().completeToolExecution(toolKey);
  }

  private handleToolStream(message: ToolMessage) {
    const store = useChatStore.getState();
    const toolKey = String(message.tool_key);
    store.startToolExecution(toolKey, message.tool_name);
    if (message.tool_content?.trim()) {
      store.addToolStep(toolKey, message.tool_content, 'info');
    }
  }

  private handleAgentThinking(message: string | { status: string }) {
    const store = useChatStore.getState();
    const thinkingText = typeof message === 'string' ? message : message?.status;

    if (thinkingText === '' || thinkingText === null || thinkingText === undefined) {
      store.setAgentThinking(null);
      return;
    }

    if (thinkingText !== '...') {
      store.stampFirstByte();
    }
    store.setAgentThinking(thinkingText);
  }

  private handleProcessing(message: any) {
    if (message?.status !== 'started') return;

    const store = useChatStore.getState();
    store.setProcessing(true);
    store.setWaitingForResponse(false);
    if (!store.currentMessage && !store.isStreaming) {
      store.startAssistantMessage();
    }
  }

  private handleToolLLMStart(message: ToolLLMStartMessage) {
    useChatStore.getState().startToolLLMStream(String(message.tool_key), message.llm_type);
  }

  private handleToolLLMToken(message: ToolLLMTokenMessage) {
    useChatStore.getState().appendToolLLMToken(String(message.tool_key), message.token);
  }

  private handleToolLLMEnd(message: ToolLLMEndMessage) {
    useChatStore.getState().endToolLLMStream(String(message.tool_key), message.content);
  }

  private handleToolStatusStart(message: any) {
    if (message?.tool_key === undefined) return;
    useChatStore.getState().startToolStatusStream(String(message.tool_key));
  }

  private handleToolStatusToken(message: any) {
    if (message?.tool_key === undefined || !message?.token) return;
    useChatStore.getState().appendToolStatusToken(String(message.tool_key), message.token);
  }

  private handleToolStatusEnd(message: any) {
    if (message?.tool_key === undefined) return;
    useChatStore.getState().endToolStatusStream(String(message.tool_key));
  }

  private handleUsageStats(message: any) {
    if (!message) return;
    useChatStore.getState().setUsageStats({
      input_tokens: message.input_tokens ?? 0,
      output_tokens: message.output_tokens ?? 0,
      cache_read: message.cache_read ?? 0,
      cache_creation: message.cache_creation ?? 0,
    });
  }

  isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }
}

export const websocketService = new WebSocketService();
