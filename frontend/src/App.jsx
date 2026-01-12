import React, { useState, useRef, useEffect } from 'react';
import { Upload, Send, Trash2, Code2, FileCode, Loader2, AlertCircle, CheckCircle } from 'lucide-react';

const API_BASE = 'http://localhost:8000';

export default function CodeQAApp() {
  const [repos, setRepos] = useState([]);
  const [currentRepoId, setCurrentRepoId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState('');
  const [isUploading, setIsUploading] = useState(false);
  const [isQuerying, setIsQuerying] = useState(false);
  const [uploadStatus, setUploadStatus] = useState(null);
  const fileInputRef = useRef(null);
  const messagesEndRef = useRef(null);

  // Load repositories on mount
  useEffect(() => {
    fetchRepositories();
  }, []);

  // Auto-scroll to bottom of messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const fetchRepositories = async () => {
    try {
      const response = await fetch(`${API_BASE}/repos`);
      const data = await response.json();
      setRepos(data.repositories || []);
      
      // Auto-select first repo if none selected
      if (data.repositories.length > 0 && !currentRepoId) {
        setCurrentRepoId(data.repositories[0].repo_id);
      }
    } catch (error) {
      console.error('Error fetching repos:', error);
    }
  };

  const handleFileUpload = async (event) => {
    const file = event.target.files[0];
    if (!file) return;

    if (!file.name.endsWith('.zip')) {
      setUploadStatus({ type: 'error', message: 'Please upload a .zip file' });
      return;
    }

    setIsUploading(true);
    setUploadStatus({ type: 'loading', message: 'Uploading and parsing repository...' });

    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await fetch(`${API_BASE}/upload`, {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        throw new Error('Upload failed');
      }

      const data = await response.json();
      
      setUploadStatus({
        type: 'success',
        message: `✓ Successfully indexed ${data.chunks_created} code chunks from ${Object.keys(data.languages).length} languages`
      });
      
      setCurrentRepoId(data.repo_id);
      setMessages([]);
      await fetchRepositories();
      
      setTimeout(() => setUploadStatus(null), 5000);
    } catch (error) {
      setUploadStatus({ type: 'error', message: `Upload failed: ${error.message}` });
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const handleQuery = async () => {
    if (!inputValue.trim() || !currentRepoId || isQuerying) return;

    const userMessage = {
      role: 'user',
      content: inputValue,
      timestamp: new Date().toISOString(),
    };

    setMessages(prev => [...prev, userMessage]);
    setInputValue('');
    setIsQuerying(true);

    try {
      const response = await fetch(`${API_BASE}/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: inputValue,
          repo_id: currentRepoId,
          top_k: 5,
        }),
      });

      if (!response.ok) {
        throw new Error('Query failed');
      }

      const data = await response.json();

      const assistantMessage = {
        role: 'assistant',
        content: data.answer,
        sources: data.sources,
        tokensUsed: data.tokens_used,
        timestamp: new Date().toISOString(),
      };

      setMessages(prev => [...prev, assistantMessage]);
    } catch (error) {
      const errorMessage = {
        role: 'assistant',
        content: `Error: ${error.message}`,
        timestamp: new Date().toISOString(),
        isError: true,
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setIsQuerying(false);
    }
  };

  const handleDeleteRepo = async (repoId) => {
    if (!confirm('Delete this repository? This cannot be undone.')) return;

    try {
      await fetch(`${API_BASE}/repos/${repoId}`, { method: 'DELETE' });
      
      if (currentRepoId === repoId) {
        setCurrentRepoId(null);
        setMessages([]);
      }
      
      await fetchRepositories();
    } catch (error) {
      console.error('Error deleting repo:', error);
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleQuery();
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 text-white">
      <div className="max-w-7xl mx-auto p-6">
        {/* Header */}
        <div className="mb-8">
          <div className="flex items-center gap-3 mb-2">
            <Code2 className="w-8 h-8 text-blue-400" />
            <h1 className="text-3xl font-bold bg-gradient-to-r from-blue-400 to-purple-400 bg-clip-text text-transparent">
              Code Repository Q&A
            </h1>
          </div>
          <p className="text-slate-400 ml-11">Ask questions about your codebase using AI-powered analysis</p>
        </div>

        {/* Upload Section */}
        <div className="bg-slate-800/50 backdrop-blur-sm rounded-lg p-6 mb-6 border border-slate-700">
          <div className="flex items-center gap-4">
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={isUploading}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-600 disabled:cursor-not-allowed rounded-lg transition-colors"
            >
              {isUploading ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Upload className="w-4 h-4" />
              )}
              {isUploading ? 'Uploading...' : 'Upload Repository (.zip)'}
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".zip"
              onChange={handleFileUpload}
              className="hidden"
            />
            
            {repos.length > 0 && (
              <select
                value={currentRepoId || ''}
                onChange={(e) => {
                  setCurrentRepoId(e.target.value);
                  setMessages([]);
                }}
                className="px-4 py-2 bg-slate-700 border border-slate-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">Select Repository</option>
                {repos.map(repo => (
                  <option key={repo.repo_id} value={repo.repo_id}>
                    {repo.name} ({repo.document_count} chunks)
                  </option>
                ))}
              </select>
            )}
          </div>

          {/* Upload Status */}
          {uploadStatus && (
            <div className={`mt-4 p-3 rounded-lg flex items-center gap-2 ${
              uploadStatus.type === 'error' ? 'bg-red-900/30 border border-red-700' :
              uploadStatus.type === 'success' ? 'bg-green-900/30 border border-green-700' :
              'bg-blue-900/30 border border-blue-700'
            }`}>
              {uploadStatus.type === 'loading' && <Loader2 className="w-4 h-4 animate-spin" />}
              {uploadStatus.type === 'error' && <AlertCircle className="w-4 h-4" />}
              {uploadStatus.type === 'success' && <CheckCircle className="w-4 h-4" />}
              <span className="text-sm">{uploadStatus.message}</span>
            </div>
          )}
        </div>

        {/* Repository List */}
        {repos.length > 0 && (
          <div className="bg-slate-800/50 backdrop-blur-sm rounded-lg p-4 mb-6 border border-slate-700">
            <h3 className="text-sm font-semibold text-slate-300 mb-3">Uploaded Repositories</h3>
            <div className="space-y-2">
              {repos.map(repo => (
                <div
                  key={repo.repo_id}
                  className={`flex items-center justify-between p-3 rounded-lg transition-colors ${
                    currentRepoId === repo.repo_id
                      ? 'bg-blue-900/30 border border-blue-700'
                      : 'bg-slate-700/30 hover:bg-slate-700/50'
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <FileCode className="w-4 h-4 text-blue-400" />
                    <div>
                      <div className="font-medium">{repo.name}</div>
                      <div className="text-xs text-slate-400">{repo.document_count} code chunks indexed</div>
                    </div>
                  </div>
                  <button
                    onClick={() => handleDeleteRepo(repo.repo_id)}
                    className="p-2 hover:bg-red-900/30 rounded-lg transition-colors"
                    title="Delete repository"
                  >
                    <Trash2 className="w-4 h-4 text-red-400" />
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Chat Interface */}
        {currentRepoId ? (
          <div className="bg-slate-800/50 backdrop-blur-sm rounded-lg border border-slate-700 overflow-hidden">
            {/* Messages */}
            <div className="h-96 overflow-y-auto p-6 space-y-4">
              {messages.length === 0 ? (
                <div className="text-center text-slate-400 mt-20">
                  <Code2 className="w-12 h-12 mx-auto mb-3 opacity-50" />
                  <p>Ask a question about your code repository</p>
                  <p className="text-sm mt-2">Try: "What does the main function do?" or "How is authentication handled?"</p>
                </div>
              ) : (
                messages.map((msg, idx) => (
                  <Message key={idx} message={msg} />
                ))
              )}
              {isQuerying && (
                <div className="flex items-center gap-2 text-slate-400">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Analyzing code...</span>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            {/* Input */}
            <div className="border-t border-slate-700 p-4">
              <div className="flex gap-2">
                <input
                  type="text"
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  onKeyPress={handleKeyPress}
                  placeholder="Ask about your code..."
                  disabled={isQuerying}
                  className="flex-1 px-4 py-2 bg-slate-700 border border-slate-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
                />
                <button
                  onClick={handleQuery}
                  disabled={!inputValue.trim() || isQuerying}
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-600 disabled:cursor-not-allowed rounded-lg transition-colors"
                >
                  <Send className="w-4 h-4" />
                </button>
              </div>
            </div>
          </div>
        ) : (
          <div className="bg-slate-800/50 backdrop-blur-sm rounded-lg border border-slate-700 p-12 text-center">
            <Upload className="w-16 h-16 mx-auto mb-4 text-slate-600" />
            <h3 className="text-xl font-semibold mb-2">No Repository Selected</h3>
            <p className="text-slate-400">Upload a repository to get started</p>
          </div>
        )}
      </div>
    </div>
  );
}

function Message({ message }) {
  const isUser = message.role === 'user';
  
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`max-w-3xl ${isUser ? 'bg-blue-900/30 border-blue-700' : 'bg-slate-700/30 border-slate-600'} border rounded-lg p-4`}>
        <div className="flex items-center gap-2 mb-2">
          <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs ${
            isUser ? 'bg-blue-600' : 'bg-purple-600'
          }`}>
            {isUser ? 'U' : 'AI'}
          </div>
          <span className="text-xs text-slate-400">
            {new Date(message.timestamp).toLocaleTimeString()}
          </span>
        </div>
        
        <div className="prose prose-invert prose-sm max-w-none">
          <div className="whitespace-pre-wrap">{message.content}</div>
        </div>

        {/* Sources */}
        {message.sources && message.sources.length > 0 && (
          <div className="mt-4 space-y-2">
            <div className="text-xs font-semibold text-slate-400">Sources:</div>
            {message.sources.map((source, idx) => (
              <div key={idx} className="bg-slate-900/50 rounded p-3 text-sm">
                <div className="flex items-center gap-2 mb-1">
                  <FileCode className="w-3 h-3 text-blue-400" />
                  <span className="font-mono text-xs text-blue-400">{source.file_path}</span>
                  <span className="text-xs text-slate-500">Lines {source.start_line}-{source.end_line}</span>
                </div>
                <pre className="text-xs text-slate-300 overflow-x-auto mt-2">
                  <code>{source.snippet}</code>
                </pre>
              </div>
            ))}
          </div>
        )}

        {/* Token usage */}
        {message.tokensUsed && (
          <div className="mt-2 text-xs text-slate-500">
            {message.tokensUsed.toLocaleString()} tokens used
          </div>
        )}
      </div>
    </div>
  );
}