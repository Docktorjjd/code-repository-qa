// Code Repository Q&A System - Frontend
// Copyright (c) 2025 James [Your Last Name]
// Licensed under the MIT License

import React, { useState, useRef, useEffect } from 'react';
import { Upload, Send, Trash2, Code2, FileCode, Loader2, AlertCircle, CheckCircle } from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

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
  
  // NEW: Multi-file context state
  const [files, setFiles] = useState([]);
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [showFileSelector, setShowFileSelector] = useState(false);
  // NEW: Metrics dashboard state
  const [metrics, setMetrics] = useState(null);
  const [showDashboard, setShowDashboard] = useState(false);

  // Load repositories on mount
  useEffect(() => {
    fetchRepositories();
  }, []);

  // Auto-scroll to bottom of messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);
  // Load repositories on mount
  useEffect(() => {
    fetchRepositories();
  }, []);

  // Auto-scroll to bottom of messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Fetch files when repo changes
  useEffect(() => {
    if (currentRepoId) {
      fetchFiles(currentRepoId);
    }
  }, [currentRepoId]);

  // Fetch files when repo changes
  useEffect(() => {
    if (currentRepoId) {
      fetchFiles(currentRepoId);
    }
  }, [currentRepoId]);

  const fetchMetrics = async () => {
    try {
      const response = await fetch(`${API_BASE}/metrics`);
      const data = await response.json();
      setMetrics(data);
    } catch (error) {
      console.error('Error fetching metrics:', error);
    }
  };

  const rateQuery = async (queryId, rating) => {
    try {
      await fetch(`${API_BASE}/queries/${queryId}/rate?rating=${rating}`, {
        method: 'POST',
      });
      // Refresh metrics after rating
      fetchMetrics();
    } catch (error) {
      console.error('Error rating query:', error);
    }
  };

  
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


  const fetchFiles = async (repoId) => {
    try {
      const response = await fetch(`${API_BASE}/repos/${repoId}/files`);
      const data = await response.json();
      setFiles(data.files || []);
    } catch (error) {
      console.error('Error fetching files:', error);
      setFiles([]);
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
          selected_files: selectedFiles.length > 0 ? selectedFiles : null,
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
        query_id: data.query_id, 
        validation_preview: data.validation_preview, 
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
        <div className="flex items-center justify-between gap-4">
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
            
            {/* Dashboard button */}
            <button
              onClick={() => {
                setShowDashboard(!showDashboard);
                if (!showDashboard) fetchMetrics();
              }}
              className="flex items-center gap-2 px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg transition-colors"
            >
              📊 {showDashboard ? 'Hide' : 'Show'} Dashboard
            </button>
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
        
        {/* Dashboard */}
        {showDashboard && metrics && (
          <div className="bg-slate-800/50 backdrop-blur-sm rounded-lg p-6 mb-6 border border-slate-700">
            <h2 className="text-2xl font-bold mb-6 flex items-center gap-2">
              📊 Evaluation Metrics Dashboard
            </h2>
            
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
              {/* Stat Cards */}
              <div className="bg-slate-700/50 rounded-lg p-4">
                <div className="text-slate-400 text-sm mb-1">Total Queries</div>
                <div className="text-2xl font-bold text-blue-400">
                  {metrics.overall.total_queries || 0}
                </div>
              </div>
              
              <div className="bg-slate-700/50 rounded-lg p-4">
                <div className="text-slate-400 text-sm mb-1">Avg Response Time</div>
                <div className="text-2xl font-bold text-green-400">
                  {metrics.overall.avg_response_time ? 
                    `${metrics.overall.avg_response_time.toFixed(2)}s` : 'N/A'}
                </div>
              </div>
              
              <div className="bg-slate-700/50 rounded-lg p-4">
                <div className="text-slate-400 text-sm mb-1">Avg Tokens</div>
                <div className="text-2xl font-bold text-purple-400">
                  {metrics.overall.avg_tokens ? 
                    Math.round(metrics.overall.avg_tokens) : 0}
                </div>
              </div>
              
              <div className="bg-slate-700/50 rounded-lg p-4">
                <div className="text-slate-400 text-sm mb-1">Positive Ratings</div>
                <div className="text-2xl font-bold text-emerald-400">
                  {metrics.ratings.positive || 0} 👍 / {metrics.ratings.negative || 0} 👎
                </div>
              </div>
            </div>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* Most Accessed Files */}
              <div className="bg-slate-700/30 rounded-lg p-4">
                <h3 className="text-lg font-semibold mb-3 flex items-center gap-2">
                  <FileCode className="w-5 h-5" />
                  Most Queried Files
                </h3>
                <div className="space-y-2">
                  {metrics.popular_files.length === 0 ? (
                    <p className="text-slate-400 text-sm">No data yet</p>
                  ) : (
                    metrics.popular_files.map((file, idx) => (
                      <div key={idx} className="flex items-center justify-between text-sm">
                        <span className="text-slate-300 truncate font-mono">
                          {file.file_path}
                        </span>
                        <span className="text-blue-400 font-semibold ml-2">
                          {file.access_count}x
                        </span>
                      </div>
                    ))
                  )}
                </div>
              </div>
              
              {/* Recent Queries */}
              <div className="bg-slate-700/30 rounded-lg p-4">
                <h3 className="text-lg font-semibold mb-3">Recent Queries</h3>
                <div className="space-y-2 max-h-60 overflow-y-auto">
                  {metrics.recent_queries.length === 0 ? (
                    <p className="text-slate-400 text-sm">No queries yet</p>
                  ) : (
                    metrics.recent_queries.map((query, idx) => (
                      <div key={idx} className="text-sm border-l-2 border-blue-500 pl-3 py-1">
                        <p className="text-slate-300 line-clamp-2">{query.question}</p>
                        <p className="text-slate-500 text-xs mt-1">
                          {query.response_time.toFixed(2)}s • {query.tokens_used} tokens
                        </p>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>
          </div>
        )}

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
    <Message key={idx} message={msg} rateQuery={rateQuery} />
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
{/* File Selector */}
<div className="border-t border-slate-700 p-4 bg-slate-900/50">
              <div className="flex items-center justify-between mb-2">
                <button
                  onClick={() => setShowFileSelector(!showFileSelector)}
                  className="flex items-center gap-2 px-3 py-2 bg-slate-800 hover:bg-slate-700 rounded-lg text-sm transition-colors"
                >
                  <FileCode className="w-4 h-4" />
                  <span>Select Files ({selectedFiles.length}/{files.length})</span>
                </button>
                
                {selectedFiles.length > 0 && (
                  <button
                    onClick={() => setSelectedFiles([])}
                    className="text-sm text-slate-400 hover:text-slate-300"
                  >
                    Clear Selection
                  </button>
                )}
              </div>

              {showFileSelector && (
                <div className="mt-3 max-h-60 overflow-y-auto bg-slate-800/50 rounded-lg p-3 space-y-2">
                  {files.length === 0 ? (
                    <p className="text-slate-400 text-sm">No files available. Upload a repository first.</p>
                  ) : (
                    files.map((file) => (
                      <label
                        key={file.file_path}
                        className="flex items-start gap-3 p-2 hover:bg-slate-700/50 rounded cursor-pointer"
                      >
                        <input
                          type="checkbox"
                          checked={selectedFiles.includes(file.file_path)}
                          onChange={(e) => {
                            if (e.target.checked) {
                              setSelectedFiles([...selectedFiles, file.file_path]);
                            } else {
                              setSelectedFiles(selectedFiles.filter(f => f !== file.file_path));
                            }
                          }}
                          className="mt-1"
                        />
                        <div className="flex-1 min-w-0">
                          <p className="text-sm text-slate-200 font-mono truncate">{file.file_path}</p>
                          <p className="text-xs text-slate-500">
                            {file.language} • {file.chunk_count} chunks • {file.total_lines} lines
                          </p>
                        </div>
                      </label>
                    ))
                  )}
                </div>
              )}
            </div>

            {/* Input */}
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

function Message({ message, rateQuery }) {
  const isUser = message.role === 'user';
  const [hasRated, setHasRated] = useState(false);
  
  const handleRate = async (rating) => {
    if (message.query_id && !hasRated) {
      await rateQuery(message.query_id, rating);
      setHasRated(true);
    }
  };
  
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
        
        <div className="text-slate-200 whitespace-pre-wrap">
          {message.content}
        </div>
        
        {/* Validation Preview */}
        {!isUser && message.validation_preview && (
          <div className="mt-4 p-3 bg-slate-800/50 rounded-lg border border-slate-600">
            <div className="text-xs font-semibold text-slate-300 mb-2 flex items-center gap-2">
              🔬 Multi-Model Validation
            </div>
            <div className="space-y-2 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Confidence:</span>
                <span className={`font-semibold ${
                  message.validation_preview.confidence_level === 'HIGH' ? 'text-green-400' :
                  message.validation_preview.confidence_level === 'MEDIUM' ? 'text-yellow-400' :
                  'text-red-400'
                }`}>
                  {(message.validation_preview.confidence_score * 100).toFixed(0)}% 
                  ({message.validation_preview.confidence_level})
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Models Agree:</span>
                <span className="text-slate-300 font-mono">
                  {message.validation_preview.models_agree}
                </span>
              </div>
              <div className="grid grid-cols-3 gap-2 mt-2">
                {Object.entries(message.validation_preview.model_agreements).map(([model, agrees]) => (
                  <div key={model} className="flex items-center gap-1 text-xs">
                    <span className={agrees ? 'text-green-400' : 'text-red-400'}>
                      {agrees ? '✓' : '✗'}
                    </span>
                    <span className="text-slate-400">{model}</span>
                  </div>
                ))}
              </div>
              <div className="pt-2 border-t border-slate-700">
                <span className={`text-xs font-semibold ${
                  message.validation_preview.recommendation === 'APPLY' ? 'text-green-400' :
                  message.validation_preview.recommendation === 'REVIEW' ? 'text-yellow-400' :
                  'text-red-400'
                }`}>
                  {message.validation_preview.recommendation === 'APPLY' ? '✅ READY TO APPLY' :
                   message.validation_preview.recommendation === 'REVIEW' ? '⚠️ NEEDS REVIEW' :
                   '❌ NOT RECOMMENDED'}
                </span>
              </div>
              <div className="text-xs text-slate-500 italic mt-2">
                {message.validation_preview.note}
              </div>
            </div>
          </div>
        )}
        
        {/* Rating buttons */}
        {!isUser && message.query_id && (
          <div className="mt-3 pt-3 border-t border-slate-600 flex items-center gap-2">
            <span className="text-xs text-slate-400">Was this helpful?</span>
            <button
              onClick={() => handleRate(1)}
              disabled={hasRated}
              className={`p-1 rounded hover:bg-slate-600 transition-colors ${
                hasRated ? 'opacity-50 cursor-not-allowed' : ''
              }`}
              title="Thumbs up"
            >
              👍
            </button>
            <button
              onClick={() => handleRate(-1)}
              disabled={hasRated}
              className={`p-1 rounded hover:bg-slate-600 transition-colors ${
                hasRated ? 'opacity-50 cursor-not-allowed' : ''
              }`}
              title="Thumbs down"
            >
              👎
            </button>
            {hasRated && <span className="text-xs text-green-400 ml-2">Thanks for your feedback!</span>}
          </div>
        )}
      </div>
    </div>
  );
}