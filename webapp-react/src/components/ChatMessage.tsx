import React, { memo, useMemo, useState, useCallback, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { User, Clock, ThumbsUp, ThumbsDown, Copy, Check } from 'lucide-react';
import { Message, ToolExecution, UsageStats } from '../types/websocket.types';
// logo removed
import { ToolExecutionCard } from './ToolExecutionCard';
import { ThinkingDots } from './ThinkingDots';
import { useChatStore } from '../store/chatStore';

const remarkPlugins = [remarkGfm];

const CodeBlock: React.FC<{ className?: string; children?: React.ReactNode }> = ({ className, children }) => {
  const [copied, setCopied] = useState(false);
  const match = /language-(\w+)/.exec(className || '');
  const language = match ? match[1] : '';
  const code = String(children).replace(/\n$/, '');

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [code]);

  if (!className) {
    return <code className="bg-gray-100 text-gray-800 px-1.5 py-0.5 rounded text-sm font-mono">{children}</code>;
  }

  return (
    <div className="relative group my-3">
      <div className="flex items-center justify-between bg-gray-800 text-gray-300 px-4 py-1.5 rounded-t-lg text-xs">
        <span>{language || 'code'}</span>
        <button
          type="button"
          onClick={handleCopy}
          className="flex items-center gap-1 hover:text-white transition-colors"
          aria-label="Copy code"
        >
          {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
          <span>{copied ? 'Copied' : 'Copy'}</span>
        </button>
      </div>
      <pre className="bg-gray-900 text-gray-100 p-4 rounded-b-lg overflow-x-auto text-sm">
        <code>{code}</code>
      </pre>
    </div>
  );
};

const markdownComponents = { code: CodeBlock as any };

interface ChatMessageProps {
  message: Message;
  isStreaming?: boolean;
}

export const ChatMessage: React.FC<ChatMessageProps> = memo(({ message, isStreaming }) => {
  const isUser = message.role === 'user';

  const sToolExecMap     = useChatStore((s) => isStreaming ? s.currentToolExecutions : null);
  const sAgentThinking   = useChatStore((s) => isStreaming ? s.agentThinking : null);
  const sIsProcessing    = useChatStore((s) => isStreaming ? s.isProcessing : false);
  const sFirstByteTime      = useChatStore((s) => isStreaming ? s.firstByteTime : null);
  const sRequestStartTime   = useChatStore((s) => isStreaming ? s.requestStartTime : null);
  const sUsageStats         = useChatStore((s) => isStreaming ? s.currentUsageStats : null);

  const [liveElapsedMs, setLiveElapsedMs] = useState<number | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!isStreaming || !sRequestStartTime) {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      setLiveElapsedMs(null);
      return;
    }
    setLiveElapsedMs(Date.now() - sRequestStartTime);
    timerRef.current = setInterval(() => {
      setLiveElapsedMs(Date.now() - sRequestStartTime);
    }, 100);
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [isStreaming, sRequestStartTime]);

  const agentThinking = sAgentThinking;
  const isProcessing  = sIsProcessing;

  const toolExecutionsArray: ToolExecution[] = useMemo(() => {
    if (isStreaming && sToolExecMap) {
      return Array.from(sToolExecMap.values());
    }
    return message.tool_executions || [];
  }, [isStreaming, sToolExecMap, message.tool_executions]);

  const ttfbMs = isStreaming ? (sFirstByteTime ?? liveElapsedMs) : message.response_time;
  const totalMs = isStreaming ? liveElapsedMs : message.total_response_time;
  const ttfbSec = ttfbMs !== null && ttfbMs !== undefined ? (ttfbMs / 1000).toFixed(1) : null;
  const totalSec = totalMs !== null && totalMs !== undefined ? (totalMs / 1000).toFixed(1) : null;
  const usageStats: UsageStats | null | undefined = isStreaming ? sUsageStats : message.usage_stats;

  const statusMessage = isStreaming ? agentThinking : (message.agent_thinking || null);

  const setMessageFeedback = useChatStore((s) => s.setMessageFeedback);

  const showToolExecutions = toolExecutionsArray.length > 0;

  const displayContent = (() => {
    if (!message.content) return '';
    const content = message.content;

    const preToolText = statusMessage || message.agent_thinking;
    if (!preToolText) return content;

    const status = preToolText.trim();
    if (!status) return content;

    const trimmedContent = content.trimStart();

    if (statusMessage && status.startsWith(trimmedContent)) {
      return '';
    }

    if (trimmedContent.startsWith(status)) {
      const remaining = trimmedContent.slice(status.length);
      if (remaining.length === 0) return '';
      if (/^[\s.,!?;\n]/.test(remaining)) {
        return remaining.trimStart();
      }
      return remaining;
    }
    return content;
  })();

  return (
    <div className={`flex gap-4 ${isUser ? 'justify-end' : 'justify-start'} mb-6 animate-fadeIn`}>
      {!isUser && (
        <div className="flex-shrink-0 w-8 h-8 rounded-full bg-gradient-to-br from-blue-600 to-purple-600 flex items-center justify-center">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4">
            <path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><line x1="3" y1="6" x2="21" y2="6"/><path d="M16 10a4 4 0 0 1-8 0"/>
          </svg>
        </div>
      )}

      <div className={`flex-1 max-w-3xl ${isUser ? 'flex justify-end' : ''}`}>
        <div
          className={`${
            isUser
              ? 'bg-blue-600 text-white rounded-2xl rounded-br-md px-4 py-3 inline-block'
              : 'space-y-4 w-full'
          }`}
        >
          {isUser ? (
            <p className="text-sm whitespace-pre-wrap">{message.content}</p>
          ) : (
            <>
              {isStreaming && (isProcessing || statusMessage === '...') && !showToolExecutions && !message.content && (
                <ThinkingDots />
              )}

              {statusMessage && statusMessage !== '...' && (
                <div className="text-sm text-gray-700 dark:text-gray-300 mb-3 animate-fadeIn prose prose-sm max-w-none dark:prose-invert">
                  <ReactMarkdown remarkPlugins={remarkPlugins} components={markdownComponents}>
                    {statusMessage}
                  </ReactMarkdown>
                </div>
              )}

              {showToolExecutions && message.agent_thinking && !isStreaming && !statusMessage && (
                <div className="text-sm text-gray-700 dark:text-gray-300 mb-3 prose prose-sm max-w-none dark:prose-invert">
                  <ReactMarkdown remarkPlugins={remarkPlugins} components={markdownComponents}>
                    {message.agent_thinking}
                  </ReactMarkdown>
                </div>
              )}

              {showToolExecutions && (
                <>
                  {toolExecutionsArray.map((execution) => (
                    <ToolExecutionCard
                      key={execution.tool_key}
                      toolName={execution.tool_name}
                      toolDescription={execution.tool_description}
                      steps={execution.steps}
                      isExecuting={execution.isExecuting}
                      startTime={execution.startTime}
                    />
                  ))}
                </>
              )}


              {displayContent ? (
                <div className="prose prose-sm max-w-none dark:prose-invert">
                  <ReactMarkdown remarkPlugins={remarkPlugins} components={markdownComponents}>
                    {displayContent}
                  </ReactMarkdown>
                  {isStreaming && (
                    <span className="inline-flex items-center ml-1">
                      <span className="w-2 h-4 bg-blue-500 animate-pulse" />
                    </span>
                  )}
                </div>
              ) : (
                isStreaming && !isProcessing && !showToolExecutions && !statusMessage && message.content && (
                  <div className="prose prose-sm max-w-none dark:prose-invert">
                    <span className="inline-flex items-center">
                      <span className="w-2 h-4 bg-blue-500 animate-pulse" />
                    </span>
                  </div>
                )
              )}

              <div className="flex items-center gap-3 mt-2">
                <p className="text-xs text-gray-400">
                  {new Date(message.timestamp).toLocaleTimeString()}
                </p>
                {(ttfbSec || totalSec) && (
                  <div className="flex items-center gap-1 text-xs text-gray-400">
                    <Clock className="w-3 h-3" />
                    {isStreaming ? (
                      <span>{totalSec ?? ttfbSec}s</span>
                    ) : (
                      ttfbSec && totalSec && ttfbSec !== totalSec ? (
                        <span title={`First byte: ${ttfbSec}s · Total: ${totalSec}s`}>{ttfbSec}s / {totalSec}s</span>
                      ) : (
                        <span>{totalSec ?? ttfbSec}s</span>
                      )
                    )}
                  </div>
                )}
                {usageStats && (usageStats.cache_read > 0 || usageStats.cache_creation > 0) && (
                  <div
                    className="flex items-center gap-1 text-xs text-emerald-500"
                    title={`Cache: ${usageStats.cache_read.toLocaleString()} read · ${usageStats.cache_creation.toLocaleString()} written`}
                  >
                    <span>⚡</span>
                    <span>cached</span>
                  </div>
                )}
                {!isStreaming && !isUser && (
                  <div className="flex items-center gap-1 ml-auto">
                    <button
                      type="button"
                      onClick={() => setMessageFeedback(message.id, message.feedback === 'positive' ? undefined : 'positive')}
                      className={`p-1 rounded transition-colors ${message.feedback === 'positive' ? 'text-green-500' : 'text-gray-300 hover:text-gray-500'}`}
                      aria-label="Helpful response"
                    >
                      <ThumbsUp className="w-3.5 h-3.5" />
                    </button>
                    <button
                      type="button"
                      onClick={() => setMessageFeedback(message.id, message.feedback === 'negative' ? undefined : 'negative')}
                      className={`p-1 rounded transition-colors ${message.feedback === 'negative' ? 'text-red-500' : 'text-gray-300 hover:text-gray-500'}`}
                      aria-label="Unhelpful response"
                    >
                      <ThumbsDown className="w-3.5 h-3.5" />
                    </button>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>

      {isUser && (
        <div className="flex-shrink-0 w-8 h-8 rounded-full bg-gradient-to-br from-green-500 to-teal-600 flex items-center justify-center">
          <User className="w-5 h-5 text-white" />
        </div>
      )}
    </div>
  );
});

ChatMessage.displayName = 'ChatMessage';
