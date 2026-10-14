import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

const debouncedStorage = (() => {
  let timer: ReturnType<typeof setTimeout> | null = null;
  let pendingName: string | null = null;
  let pendingValue: string | null = null;

  const flush = () => {
    if (pendingName !== null && pendingValue !== null) {
      localStorage.setItem(pendingName, pendingValue);
    }
    if (timer !== null) clearTimeout(timer);
    timer = null;
    pendingName = null;
    pendingValue = null;
  };

  if (typeof window !== 'undefined') {
    window.addEventListener('beforeunload', flush);
  }

  return {
    getItem: (name: string) => localStorage.getItem(name),
    setItem: (name: string, value: string) => {
      pendingName = name;
      pendingValue = value;
      if (timer !== null) clearTimeout(timer);
      timer = setTimeout(flush, 2000);
    },
    removeItem: (name: string) => localStorage.removeItem(name),
  };
})();

import type {
  Conversation,
  Message,
  ToolExecution,
  UsageStats,
  User,
} from '../types/websocket.types';

interface ChatState {
  user: User | null;
  isAuthenticated: boolean;

  conversations: Conversation[];
  currentConversationId: string | null;

  currentMessage: Message | null;
  currentToolExecutions: Map<string, ToolExecution>;
  isStreaming: boolean;
  isWaitingForResponse: boolean;
  isProcessing: boolean;
  agentThinking: string | null;
  lastAgentThinking: string | null;
  requestStartTime: number | null;
  firstByteTime: number | null;
  responseTime: number | null;
  currentUsageStats: UsageStats | null;

  isSidebarOpen: boolean;
  isDarkMode: boolean;
  isConnected: boolean;

  setUser: (user: User) => void;
  logout: () => void;

  createConversation: (threadId: string) => void;
  setCurrentConversation: (id: string) => void;
  deleteConversation: (id: string) => void;
  updateConversationTitle: (id: string, title: string) => void;

  addUserMessage: (content: string) => void;
  startAssistantMessage: () => void;
  appendToAssistantMessage: (content: string) => void;
  clearMessageContent: () => void;
  completeAssistantMessage: () => void;
  addErrorMessage: (error: string) => void;

  startToolExecution: (toolKey: string, toolName: string, toolId?: string, toolDescription?: string) => void;
  addToolStep: (toolKey: string, content: string, type: 'progress' | 'success' | 'info' | 'error' | 'input') => void;
  startToolLLMStream: (toolKey: string, llmType: string) => void;
  appendToolLLMToken: (toolKey: string, token: string) => void;
  endToolLLMStream: (toolKey: string, content: string) => void;
  startToolStatusStream: (toolKey: string) => void;
  appendToolStatusToken: (toolKey: string, token: string) => void;
  endToolStatusStream: (toolKey: string) => void;
  completeToolExecution: (toolKey: string) => void;

  setStreaming: (isStreaming: boolean) => void;
  setWaitingForResponse: (waiting: boolean) => void;
  setProcessing: (processing: boolean) => void;
  setAgentThinking: (text: string | null) => void;
  promoteToAgentThinking: (statusMessage: string) => void;
  stampFirstByte: () => void;
  setUsageStats: (stats: UsageStats) => void;

  setMessageFeedback: (messageId: string, feedback: 'positive' | 'negative' | undefined) => void;

  voiceEnabled: boolean;
  toggleVoice: () => void;

  toggleSidebar: () => void;
  setSidebarOpen: (open: boolean) => void;
  toggleDarkMode: () => void;
  setConnected: (connected: boolean) => void;
}

const generateId = () => Math.random().toString(36).substring(2, 11);

export const useChatStore = create<ChatState>()(
  persist(
    (set, get) => ({
      user: null,
      isAuthenticated: false,
      conversations: [],
      currentConversationId: null,
      currentMessage: null,
      currentToolExecutions: new Map(),
      isStreaming: false,
      isWaitingForResponse: false,
      isProcessing: false,
      agentThinking: null,
      lastAgentThinking: null,
      requestStartTime: null,
      firstByteTime: null,
      responseTime: null,
      currentUsageStats: null,
      isSidebarOpen: true,
      isDarkMode: false,
      isConnected: false,
      voiceEnabled: false,

      setUser: (user) => set({ user, isAuthenticated: true }),

      logout: () => set({
        user: null,
        isAuthenticated: false,
        conversations: [],
        currentConversationId: null
      }),

      createConversation: (threadId) => {
        const newConversation: Conversation = {
          id: generateId(),
          thread_id: threadId,
          title: 'New conversation',
          messages: [],
          created_at: Date.now(),
          updated_at: Date.now(),
        };

        set((state) => ({
          conversations: [newConversation, ...state.conversations],
          currentConversationId: newConversation.id,
          currentMessage: null,
        }));
      },

      setCurrentConversation: (id) => set({
        currentConversationId: id,
        currentMessage: null,
        currentToolExecutions: new Map(),
        isStreaming: false,
        isWaitingForResponse: false,
        isProcessing: false,
        agentThinking: null,
        lastAgentThinking: null,
      }),

      deleteConversation: (id) => set((state) => ({
        conversations: state.conversations.filter((c) => c.id !== id),
        currentConversationId:
          state.currentConversationId === id ? null : state.currentConversationId,
      })),

      updateConversationTitle: (id, title) => set((state) => ({
        conversations: state.conversations.map((c) =>
          c.id === id ? { ...c, title, updated_at: Date.now() } : c
        ),
      })),

      addUserMessage: (content) => {
        const { currentConversationId } = get();
        if (!currentConversationId) return;

        const now = Date.now();
        const newMessage: Message = {
          id: generateId(),
          role: 'user',
          content,
          timestamp: now,
        };

        set((state) => ({
          conversations: state.conversations.map((c) =>
            c.id === currentConversationId
              ? {
                  ...c,
                  messages: [...c.messages, newMessage],
                  updated_at: now,
                  title: c.messages.length === 0
                    ? content.substring(0, 50) + (content.length > 50 ? '...' : '')
                    : c.title,
                }
              : c
          ),
          currentMessage: null,
          currentToolExecutions: new Map(),
          isStreaming: false,
          isWaitingForResponse: true,
          agentThinking: null,
          lastAgentThinking: null,
          requestStartTime: now,
          firstByteTime: null,
          responseTime: null,
          currentUsageStats: null,
        }));
      },

      startAssistantMessage: () => {
        const newMessage: Message = {
          id: generateId(),
          role: 'assistant',
          content: '',
          timestamp: Date.now(),
          is_streaming: true,
          response_time: null,
        };

        set({
          currentMessage: newMessage,
          isStreaming: true,
        });
      },

      appendToAssistantMessage: (content) => {
        set((state) => {
          if (!state.currentMessage) return state;
          return {
            currentMessage: {
              ...state.currentMessage,
              content: state.currentMessage.content + content,
            },
          };
        });
      },

      clearMessageContent: () => {
        set((state) => {
          if (!state.currentMessage) return state;
          return {
            currentMessage: {
              ...state.currentMessage,
              content: '',
            },
          };
        });
      },

      completeAssistantMessage: () => {
        const { currentMessage, currentConversationId, currentToolExecutions, lastAgentThinking, firstByteTime, requestStartTime, currentUsageStats } = get();
        if (!currentMessage || !currentConversationId) return;

        const now = Date.now();
        const totalResponseTime = requestStartTime ? now - requestStartTime : null;

        const toolExecutionsArray = Array.from(currentToolExecutions.values()).map((exec) => ({
          ...exec,
          isExecuting: false,
          endTime: exec.endTime ?? now,
        }));

        const completedMessage: Message = {
          ...currentMessage,
          is_streaming: false,
          tool_executions: toolExecutionsArray.length > 0 ? toolExecutionsArray : undefined,
          agent_thinking: lastAgentThinking || undefined,
          response_time: firstByteTime,
          total_response_time: totalResponseTime,
          usage_stats: currentUsageStats,
        };

        set((state) => ({
          conversations: state.conversations.map((c) =>
            c.id === currentConversationId
              ? {
                  ...c,
                  messages: [...c.messages, completedMessage],
                  updated_at: Date.now(),
                }
              : c
          ),
          currentMessage: null,
          isStreaming: false,
          isWaitingForResponse: false,
          isProcessing: false,
          agentThinking: null,
          lastAgentThinking: null,
          currentToolExecutions: new Map(),
          responseTime: firstByteTime,
          firstByteTime: null,
          requestStartTime: null,
          currentUsageStats: null,
        }));
      },

      addErrorMessage: (error) => {
        const { currentConversationId } = get();
        if (!currentConversationId) return;

        const errorMessage: Message = {
          id: generateId(),
          role: 'assistant',
          content: `Error: ${error}`,
          timestamp: Date.now(),
        };

        set((state) => ({
          conversations: state.conversations.map((c) =>
            c.id === currentConversationId
              ? {
                  ...c,
                  messages: [...c.messages, errorMessage],
                  updated_at: Date.now(),
                }
              : c
          ),
          currentMessage: null,
          currentToolExecutions: new Map(),
          isStreaming: false,
          isWaitingForResponse: false,
          isProcessing: false,
          agentThinking: null,
          lastAgentThinking: null,
        }));
      },

      startToolExecution: (toolKey, toolName, toolId, toolDescription) => {
        set((state) => {
          const newExecutions = new Map(state.currentToolExecutions);
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
          return { currentToolExecutions: newExecutions };
        });
      },

      addToolStep: (toolKey, content, type) => {
        set((state) => {
          const newExecutions = new Map(state.currentToolExecutions);
          const execution = newExecutions.get(toolKey);

          if (execution) {
            const newStep = {
              id: generateId(),
              content,
              timestamp: Date.now(),
              type,
            };
            execution.steps.push(newStep);
            newExecutions.set(toolKey, { ...execution });
          }

          return { currentToolExecutions: newExecutions };
        });
      },

      completeToolExecution: (toolKey) => {
        set((state) => {
          const newExecutions = new Map(state.currentToolExecutions);
          const execution = newExecutions.get(toolKey);

          if (execution) {
            execution.isExecuting = false;
            execution.endTime = Date.now();
            newExecutions.set(toolKey, { ...execution });
          }

          return { currentToolExecutions: newExecutions };
        });
      },

      startToolLLMStream: (toolKey, llmType) => {
        set((state) => {
          const newExecutions = new Map(state.currentToolExecutions);
          const execution = newExecutions.get(toolKey);

          if (execution) {
            execution.llm_stream = { isStreaming: true, content: '', llm_type: llmType };
            newExecutions.set(toolKey, { ...execution });
          }

          return { currentToolExecutions: newExecutions };
        });
      },

      appendToolLLMToken: (toolKey, token) => {
        set((state) => {
          const newExecutions = new Map(state.currentToolExecutions);
          const execution = newExecutions.get(toolKey);

          if (execution && execution.llm_stream) {
            execution.llm_stream = {
              ...execution.llm_stream,
              content: execution.llm_stream.content + token
            };
            newExecutions.set(toolKey, { ...execution });
          }

          return { currentToolExecutions: newExecutions };
        });
      },

      endToolLLMStream: (toolKey, content) => {
        set((state) => {
          const newExecutions = new Map(state.currentToolExecutions);
          const execution = newExecutions.get(toolKey);

          if (execution && execution.llm_stream) {
            execution.llm_stream = {
              ...execution.llm_stream,
              isStreaming: false,
              content: content || execution.llm_stream.content
            };
            newExecutions.set(toolKey, { ...execution });
          }

          return { currentToolExecutions: newExecutions };
        });
      },

      startToolStatusStream: (toolKey) => {
        set((state) => {
          const newExecutions = new Map(state.currentToolExecutions);
          const execution = newExecutions.get(toolKey);

          if (execution) {
            const newStep = {
              id: generateId(),
              content: '',
              type: 'progress' as const,
              timestamp: Date.now(),
              isStreaming: true
            };
            execution.steps = [...execution.steps, newStep];
            newExecutions.set(toolKey, { ...execution });
          }

          return { currentToolExecutions: newExecutions };
        });
      },

      appendToolStatusToken: (toolKey, token) => {
        set((state) => {
          const execution = state.currentToolExecutions.get(toolKey);
          if (!execution || execution.steps.length === 0) return state;

          const lastStep = execution.steps[execution.steps.length - 1];
          if (!lastStep.isStreaming) return state;

          const newExecutions = new Map(state.currentToolExecutions);
          const updatedSteps = [...execution.steps];
          updatedSteps[updatedSteps.length - 1] = {
            ...lastStep,
            content: lastStep.content + token
          };
          newExecutions.set(toolKey, { ...execution, steps: updatedSteps });

          return { currentToolExecutions: newExecutions };
        });
      },

      endToolStatusStream: (toolKey) => {
        set((state) => {
          const newExecutions = new Map(state.currentToolExecutions);
          const execution = newExecutions.get(toolKey);

          if (execution && execution.steps.length > 0) {
            const lastStep = execution.steps[execution.steps.length - 1];
            if (lastStep.isStreaming) {
              const updatedSteps = [...execution.steps];
              updatedSteps[updatedSteps.length - 1] = {
                ...lastStep,
                isStreaming: false
              };
              execution.steps = updatedSteps;
              newExecutions.set(toolKey, { ...execution });
            }
          }

          return { currentToolExecutions: newExecutions };
        });
      },

      setStreaming: (isStreaming) => set({ isStreaming }),
      setWaitingForResponse: (waiting) => set({ isWaitingForResponse: waiting }),
      setProcessing: (processing) => set({ isProcessing: processing }),
      setAgentThinking: (text) => {
        const update: Record<string, unknown> = { agentThinking: text };
        if (text && text !== '...') {
          update.lastAgentThinking = text;
        }
        set(update as any);
      },

      promoteToAgentThinking: (statusMessage: string) => {
        set((state) => {
          const result: Record<string, unknown> = {
            agentThinking: statusMessage,
            lastAgentThinking: statusMessage,
          };
          if (state.currentMessage?.content) {
            const currentContent = state.currentMessage.content.trim();
            const statusTrimmed = statusMessage.trim();
            if (
              currentContent === statusTrimmed ||
              statusTrimmed.startsWith(currentContent) ||
              currentContent.startsWith(statusTrimmed)
            ) {
              result.currentMessage = { ...state.currentMessage, content: '' };
            }
          }
          return result;
        });
      },

      setUsageStats: (stats) => set({ currentUsageStats: stats }),

      stampFirstByte: () => {
        const { firstByteTime, requestStartTime } = get();
        if (firstByteTime !== null) return;
        if (!requestStartTime) return;
        set({ firstByteTime: Date.now() - requestStartTime });
      },

      setMessageFeedback: (messageId, feedback) => set((state) => ({
        conversations: state.conversations.map((c) => ({
          ...c,
          messages: c.messages.map((m) =>
            m.id === messageId ? { ...m, feedback } : m
          ),
        })),
      })),

      setConnected: (connected) => set({ isConnected: connected }),
      toggleVoice: () => set((state) => ({ voiceEnabled: !state.voiceEnabled })),
      toggleSidebar: () => set((state) => ({ isSidebarOpen: !state.isSidebarOpen })),
      setSidebarOpen: (open) => set({ isSidebarOpen: open }),
      toggleDarkMode: () => set((state) => {
        const next = !state.isDarkMode;
        document.documentElement.classList.toggle('dark', next);
        return { isDarkMode: next };
      }),
    }),
    {
      name: 'chatai-storage',
      storage: createJSONStorage(() => debouncedStorage),
      partialize: (state) => ({
        user: state.user,
        isAuthenticated: state.isAuthenticated,
        conversations: state.conversations.map((c) => ({
          ...c,
          messages: c.messages.slice(-200),
        })),
        currentConversationId: state.currentConversationId,
        isDarkMode: state.isDarkMode,
      }),
      onRehydrateStorage: () => (state) => {
        if (state?.isDarkMode) {
          document.documentElement.classList.add('dark');
        }
      },
    }
  )
);
