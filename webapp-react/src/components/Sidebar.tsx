import React, { useState, memo, useCallback, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { websocketService } from '../services/websocket';
import {
  MessageSquare,
  Plus,
  LogOut,
  User,
  X,
  Trash2,
  Moon,
  Sun,
  Upload,
  FileText,
} from 'lucide-react';
import { useChatStore } from '../store/chatStore';
import { formatDistanceToNow } from 'date-fns';

interface SidebarProps {
  activeTab?: 'chat' | 'admin';
}

export const Sidebar: React.FC<SidebarProps> = memo(({ activeTab = 'chat' }) => {
  const isSidebarOpen = useChatStore((s) => s.isSidebarOpen);
  const toggleSidebar = useChatStore((s) => s.toggleSidebar);
  const conversations = useChatStore((s) => s.conversations);
  const currentConversationId = useChatStore((s) => s.currentConversationId);
  const createConversation = useChatStore((s) => s.createConversation);
  const setCurrentConversation = useChatStore((s) => s.setCurrentConversation);
  const deleteConversation = useChatStore((s) => s.deleteConversation);
  const user = useChatStore((s) => s.user);
  const logout = useChatStore((s) => s.logout);
  const isDarkMode = useChatStore((s) => s.isDarkMode);
  const toggleDarkMode = useChatStore((s) => s.toggleDarkMode);

  const isStreaming = useChatStore((s) => s.isStreaming);

  const handleNewChat = () => {
    if (isStreaming) websocketService.sendCancel();
    const threadId = `thread-${Date.now()}`;
    createConversation(threadId);
  };

  const handleSwitchConversation = useCallback((id: string) => {
    if (isStreaming) websocketService.sendCancel();
    setCurrentConversation(id);
  }, [isStreaming, setCurrentConversation]);

  const handleDeleteConversation = (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    if (confirm('Delete this conversation?')) {
      deleteConversation(id);
    }
  };

  // ── Admin: file upload state ──
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadMsg, setUploadMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [documents, setDocuments] = useState<{ filename: string; s3_key: string; size_bytes: number; last_modified: string }[]>([]);
  const [loadingDocs, setLoadingDocs] = useState(false);
  const basePath = import.meta.env.BASE_URL.replace(/\/$/, '');

  const fetchDocuments = useCallback(async () => {
    setLoadingDocs(true);
    try {
      const res = await fetch(`${basePath}/ingestion/documents`);
      if (!res.ok) return;
      const data = await res.json();
      setDocuments(data.documents ?? []);
    } catch {
      // non-critical
    } finally {
      setLoadingDocs(false);
    }
  }, [basePath]);

  const handleUpload = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      setUploadMsg({ type: 'error', text: 'Only PDF files are supported.' });
      return;
    }
    if (file.size === 0) {
      setUploadMsg({ type: 'error', text: 'File is empty.' });
      return;
    }
    if (file.size > 20 * 1024 * 1024) {
      setUploadMsg({ type: 'error', text: 'File exceeds 20MB limit.' });
      return;
    }
    setUploading(true);
    setUploadMsg(null);
    try {
      const urlRes = await fetch(`${basePath}/presigned-url?filename=${encodeURIComponent(file.name)}`, { method: 'POST' });
      const urlData = await urlRes.json();
      if (!urlRes.ok) throw new Error(urlData.detail || 'Failed to get upload URL');

      const putRes = await fetch(urlData.upload_url, {
        method: 'PUT',
        body: file,
        headers: { 'Content-Type': 'application/pdf' },
      });
      if (!putRes.ok) throw new Error(`S3 upload failed (${putRes.status})`);

      const ingestRes = await fetch(`${basePath}/ingestion/ingest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          request_id: `upload_${file.name}_${Date.now()}`,
          pre_signed_url: urlData.download_url,
          file_name: file.name,
          file_type: 'pdf',
          index_name: null,
          namespace_name: 'policy_documents',
          metadata: { source: file.name, s3_key: urlData.s3_key, document_type: 'uploaded_policy' },
        }),
      });
      const ingestData = await ingestRes.json();
      if (!ingestRes.ok) throw new Error(ingestData.detail || 'Ingestion failed');

      const chunks = ingestData.chunk_count ?? 0;
      setUploadMsg({ type: 'success', text: `Ingested ${chunks} chunks from "${file.name}"` });
      fetchDocuments();
    } catch (err) {
      setUploadMsg({ type: 'error', text: err instanceof Error ? err.message : 'Upload failed' });
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  }, [basePath, fetchDocuments]);

  // Fetch docs on mount when in admin mode
  React.useEffect(() => {
    if (activeTab === 'admin') fetchDocuments();
  }, [activeTab, fetchDocuments]);

  if (!isSidebarOpen) return null;

  return (
    <>
      {/* Mobile Overlay */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 bg-black/30 z-40 md:hidden"
        onClick={toggleSidebar}
      />

      {/* Sidebar */}
      <motion.aside
        initial={{ x: '-100%' }}
        animate={{ x: 0 }}
        exit={{ x: '-100%' }}
        transition={{ type: 'spring', damping: 25, stiffness: 200 }}
        className="fixed left-0 top-0 h-screen w-72 bg-gray-900 text-white z-50 flex flex-col shadow-xl md:static"
      >
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-gray-800">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center">
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4">
                <path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><line x1="3" y1="6" x2="21" y2="6"/><path d="M16 10a4 4 0 0 1-8 0"/>
              </svg>
            </div>
            <span className="font-semibold">ShopAssist AI</span>
          </div>
          <button
            type="button"
            onClick={toggleSidebar}
            className="p-1 hover:bg-gray-800 rounded md:hidden"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {activeTab === 'chat' ? (
          <>
            {/* New Chat Button */}
            <div className="p-3 border-b border-gray-800">
              <button
                type="button"
                onClick={handleNewChat}
                aria-label="Start new conversation"
                className="w-full flex items-center gap-2 px-3 py-2.5 bg-white/10 hover:bg-white/20 rounded-lg transition-colors"
              >
                <Plus className="w-5 h-5" />
                <span className="font-medium">New chat</span>
              </button>
            </div>

            {/* Conversations List */}
            <div className="flex-1 overflow-y-auto p-3 space-y-2" role="list" aria-label="Conversation list">
              <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 px-2">
                Your conversations
              </h3>
              <AnimatePresence mode="popLayout">
                {conversations.length === 0 ? (
                  <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    className="text-center text-gray-500 mt-8 px-4"
                  >
                    <MessageSquare className="w-12 h-12 mx-auto mb-2 opacity-30" />
                    <p className="text-sm">No conversations yet</p>
                    <p className="text-xs mt-1">Start a new chat to begin</p>
                  </motion.div>
                ) : (
                  conversations.map((conv) => (
                    <motion.button
                      key={conv.id}
                      initial={{ opacity: 0, x: -20 }}
                      animate={{ opacity: 1, x: 0 }}
                      exit={{ opacity: 0, x: -20 }}
                      onClick={() => handleSwitchConversation(conv.id)}
                      className={`w-full text-left px-3 py-2.5 rounded-lg transition-all group relative ${
                        currentConversationId === conv.id
                          ? 'bg-white/20'
                          : 'hover:bg-white/10'
                      }`}
                    >
                      <div className="flex items-start gap-2">
                        <MessageSquare className="w-4 h-4 mt-0.5 flex-shrink-0" />
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium truncate">{conv.title}</p>
                          <p className="text-xs text-gray-400 mt-0.5">
                            {formatDistanceToNow(conv.updated_at, { addSuffix: true })}
                          </p>
                        </div>
                        <button
                          type="button"
                          onClick={(e) => handleDeleteConversation(e, conv.id)}
                          className="opacity-0 group-hover:opacity-100 p-1 hover:bg-red-500/20 rounded transition-all"
                        >
                          <Trash2 className="w-3.5 h-3.5 text-red-400" />
                        </button>
                      </div>
                    </motion.button>
                  ))
                )}
              </AnimatePresence>
            </div>
          </>
        ) : (
          <>
            {/* Admin: Knowledge Base Upload */}
            <div className="p-3 border-b border-gray-800">
              <label className={`w-full flex items-center gap-2 px-3 py-2.5 rounded-lg transition-colors cursor-pointer ${
                uploading ? 'bg-gray-700 text-gray-400 cursor-not-allowed' : 'bg-purple-600 hover:bg-purple-700 text-white'
              }`}>
                <Upload className="w-5 h-5" />
                <span className="font-medium">{uploading ? 'Uploading...' : 'Upload PDF'}</span>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf"
                  className="hidden"
                  onChange={handleUpload}
                  disabled={uploading}
                />
              </label>
              {uploadMsg && (
                <p className={`text-xs mt-2 px-1 ${uploadMsg.type === 'success' ? 'text-green-400' : 'text-red-400'}`}>
                  {uploadMsg.text}
                </p>
              )}
            </div>

            {/* Admin: Ingested Documents */}
            <div className="flex-1 overflow-y-auto p-3 space-y-2">
              <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 px-2">
                Knowledge Base Documents
              </h3>
              {loadingDocs && documents.length === 0 ? (
                <p className="text-xs text-gray-500 px-2">Loading...</p>
              ) : documents.length === 0 ? (
                <div className="text-center text-gray-500 mt-8 px-4">
                  <FileText className="w-12 h-12 mx-auto mb-2 opacity-30" />
                  <p className="text-sm">No documents yet</p>
                  <p className="text-xs mt-1">Upload a PDF to add to the knowledge base</p>
                </div>
              ) : (
                documents.map(doc => (
                  <div key={doc.s3_key} className="px-3 py-2 bg-white/5 rounded-lg">
                    <div className="flex items-center gap-2">
                      <FileText className="w-4 h-4 text-gray-400 flex-shrink-0" />
                      <p className="text-sm truncate">{doc.filename}</p>
                    </div>
                    <p className="text-xs text-gray-500 mt-0.5 ml-6">
                      {(doc.size_bytes / 1024).toFixed(1)} KB
                    </p>
                  </div>
                ))
              )}
            </div>
          </>
        )}

        {/* Footer */}
        <div className="border-t border-gray-800 p-3 space-y-2">
          <button
            type="button"
            onClick={toggleDarkMode}
            aria-label={isDarkMode ? 'Switch to light mode' : 'Switch to dark mode'}
            className="w-full flex items-center gap-2 px-3 py-2 hover:bg-white/10 rounded-lg transition-colors text-sm"
          >
            {isDarkMode ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
            <span>{isDarkMode ? 'Light mode' : 'Dark mode'}</span>
          </button>

          {user && (
            <div className="flex items-center gap-3 px-3 py-2 bg-white/5 rounded-lg">
              <div className="w-8 h-8 bg-gradient-to-br from-blue-400 to-purple-500 rounded-full flex items-center justify-center">
                <User className="w-4 h-4" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium truncate">User</p>
              </div>
              <button
                type="button"
                onClick={logout}
                className="p-1.5 hover:bg-red-500/20 rounded transition-colors"
                title="Logout"
                aria-label="Logout"
              >
                <LogOut className="w-4 h-4 text-red-400" />
              </button>
            </div>
          )}
        </div>
      </motion.aside>
    </>
  );
});

Sidebar.displayName = 'Sidebar';
