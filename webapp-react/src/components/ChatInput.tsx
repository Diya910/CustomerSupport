import React, { useState, useRef, useEffect, memo, useMemo, useCallback } from 'react';
import { Send, Square, Volume2, VolumeX, Mic, MicOff } from 'lucide-react';
import { useChatStore } from '../store/chatStore';
import { websocketService } from '../services/websocket';
import { streamingTts } from '../services/streamingTts';
import { ChatRequest } from '../types/websocket.types';

const SpeechRecognitionAPI =
  (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;

export const ChatInput: React.FC = memo(() => {
  const [input, setInput] = useState('');
  const [isListening, setIsListening] = useState(false);
  const [micSupported] = useState(() => !!SpeechRecognitionAPI);
  const recognitionRef = useRef<any>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const prevStreamingRef = useRef(false);
  const isStreaming = useChatStore((s) => s.isStreaming);
  const isConnected = useChatStore((s) => s.isConnected);
  const currentConversationId = useChatStore((s) => s.currentConversationId);
  const conversations = useChatStore((s) => s.conversations);
  const addUserMessage = useChatStore((s) => s.addUserMessage);
  const createConversation = useChatStore((s) => s.createConversation);
  const isAuthenticated = useChatStore((s) => s.isAuthenticated);
  const voiceEnabled = useChatStore((s) => s.voiceEnabled);
  const toggleVoice = useChatStore((s) => s.toggleVoice);

  const currentConversation = useMemo(
    () => conversations.find((c) => c.id === currentConversationId),
    [conversations, currentConversationId]
  );

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`;
    }
  }, [input]);

  useEffect(() => {
    const wasStreaming = prevStreamingRef.current;
    prevStreamingRef.current = isStreaming;

    // Stream just started: begin watching only if voice is on.
    if (!wasStreaming && isStreaming && voiceEnabled) {
      streamingTts.start();
    }
    // Stream just ended (natural completion OR user pressed stop): the watcher
    // stops polling on its own, but we still finalize so in-flight fetches and
    // queued audio for THIS turn are flushed/cleaned regardless of voice state.
    // start() flushes the remaining text before tearing down.
  }, [isStreaming, voiceEnabled]);

  useEffect(() => {
    // Toggling voice off mid-turn must immediately silence playback and abort
    // pending fetches. Toggling on mid-stream starts watching from the current
    // point (it will speak the remainder, not what already streamed).
    if (!voiceEnabled) {
      streamingTts.stop();
    } else if (isStreaming) {
      streamingTts.start();
    }
  }, [voiceEnabled]);

  // Hard stop on unmount or when the active conversation changes — prevents
  // audio from one conversation bleeding into another, and aborts fetches.
  // Also stops any active recognition.
  useEffect(() => {
    return () => {
      streamingTts.stop();
      if (recognitionRef.current) {
        recognitionRef.current.abort();
        recognitionRef.current = null;
      }
    };
  }, [currentConversationId]);

  // If streaming starts while mic is active, stop recording immediately
  // (agent is responding — mic input no longer makes sense).
  useEffect(() => {
    if (isStreaming && recognitionRef.current) {
      recognitionRef.current.abort();
      recognitionRef.current = null;
      setIsListening(false);
    }
  }, [isStreaming]);

  const stopListening = useCallback(() => {
    if (recognitionRef.current) {
      recognitionRef.current.stop();
      recognitionRef.current = null;
    }
    setIsListening(false);
  }, []);

  const startListening = useCallback(() => {
    if (!SpeechRecognitionAPI) return;
    // Prevent double-start: if already listening, ignore.
    if (recognitionRef.current) return;
    // Don't start if agent is streaming.
    if (useChatStore.getState().isStreaming) return;

    const recognition = new SpeechRecognitionAPI();
    recognition.lang = 'en-US';
    recognition.interimResults = true;
    recognition.continuous = false;
    recognition.maxAlternatives = 1;

    let finalTranscript = '';
    let aborted = false;

    recognition.onresult = (event: any) => {
      if (aborted) return;
      let interim = '';
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const transcript = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          finalTranscript += transcript;
        } else {
          interim = transcript;
        }
      }
      setInput(finalTranscript || interim);
    };

    recognition.onend = () => {
      if (aborted) return;
      setIsListening(false);
      recognitionRef.current = null;
      if (finalTranscript.trim()) {
        setInput(finalTranscript.trim());
      }
    };

    recognition.onerror = (event: any) => {
      if (event.error === 'aborted') {
        aborted = true;
      } else {
        console.warn('Speech recognition error:', event.error);
      }
      setIsListening(false);
      recognitionRef.current = null;
    };

    recognition.onstart = () => {
      setIsListening(true);
    };

    recognitionRef.current = recognition;
    recognition.start();
  }, []);

  const toggleMic = useCallback(() => {
    if (recognitionRef.current) {
      stopListening();
    } else {
      startListening();
    }
  }, [startListening, stopListening]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    if (!input.trim() || isStreaming || !isAuthenticated || !isConnected) return;

    // Stop mic if active — prevents onresult from overwriting cleared input after send.
    if (recognitionRef.current) {
      recognitionRef.current.abort();
      recognitionRef.current = null;
      setIsListening(false);
    }

    let conversation = currentConversation;
    if (!conversation) {
      const threadId = `thread-${Date.now()}`;
      createConversation(threadId);
      const state = useChatStore.getState();
      conversation = state.conversations.find((c) => c.id === state.currentConversationId)!;
    }

    addUserMessage(input);

    const request: ChatRequest = {
      question: input,
      language: 'English',
      thread_id: conversation.thread_id,
      namespace: 'default',
      graph_initialization: false,
    };

    websocketService.sendMessage(request);

    setInput('');

    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  return (
    <div className="border-t border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4">
      <form onSubmit={handleSubmit} className="max-w-4xl mx-auto">
        <div className="flex items-end bg-gray-50 dark:bg-gray-700 rounded-2xl border border-gray-300 dark:border-gray-600 focus-within:border-blue-500 focus-within:ring-2 focus-within:ring-blue-200 dark:focus-within:ring-blue-800 transition-all">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              if (recognitionRef.current) {
                recognitionRef.current.abort();
                recognitionRef.current = null;
                setIsListening(false);
              }
            }}
            onKeyDown={handleKeyDown}
            placeholder={isConnected ? 'Describe your refund request or provide an order number...' : 'Reconnecting to server…'}
            disabled={isStreaming || !isAuthenticated || !isConnected}
            rows={1}
            aria-label="Message input"
            className="flex-1 px-4 py-3 bg-transparent border-none outline-none resize-none max-h-40 disabled:opacity-50 disabled:cursor-not-allowed dark:text-gray-100 dark:placeholder-gray-400"
          />
          <div className="flex items-center m-2 gap-1">
            <button
              type="button"
              onClick={toggleVoice}
              aria-label={voiceEnabled ? 'Disable voice' : 'Enable voice'}
              title={voiceEnabled ? 'Voice on — click to mute' : 'Voice off — click to enable'}
              className={`p-2 rounded-lg transition-colors ${
                voiceEnabled
                  ? 'bg-purple-100 text-purple-600 dark:bg-purple-900/30 dark:text-purple-400'
                  : 'text-gray-400 hover:text-gray-600 dark:hover:text-gray-300'
              }`}
            >
              {voiceEnabled ? <Volume2 className="w-5 h-5" /> : <VolumeX className="w-5 h-5" />}
            </button>
            {micSupported && (
              <button
                type="button"
                onClick={toggleMic}
                disabled={isStreaming || !isAuthenticated || !isConnected}
                aria-label={isListening ? 'Stop listening' : 'Start voice input'}
                title={isListening ? 'Listening... click to stop' : 'Click to speak'}
                className={`p-2 rounded-lg transition-colors ${
                  isListening
                    ? 'bg-red-100 text-red-600 dark:bg-red-900/30 dark:text-red-400 animate-pulse'
                    : 'text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 disabled:opacity-50'
                }`}
              >
                {isListening ? <Mic className="w-5 h-5" /> : <MicOff className="w-5 h-5" />}
              </button>
            )}
            {isStreaming ? (
              <button
                type="button"
                onClick={() => {
                  streamingTts.stop();
                  websocketService.sendCancel();
                }}
                aria-label="Stop generation"
                className="p-2 bg-red-500 hover:bg-red-600 text-white rounded-lg transition-colors"
              >
                <Square className="w-5 h-5" />
              </button>
            ) : (
              <button
                type="submit"
                disabled={!input.trim() || !isAuthenticated || !isConnected}
                aria-label="Send message"
                className="p-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed text-white rounded-lg transition-colors"
              >
                <Send className="w-5 h-5" />
              </button>
            )}
          </div>
        </div>
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-2 text-center">
          Press Enter to send, Shift+Enter for new line
        </p>
      </form>
    </div>
  );
});

ChatInput.displayName = 'ChatInput';
