# Code Repository Q&A System
# Copyright (c) 2025 James [Your Last Name]
# Licensed under the MIT License
# See LICENSE file in the project root for full license text

"""
Main application module for Code Repository Q&A System.
Provides FastAPI endpoints for semantic code search using RAG architecture.
"""
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import chromadb
from chromadb.config import Settings
import anthropic
import os
from typing import List, Optional
import uuid
import sqlite3
from datetime import datetime
import tempfile
import shutil
from code_parser import CodeParser
import httpx
from dotenv import load_dotenv
import json
import httpx  # Add this line

# Load environment variables FIRST, before anything else
load_dotenv()

app = FastAPI(title="Code Repository Q&A API")

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # Local development
        "https://code-repository-qa.vercel.app"  # Production frontend
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize ChromaDB client (persistent storage)
chroma_client = chromadb.PersistentClient(path="./chroma_db")


# Initialize Anthropic client with explicit http_client to avoid proxies issue
import httpx
anthropic_client = anthropic.Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY"),
    http_client=httpx.Client()
)
async def call_llm_evaluator(original_code: str, improved_code: str, explanation: str, suggestion_type: str = "security") -> dict:
    """
    TIPS Framework - INTEGRATE stage: Call LLM Evaluator for real validation
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "http://localhost:8002/validate",
                json={
                    "file_path": "code.py",
                    "original_code": original_code,
                    "improved_code": improved_code,
                    "explanation": explanation,
                    "suggestion_type": suggestion_type
                }
            )
            
            if response.status_code == 200:
                validation = response.json()
                return {
                    "confidence_score": validation["confidence_score"],
                    "confidence_level": validation["confidence_level"],
                    "model_agreements": validation["model_agreements"],
                    "models_agree": validation["models_agree"],
                    "recommendation": validation["recommendation"],
                    "note": f"Validated by {validation['models_agree']} models"
                }
            else:
                # Fallback if validation service fails
                return {
                    "confidence_score": 0.75,
                    "confidence_level": "MEDIUM",
                    "model_agreements": {"fallback": True},
                    "models_agree": "1/1",
                    "recommendation": "REVIEW",
                    "note": "Validation service unavailable - using fallback"
                }
                
    except Exception as e:
        print(f"Validation API error: {e}")
        # Fallback if API call fails
        return {
            "confidence_score": 0.75,
            "confidence_level": "MEDIUM",
            "model_agreements": {"fallback": True},
            "models_agree": "1/1",
            "recommendation": "REVIEW",
            "note": f"Validation failed: {str(e)}"
        }
    
    agree_count = sum(agreements.values())
    
    return {
        "confidence_score": round(confidence, 2),
        "confidence_level": "HIGH" if confidence >= 0.85 else "MEDIUM" if confidence >= 0.70 else "LOW",
        "model_agreements": agreements,
        "models_agree": f"{agree_count}/{len(models)}",
        "recommendation": "APPLY" if confidence >= 0.85 else "REVIEW" if confidence >= 0.70 else "REJECT",
        "note": "Simulated validation - production version will use real multi-model evaluation"
    }
# Initialize metrics database
def init_metrics_db():
    conn = sqlite3.connect('metrics.db')
    c = conn.cursor()
    
    # Query metrics table
    c.execute('''
        CREATE TABLE IF NOT EXISTS query_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repo_id TEXT NOT NULL,
            question TEXT NOT NULL,
            response_time REAL NOT NULL,
            tokens_used INTEGER NOT NULL,
            files_queried TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Ratings table
    c.execute('''
        CREATE TABLE IF NOT EXISTS query_ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query_id INTEGER NOT NULL,
            rating INTEGER NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (query_id) REFERENCES query_metrics (id)
        )
    ''')
    
    # File access frequency table
    c.execute('''
        CREATE TABLE IF NOT EXISTS file_access (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repo_id TEXT NOT NULL,
            file_path TEXT NOT NULL,
            access_count INTEGER DEFAULT 1,
            last_accessed DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

# Initialize DB on startup
init_metrics_db()

# Initialize code parser
code_parser = CodeParser(max_chunk_size=100, overlap=10)

# Global state for current collection
current_collection = None
current_repo_id = None


class QueryRequest(BaseModel):
    question: str
    repo_id: str
    top_k: Optional[int] = 5
    selected_files: Optional[List[str]] = None  # Add file filtering


class QueryResponse(BaseModel):
    answer: str
    sources: List[dict]
    tokens_used: int
    suggestions: Optional[List[dict]] = []
    query_id: Optional[int] = None
    validation_preview: Optional[dict] = None  # ADD THIS LINE


@app.get("/")
async def root():
    return {
        "message": "Code Repository Q&A API",
        "status": "running",
        "endpoints": ["/upload", "/query", "/repos", "/health"]
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "chroma_collections": len(chroma_client.list_collections()),
        "anthropic_configured": bool(os.getenv("ANTHROPIC_API_KEY"))
    }


@app.post("/upload")
async def upload_repository(file: UploadFile = File(...)):
    """
    Upload a repository (zip file), parse code, and store in ChromaDB.
    """
    global current_collection, current_repo_id
    
    temp_zip = None
    extracted_dir = None
    
    try:
        # Validate file type
        if not file.filename.endswith('.zip'):
            raise HTTPException(status_code=400, detail="Only .zip files are supported")
        
        # Save uploaded file to temporary location
        temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
        content = await file.read()
        temp_zip.write(content)
        temp_zip.close()
        
        # Extract zip file
        extracted_dir = code_parser.extract_zip(temp_zip.name)
        
        # Parse repository
        print(f"Parsing repository from: {extracted_dir}")
        chunks = code_parser.parse_repository(extracted_dir)
        
        if not chunks:
            raise HTTPException(
                status_code=400, 
                detail="No code files found in repository. Make sure zip contains code files."
            )
        
        print(f"Found {len(chunks)} code chunks")
        
        # Generate unique repo ID
        repo_id = str(uuid.uuid4())
        
        # Create ChromaDB collection
        collection_name = f"repo_{repo_id}"
        collection = chroma_client.get_or_create_collection(
            name=collection_name,
            metadata={"repo_name": file.filename}
        )
        
        # Prepare data for ChromaDB
        documents = []
        metadatas = []
        ids = []
        
        for i, chunk in enumerate(chunks):
            documents.append(chunk.content)
            metadatas.append({
                "file_path": chunk.file_path,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "language": chunk.language,
                "chunk_type": chunk.chunk_type
            })
            ids.append(f"{repo_id}_{i}")
        
        # Add to ChromaDB (it will auto-generate embeddings)
        collection.add(
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )
        
        current_collection = collection
        current_repo_id = repo_id
        
        # Get language statistics
        lang_counts = {}
        for chunk in chunks:
            lang_counts[chunk.language] = lang_counts.get(chunk.language, 0) + 1
        
        return {
            "repo_id": repo_id,
            "collection_name": collection_name,
            "filename": file.filename,
            "status": "success",
            "chunks_created": len(chunks),
            "languages": lang_counts,
            "message": f"Repository parsed successfully! {len(chunks)} code chunks indexed."
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing repository: {str(e)}")
    finally:
        # Cleanup temporary files
        if temp_zip and os.path.exists(temp_zip.name):
            os.unlink(temp_zip.name)
        if extracted_dir and os.path.exists(extracted_dir):
            shutil.rmtree(extracted_dir, ignore_errors=True)


@app.post("/query", response_model=QueryResponse)
async def query_repository(request: QueryRequest):
    """
    Query the repository using RAG with Claude.
    """
    import time
    start_time = time.time()
    query_id = None
    
    try:
        # Get the collection for this repo
        collection_name = f"repo_{request.repo_id}"
        collection = chroma_client.get_collection(name=collection_name)
        
        # Check if collection has documents
        count = collection.count()
        if count == 0:
            raise HTTPException(
                status_code=400, 
                detail="No documents in repository. Upload and parse code first."
            )
        
# Query ChromaDB for relevant code chunks
        # If specific files are selected, filter to only those files
        if request.selected_files and len(request.selected_files) > 0:
            # Query with file path filter
            results = collection.query(
                query_texts=[request.question],
                n_results=min(request.top_k * 2, count),  # Get more results to filter
                where={"file_path": {"$in": request.selected_files}}
            )
        else:
            # Query all files
            results = collection.query(
                query_texts=[request.question],
                n_results=min(request.top_k, count)
            )
        
        # Extract documents and metadata
        documents = results['documents'][0] if results['documents'] else []
        metadatas = results['metadatas'][0] if results['metadatas'] else []
        
        if not documents:
            return QueryResponse(
                answer="I couldn't find relevant code to answer your question.",
                sources=[],
                tokens_used=0
            )
        
        # Build context from retrieved chunks
        context_parts = []
        for i, (doc, meta) in enumerate(zip(documents, metadatas)):
            file_path = meta.get('file_path', 'unknown')
            start_line = meta.get('start_line', '?')
            context_parts.append(
                f"[Source {i+1}: {file_path}, line {start_line}]\n{doc}\n"
            )
        
        context = "\n---\n".join(context_parts)
        
 # Detect if user is asking for code improvements/modifications
        suggestion_keywords = ['improve', 'fix', 'refactor', 'optimize', 'suggest', 'change', 'modify', 'better', 'update']
        is_suggestion_request = any(keyword in request.question.lower() for keyword in suggestion_keywords)
        
        # Create prompt for Claude
        if is_suggestion_request:
            prompt = f"""You are a code analysis assistant. The user is asking for code improvement suggestions.

Retrieved Code Snippets:
{context}

User Question: {request.question}

Instructions:
- Analyze the code and provide specific, actionable improvement suggestions
- For each suggestion, provide:
  * A clear description of the improvement
  * The specific file and line numbers affected
  * The original code snippet
  * The improved code snippet
  * Explanation of why this is better

Format your response as:
1. First, provide a brief summary answer
2. Then list each suggestion with:
   
   **Suggestion [N]: [Title]**
   File: [file_path]
   Lines: [start]-[end]
   
   Original Code:
```language
   [original code]
```
   
   Improved Code:
```language
   [improved code]
```
   
   Explanation: [why this is better]

Use markdown formatting for code examples."""
        else:
            prompt = f"""You are a code analysis assistant. Answer the user's question about their codebase based on the provided code snippets.

Retrieved Code Snippets:
{context}

User Question: {request.question}

Instructions:
- Provide a clear, concise answer based on the code snippets above
- Reference specific files and line numbers when relevant
- If the snippets don't contain enough information, say so
- Use markdown formatting for code examples"""
        # Call Claude API
        message = anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        # Extract response
        answer = message.content[0].text
        tokens_used = message.usage.input_tokens + message.usage.output_tokens
        
        # Format sources
        sources = [
            {
                "file_path": meta.get('file_path', 'unknown'),
                "start_line": meta.get('start_line', 0),
                "end_line": meta.get('end_line', 0),
                "language": meta.get('language', 'unknown'),
                "snippet": doc[:200] + "..." if len(doc) > 200 else doc
            }
            for doc, meta in zip(documents, metadatas)
        ]
        
# Calculate response time
        response_time = time.time() - start_time
        
        # Save metrics to database
        conn = sqlite3.connect('metrics.db')
        c = conn.cursor()
        
        # Insert query metrics
        c.execute('''
            INSERT INTO query_metrics (repo_id, question, response_time, tokens_used, files_queried)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            request.repo_id,
            request.question,
            response_time,
            tokens_used,
            json.dumps(request.selected_files) if request.selected_files else None
        ))
        
        query_id = c.lastrowid
        
        # Track file access
        if request.selected_files:
            for file_path in request.selected_files:
                c.execute('''
                    INSERT INTO file_access (repo_id, file_path, access_count, last_accessed)
                    VALUES (?, ?, 1, CURRENT_TIMESTAMP)
                    ON CONFLICT(repo_id, file_path) DO UPDATE SET
                        access_count = access_count + 1,
                        last_accessed = CURRENT_TIMESTAMP
                ''', (request.repo_id, file_path))
        
        conn.commit()
        conn.close()
        # Calculate response time
        response_time = time.time() - start_time
        
        # Save metrics to database
        conn = sqlite3.connect('metrics.db')
        c = conn.cursor()
        
        # Insert query metrics
        c.execute('''
            INSERT INTO query_metrics (repo_id, question, response_time, tokens_used, files_queried)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            request.repo_id,
            request.question,
            response_time,
            tokens_used,
            json.dumps(request.selected_files) if request.selected_files else None
        ))
        
        query_id = c.lastrowid
        
        # Track file access
        if request.selected_files:
            for file_path in request.selected_files:
                c.execute('''
                    INSERT INTO file_access (repo_id, file_path, access_count, last_accessed)
                    VALUES (?, ?, 1, CURRENT_TIMESTAMP)
                    ON CONFLICT(repo_id, file_path) DO UPDATE SET
                        access_count = access_count + 1,
                        last_accessed = CURRENT_TIMESTAMP
                ''', (request.repo_id, file_path))
        
        conn.commit()
        conn.close()
        
        # ADD THIS: Simulate validation for improvement suggestions
        validation_preview = None
        if is_suggestion_request:  # If this was an improvement query
            validation_preview = await call_llm_evaluator(
    original_code="password = request.POST['pwd']",
    improved_code="password = request.POST.get('pwd', '')",
    explanation="Prevents KeyError exception",
    suggestion_type="security"
)
        
        return QueryResponse(
            answer=answer,
            sources=sources,
            tokens_used=tokens_used,
            suggestions=[],
            query_id=query_id,
            validation_preview=validation_preview  # ADD THIS
        )

        return QueryResponse(
            answer=answer,
            sources=sources,
            tokens_used=tokens_used,
            suggestions=[],
            query_id=query_id
        )
        
    except Exception as e:
        # Add detailed error logging
        import traceback
        print(f"Query error: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/repos")
async def list_repositories():
    """List all uploaded repositories"""
    try:
        collections = chroma_client.list_collections()
        repos = [
            {
                "repo_id": col.name.replace("repo_", ""),
                "name": col.metadata.get("repo_name", "Unknown"),
                "document_count": col.count()
            }
            for col in collections
            if col.name.startswith("repo_")
        ]
        return {"repositories": repos}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/repos/{repo_id}")
async def delete_repository(repo_id: str):
    """Delete a repository and its collection"""
    try:
        collection_name = f"repo_{repo_id}"
        chroma_client.delete_collection(name=collection_name)
        return {"message": f"Repository {repo_id} deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@app.delete("/repos/{repo_id}")
async def delete_repository(repo_id: str):
    """Delete a repository and its collection"""
    try:
        collection_name = f"repo_{repo_id}"
        chroma_client.delete_collection(name=collection_name)
        return {"message": f"Repository {repo_id} deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/repos/{repo_id}/files")
async def list_repository_files(repo_id: str):
    """
    List all files in a repository with metadata.
    """
    try:
        collection_name = f"repo_{repo_id}"
        collection = chroma_client.get_collection(name=collection_name)
        
        # Get all documents with metadata
        results = collection.get(include=['metadatas'])
        metadatas = results['metadatas']
        
        # Extract unique files with stats
        files_dict = {}
        for meta in metadatas:
            file_path = meta.get('file_path', 'unknown')
            if file_path not in files_dict:
                files_dict[file_path] = {
                    'file_path': file_path,
                    'language': meta.get('language', 'unknown'),
                    'chunk_count': 0,
                    'total_lines': 0
                }
            
            files_dict[file_path]['chunk_count'] += 1
            end_line = meta.get('end_line', 0)
            if end_line > files_dict[file_path]['total_lines']:
                files_dict[file_path]['total_lines'] = end_line
        
        # Convert to sorted list
        files = sorted(files_dict.values(), key=lambda x: x['file_path'])
        
        return {
            "repo_id": repo_id,
            "files": files,
            "total_files": len(files)
        }
        return {
            "repo_id": repo_id,
            "files": files,
            "total_files": len(files)
        }
        
    except Exception as e:
        import traceback
        print(f"List files error: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/queries/{query_id}/rate")
async def rate_query(query_id: int, rating: int):
    """
    Rate a query response (1 for thumbs up, -1 for thumbs down).
    """
    try:
        if rating not in [1, -1]:
            raise HTTPException(status_code=400, detail="Rating must be 1 or -1")
        
        conn = sqlite3.connect('metrics.db')
        c = conn.cursor()
        
        c.execute('''
            INSERT INTO query_ratings (query_id, rating)
            VALUES (?, ?)
        ''', (query_id, rating))
        
        conn.commit()
        conn.close()
        
        return {"message": "Rating saved", "query_id": query_id, "rating": rating}
        
    except Exception as e:
        import traceback
        print(f"Rating error: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/metrics")
async def get_metrics():
    """
    Get evaluation metrics and statistics.
    """
    try:
        conn = sqlite3.connect('metrics.db')
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        # Overall stats
        c.execute('''
            SELECT 
                COUNT(*) as total_queries,
                AVG(response_time) as avg_response_time,
                AVG(tokens_used) as avg_tokens,
                SUM(tokens_used) as total_tokens
            FROM query_metrics
        ''')
        overall = dict(c.fetchone())
        
        # Recent queries
        c.execute('''
            SELECT 
                id,
                repo_id,
                question,
                response_time,
                tokens_used,
                timestamp
            FROM query_metrics
            ORDER BY timestamp DESC
            LIMIT 10
        ''')
        recent_queries = [dict(row) for row in c.fetchall()]
        
        # Most accessed files
        c.execute('''
            SELECT 
                file_path,
                access_count,
                last_accessed
            FROM file_access
            ORDER BY access_count DESC
            LIMIT 10
        ''')
        popular_files = [dict(row) for row in c.fetchall()]
        
        # Rating stats
        c.execute('''
            SELECT 
                COUNT(*) as total_ratings,
                SUM(CASE WHEN rating = 1 THEN 1 ELSE 0 END) as positive,
                SUM(CASE WHEN rating = -1 THEN 1 ELSE 0 END) as negative
            FROM query_ratings
        ''')
        ratings = dict(c.fetchone())
        
        conn.close()
        
        return {
            "overall": overall,
            "recent_queries": recent_queries,
            "popular_files": popular_files,
            "ratings": ratings
        }
        
    except Exception as e:
        import traceback
        print(f"Metrics error: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        import traceback
        print(f"List files error: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)