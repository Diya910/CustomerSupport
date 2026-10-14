import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { loginWithCredentials } from './services/auth';
import { AnimatePresence } from 'framer-motion';
import { Menu, MessageSquare, LayoutDashboard } from 'lucide-react';
import { useChatStore } from './store/chatStore';
import { websocketService } from './services/websocket';
// logo removed
import { Sidebar } from './components/Sidebar';
import { ChatMessage } from './components/ChatMessage';
import { ChatInput } from './components/ChatInput';
import { WelcomeScreen } from './components/WelcomeScreen';
import { ThinkingDots } from './components/ThinkingDots';
import { AdminDashboard } from './components/AdminDashboard';

function App() {
  const isSidebarOpen = useChatStore((s) => s.isSidebarOpen);
  const toggleSidebar = useChatStore((s) => s.toggleSidebar);
  const isConnected = useChatStore((s) => s.isConnected);
  const currentConversationId = useChatStore((s) => s.currentConversationId);
  const conversations = useChatStore((s) => s.conversations);
  const currentMessage = useChatStore((s) => s.currentMessage);
  const isStreaming = useChatStore((s) => s.isStreaming);
  const isWaitingForResponse = useChatStore((s) => s.isWaitingForResponse);
  const agentThinking = useChatStore((s) => s.agentThinking);
  const toolExecutionCount = useChatStore((s) => s.currentToolExecutions.size);
  const setUser = useChatStore((s) => s.setUser);
  const user = useChatStore((s) => s.user);
  const isAuthenticated = useChatStore((s) => s.isAuthenticated);

  const chatContainerRef = useRef<HTMLDivElement>(null);
  const shouldAutoScroll = useRef(true);
  const [empId, setEmpId] = useState('');
  const [password, setPassword] = useState('');
  const [authError, setAuthError] = useState('');
  const [activeTab, setActiveTab] = useState<'chat' | 'admin'>('chat');

  const currentConversation = useMemo(
    () => conversations.find((c) => c.id === currentConversationId),
    [conversations, currentConversationId]
  );
  const hasMessages = currentConversation && currentConversation.messages.length > 0;
  const isLoggedIn = isAuthenticated;

  const hasVisibleContent = Boolean(
    currentMessage && (
      currentMessage.content ||
      toolExecutionCount > 0 ||
      agentThinking
    )
  );
  const showThinkingDots = (isWaitingForResponse || isStreaming) && !currentMessage && !hasVisibleContent;

  // Clear old analytics conversation history from localStorage on first mount
  useEffect(() => {
    const ANALYTICS_KEYWORDS = ['call volume', 'escalation', 'sentiment', 'channel mix',
      'call reasons', 'agent performance', 'silence', 'talk dynamics', 'empathy', 'resolution'];
    const store = useChatStore.getState();
    const hasAnalyticsConversations = store.conversations.some(c =>
      ANALYTICS_KEYWORDS.some(kw => c.title.toLowerCase().includes(kw))
    );
    if (hasAnalyticsConversations) {
      useChatStore.setState({ conversations: [], currentConversationId: null });
    }
  }, []);

  // Initialize WebSocket connection
  useEffect(() => {
    if (!isLoggedIn) {
      websocketService.disconnect();
      return;
    }

    websocketService.connect();

    return () => {
      websocketService.disconnect();
    };
  }, [isLoggedIn]);

  // Auto-scroll to bottom on new messages, tool executions, and thinking dots
  useEffect(() => {
    if (shouldAutoScroll.current && chatContainerRef.current) {
      chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
    }
  }, [currentConversation?.messages, currentMessage?.content, toolExecutionCount, showThinkingDots]);

  const handleScroll = useCallback(() => {
    if (chatContainerRef.current) {
      const { scrollTop, scrollHeight, clientHeight } = chatContainerRef.current;
      const isAtBottom = scrollHeight - scrollTop - clientHeight < 100;
      shouldAutoScroll.current = isAtBottom;
    }
  }, []);

  // Hide sidebar during active chat on mobile
  useEffect(() => {
    if (isStreaming && window.innerWidth < 768) {
      useChatStore.setState({ isSidebarOpen: false });
    }
  }, [isStreaming]);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmedEmpId = empId.trim();
    if (!trimmedEmpId) {
      setAuthError('Username is required');
      return;
    }
    if (!password) {
      setAuthError('Password is required');
      return;
    }
    try {
      const { access_token, role } = await loginWithCredentials(trimmedEmpId, password);
      setUser({ emp_id: trimmedEmpId, token: access_token, role: role || '' });
      setEmpId('');
      setPassword('');
      setAuthError('');
    } catch (err) {
      setAuthError(err instanceof Error ? err.message : 'Login failed');
    }
  };

  if (!isLoggedIn) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 flex items-center justify-center p-6">
        <div className="w-full max-w-md bg-white/95 backdrop-blur rounded-2xl shadow-2xl border border-white/20 p-8">
          <div className="text-center space-y-4">
            <div className="inline-flex items-center justify-center w-20 h-20 rounded-2xl bg-gradient-to-br from-blue-600 to-purple-600 shadow-lg">
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="w-10 h-10">
                <path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><line x1="3" y1="6" x2="21" y2="6"/><path d="M16 10a4 4 0 0 1-8 0"/>
              </svg>
            </div>
            <div>
              <h1 className="text-2xl font-bold text-gray-900">ShopAssist AI</h1>
              <p className="text-sm text-gray-600">Sign in to process refund requests</p>
            </div>
          </div>

          <form onSubmit={handleLogin} className="mt-8 space-y-4">
            <div className="space-y-2">
              <label className="text-xs font-semibold text-gray-700">Username</label>
              <input
                type="text"
                value={empId}
                onChange={(e) => setEmpId(e.target.value)}
                className="w-full px-4 py-3 rounded-xl border border-gray-200 focus:border-blue-500 focus:ring-2 focus:ring-blue-200 outline-none transition-all"
                placeholder="Enter your username"
                autoComplete="username"
              />
            </div>
            <div className="space-y-2">
              <label className="text-xs font-semibold text-gray-700">Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full px-4 py-3 rounded-xl border border-gray-200 focus:border-blue-500 focus:ring-2 focus:ring-blue-200 outline-none transition-all"
                placeholder="Enter your password"
                autoComplete="current-password"
              />
            </div>
            {authError && (
              <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                {authError}
              </div>
            )}
            <button
              type="submit"
              className="w-full py-3 rounded-xl bg-gradient-to-r from-blue-600 to-purple-600 text-white font-semibold shadow-md hover:shadow-lg transition-all"
            >
              Sign in
            </button>
          </form>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen flex overflow-hidden bg-gray-50 dark:bg-gray-900">
      {/* Sidebar */}
      <AnimatePresence mode="wait">
        {isSidebarOpen && <Sidebar activeTab={activeTab} />}
      </AnimatePresence>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col relative">
        {/* Header */}
        <header className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            {!isSidebarOpen && (
              <button
                type="button"
                onClick={toggleSidebar}
                aria-label="Toggle sidebar"
                className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors"
              >
                <Menu className="w-5 h-5 text-gray-600 dark:text-gray-300" />
              </button>
            )}
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-600 to-purple-600 flex items-center justify-center flex-shrink-0">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4">
                  <path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><line x1="3" y1="6" x2="21" y2="6"/><path d="M16 10a4 4 0 0 1-8 0"/>
                </svg>
              </div>
            <div className="space-y-0.5">
              <h1 className="font-semibold text-gray-900 dark:text-gray-100">
                {activeTab === 'admin' ? 'Admin Dashboard' : (currentConversation?.title || 'ShopAssist AI')}
              </h1>
              <p className={`text-xs ${isConnected ? 'text-gray-500 dark:text-gray-400' : 'text-amber-500 dark:text-amber-400'}`}>
                {isConnected ? 'Ready to help' : 'Reconnecting…'}
              </p>
            </div>
          </div>

          {/* Tab switcher — Admin tab only visible to admin users */}
          {user?.role === 'admin' && (
          <div className="flex items-center gap-1 bg-gray-100 dark:bg-gray-700 rounded-lg p-1">
              <button
                type="button"
                onClick={() => setActiveTab('chat')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                  activeTab === 'chat'
                    ? 'bg-white dark:bg-gray-600 text-gray-900 dark:text-gray-100 shadow-sm'
                    : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200'
                }`}
              >
                <MessageSquare className="w-4 h-4" />
                Chat
              </button>
              <button
                type="button"
                onClick={() => setActiveTab('admin')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                  activeTab === 'admin'
                    ? 'bg-white dark:bg-gray-600 text-gray-900 dark:text-gray-100 shadow-sm'
                    : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200'
                }`}
              >
                <LayoutDashboard className="w-4 h-4" />
                Admin
              </button>
            </div>
          )}
        </header>

        {/* Admin Dashboard — only render for admin role */}
        {activeTab === 'admin' && user?.role === 'admin' ? (
          <AdminDashboard />
        ) : (
          <>
            {/* Chat Messages Area */}
            <div
              ref={chatContainerRef}
              onScroll={handleScroll}
              role="log"
              aria-label="Chat messages"
              aria-live="polite"
              className="flex-1 overflow-y-auto p-6"
            >
              {!hasMessages && !currentMessage ? (
                <WelcomeScreen />
              ) : (
                <div className="max-w-4xl mx-auto space-y-6">
                  {currentConversation?.messages.map((message) => (
                    <ChatMessage key={message.id} message={message} />
                  ))}

                  {showThinkingDots && (
                    <div className="flex gap-4 justify-start mb-6">
                      <div className="flex-shrink-0 w-8 h-8 rounded-full bg-white border border-gray-200 flex items-center justify-center p-1">
                        <div className="w-full h-full rounded-full bg-gradient-to-br from-blue-600 to-purple-600 flex items-center justify-center">
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4">
                          <path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><line x1="3" y1="6" x2="21" y2="6"/><path d="M16 10a4 4 0 0 1-8 0"/>
                        </svg>
                      </div>
                      </div>
                      <div className="flex-1 max-w-3xl">
                        <ThinkingDots agentThinking={agentThinking} />
                      </div>
                    </div>
                  )}

                  {currentMessage && (hasVisibleContent || isStreaming) && (
                    <ChatMessage message={currentMessage} isStreaming={isStreaming} />
                  )}
                </div>
              )}
            </div>

            {/* Input Area */}
            <ChatInput />
          </>
        )}
      </div>
    </div>
  );
}

export default App;
