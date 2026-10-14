import React from 'react';
import { motion } from 'framer-motion';
import { ShoppingBag, RefreshCw, AlertCircle, CheckCircle } from 'lucide-react';
import { useChatStore } from '../store/chatStore';
import { websocketService } from '../services/websocket';
// logo removed

const examplePrompts = [
  {
    icon: CheckCircle,
    title: 'Standard Refund',
    prompt: 'I want to return my Sony headphones, order ORD-2026-10001. They stopped working after 2 weeks.',
    color: 'from-blue-500 to-cyan-500',
  },
  {
    icon: AlertCircle,
    title: 'Digital Product',
    prompt: 'I need a refund for my Adobe Creative Cloud subscription, order ORD-2026-10006.',
    color: 'from-orange-500 to-red-500',
  },
  {
    icon: RefreshCw,
    title: 'Wrong Item',
    prompt: 'I received the wrong product for order ORD-2026-10010. I ordered a docking station but got something else.',
    color: 'from-purple-500 to-pink-500',
  },
  {
    icon: ShoppingBag,
    title: 'Cancelled Order',
    prompt: 'I cancelled my order ORD-2026-10008 before it shipped. Please process my refund.',
    color: 'from-green-500 to-teal-500',
  },
];

export const WelcomeScreen: React.FC = () => {
  const { currentConversationId, conversations, addUserMessage, createConversation, isAuthenticated } = useChatStore();

  const currentConversation = conversations.find((c) => c.id === currentConversationId);

  const handleExampleClick = (prompt: string) => {
    if (!isAuthenticated) return;

    let conversation = currentConversation;
    if (!conversation) {
      const threadId = `thread-${Date.now()}`;
      createConversation(threadId);
      const state = useChatStore.getState();
      conversation = state.conversations.find((c) => c.id === state.currentConversationId)!;
    }

    addUserMessage(prompt);

    websocketService.sendMessage({
      question: prompt,
      language: 'English',
      thread_id: conversation.thread_id,
      namespace: 'default',
      graph_initialization: false,
    });
  };

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.5 }}
      className="flex-1 flex items-center justify-center p-8"
    >
      <div className="max-w-4xl w-full space-y-8">
        <div className="text-center space-y-4">
          <motion.div
            initial={{ scale: 0.8, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ delay: 0.2 }}
            className="inline-flex items-center justify-center w-24 h-24 bg-gradient-to-br from-blue-600 to-purple-600 rounded-2xl shadow-lg"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="w-12 h-12">
              <path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><line x1="3" y1="6" x2="21" y2="6"/><path d="M16 10a4 4 0 0 1-8 0"/>
            </svg>
          </motion.div>

          <motion.div
            initial={{ y: 20, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ delay: 0.3 }}
          >
            <h1 className="text-4xl font-bold text-gray-900 mb-2">
              Welcome to ShopAssist AI
            </h1>
            <p className="text-lg text-gray-600">
              AI-powered refund processing agent — strict policy enforcement
            </p>
          </motion.div>
        </div>

        <motion.div
          initial={{ y: 20, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ delay: 0.4 }}
          className="grid grid-cols-1 md:grid-cols-3 gap-4"
        >
          <div className="flex items-start gap-3 p-4 bg-blue-50 rounded-xl">
            <CheckCircle className="w-5 h-5 text-blue-600 mt-0.5" />
            <div>
              <h3 className="font-semibold text-gray-900 text-sm">Policy Enforcement</h3>
              <p className="text-xs text-gray-600 mt-1">
                Return windows, digital product rules, and flagged account handling
              </p>
            </div>
          </div>

          <div className="flex items-start gap-3 p-4 bg-purple-50 rounded-xl">
            <ShoppingBag className="w-5 h-5 text-purple-600 mt-0.5" />
            <div>
              <h3 className="font-semibold text-gray-900 text-sm">CRM Lookup</h3>
              <p className="text-xs text-gray-600 mt-1">
                Customer profiles, order history, and refund records
              </p>
            </div>
          </div>

          <div className="flex items-start gap-3 p-4 bg-green-50 rounded-xl">
            <AlertCircle className="w-5 h-5 text-green-600 mt-0.5" />
            <div>
              <h3 className="font-semibold text-gray-900 text-sm">Full Audit Trail</h3>
              <p className="text-xs text-gray-600 mt-1">
                Every decision recorded with complete agent reasoning
              </p>
            </div>
          </div>
        </motion.div>

        <div className="space-y-3">
          <motion.h2
            initial={{ y: 20, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ delay: 0.5 }}
            className="text-sm font-semibold text-gray-700"
          >
            Try asking me...
          </motion.h2>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {examplePrompts.map((example, index) => {
              const Icon = example.icon;
              return (
                <motion.button
                  key={index}
                  initial={{ y: 20, opacity: 0 }}
                  animate={{ y: 0, opacity: 1 }}
                  transition={{ delay: 0.6 + index * 0.1 }}
                  onClick={() => handleExampleClick(example.prompt)}
                  disabled={!isAuthenticated}
                  className="group text-left p-4 bg-white border-2 border-gray-200 hover:border-blue-500 rounded-xl transition-all hover:shadow-md disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <div className="flex items-start gap-3">
                    <div
                      className={`w-10 h-10 rounded-lg bg-gradient-to-br ${example.color} flex items-center justify-center flex-shrink-0`}
                    >
                      <Icon className="w-5 h-5 text-white" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <h3 className="font-medium text-gray-900 mb-1 group-hover:text-blue-600 transition-colors">
                        {example.title}
                      </h3>
                      <p className="text-sm text-gray-600 line-clamp-2">
                        {example.prompt}
                      </p>
                    </div>
                  </div>
                </motion.button>
              );
            })}
          </div>
        </div>

        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 1 }}
          className="text-center text-xs text-gray-500"
        >
          Click on an example or type your own question below
        </motion.p>
      </div>
    </motion.div>
  );
};
