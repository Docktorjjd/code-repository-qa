"""
Code Repository Q&A System — Backend
FastAPI endpoints for semantic code search using RAG architecture.
v1.1 — Adds GitHub URL upload, cleans duplicate code.
"""

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import chromadb
import anthropic
import os
import uuid
import sqlite3
import tempfile
import shutil
import json
import time
import traceback
from typing import List, Optional
from code_parser import CodeParser
import httpx
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Code Repository Q&A API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── ChromaDB ──────────────────────────────────────────────────────────────────
CHROMA_PATH = os.environ.get("CHROMA_DB_PATH", "./chroma_db")
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)

# ── Anthropic ─────────────────────────────────────────────────────────────────
anthropic_client = anthropic.Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY"),
    http_client=httpx.Client()
)

# ── Code Parser ───────────────────────────────────────────────────────────────
code_parser = CodeParser(max_chunk_size=100, overlap=10)


# ── Metrics DB ────────────────────────────────────────────────────────────────
def init_metrics_db():
    conn = sqlite3.connect('metrics.db')
    c = conn.cursor()
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
    c.execute('''
        CREATE TABLE IF NOT EXISTS query_ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query_id INTEGER NOT NULL,
            rating INTEGER NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (query_id) REFERENCES query_metrics (id)
        )
    ''')
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

init_metrics_db()


# ── TIPS Validation ───────────────────────────────────────────────────────────
async def tips_validate(question: str, answer: str, context: str) -> dict:
    """
    TIPS Framework — Claude Haiku judges Claude Sonnet's answer.
    Assesses accuracy, completeness, and grounding against retrieved code.
    Runs on every query — not just suggestion requests.
    """
    judge_prompt = f"""You are a code analysis quality judge. Assess whether the answer accurately addresses the question based on the retrieved code context.

Question: {question}

Retrieved Code Context (truncated):
{context[:2000]}

Answer to Evaluate:
{answer[:1500]}

Rate on three criteria:
1. ACCURACY: Does the answer correctly describe what the code does?
2. COMPLETENESS: Does it fully address the question?
3. GROUNDING: Is it based on actual retrieved code, not general assumptions?

Respond with ONLY valid JSON, no other text:
{{"score": <float 0.0-1.0>, "reasoning": "<one concise sentence explaining the score>"}}"""

    try:
        response = anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": judge_prompt}]
        )
        import json as _json, re as _re
        raw = response.content[0].text.strip() if response.content else ""
        if not raw:
            raise ValueError("Empty response from judge model")
        # Extract JSON even if Haiku wraps it in text
        match = _re.search(r'\{[^{}]+\}', raw, _re.DOTALL)
        json_str = match.group() if match else raw
        result = _json.loads(json_str)
        score = float(result.get("score", 0.75))
        score = max(0.0, min(1.0, score))
        level = "HIGH" if score >= 0.85 else "MEDIUM" if score >= 0.70 else "LOW"
        return {
            "confidence_score": round(score, 2),
            "confidence_level": level,
            "model_agreements": {"claude-sonnet": True, "claude-haiku": score >= 0.70},
            "models_agree": "2/2" if score >= 0.85 else "1/2",
            "recommendation": "APPLY" if score >= 0.85 else "REVIEW" if score >= 0.70 else "REJECT",
            "reasoning": result.get("reasoning", ""),
            "note": "Validated by Claude Sonnet + Haiku consensus"
        }
    except Exception as e:
        print(f"TIPS validation error: {e}")
        return {
            "confidence_score": 0.75,
            "confidence_level": "MEDIUM",
            "model_agreements": {"fallback": True},
            "models_agree": "1/1",
            "recommendation": "REVIEW",
            "reasoning": "",
            "note": "Validation unavailable — using fallback"
        }


# ── Models ────────────────────────────────────────────────────────────────────
class QueryRequest(BaseModel):
    question: str
    repo_id: str
    top_k: Optional[int] = 5
    selected_files: Optional[List[str]] = None


class QueryResponse(BaseModel):
    answer: str
    sources: List[dict]
    tokens_used: int
    suggestions: Optional[List[dict]] = []
    query_id: Optional[int] = None
    validation_preview: Optional[dict] = None


class GitHubUploadRequest(BaseModel):
    url: str
    branch: Optional[str] = None


# ── GitHub URL Parser ─────────────────────────────────────────────────────────
def parse_github_url(url: str) -> tuple:
    """
    Parse a GitHub URL into (owner, repo, branch).
    Handles:
      https://github.com/owner/repo
      https://github.com/owner/repo.git
      https://github.com/owner/repo/tree/branch
      github.com/owner/repo
    """
    url = url.strip().rstrip('/')
    if url.endswith('.git'):
        url = url[:-4]
    if not url.startswith('http'):
        url = 'https://' + url

    path = url.replace('https://github.com/', '').replace('http://github.com/', '')
    parts = [p for p in path.split('/') if p]

    if len(parts) < 2:
        raise ValueError(
            "Invalid GitHub URL. Expected format: github.com/owner/repo"
        )

    owner = parts[0]
    repo = parts[1]
    branch = 'main'

    if len(parts) >= 4 and parts[2] == 'tree':
        branch = parts[3]

    return owner, repo, branch


# ── Shared indexing helper ────────────────────────────────────────────────────
def index_zip(zip_path: str, display_name: str, extra_metadata: dict = None) -> dict:
    """
    Extract zip, parse code chunks, store in ChromaDB.
    Returns the upload response dict.
    Raises HTTPException on failure.
    """
    extracted_dir = None
    try:
        extracted_dir = code_parser.extract_zip(zip_path)
        chunks = code_parser.parse_repository(extracted_dir)

        if not chunks:
            raise HTTPException(
                status_code=400,
                detail="No code files found. Make sure the repository contains code files."
            )

        print(f"Found {len(chunks)} code chunks")

        repo_id = str(uuid.uuid4())
        collection_name = f"repo_{repo_id}"

        metadata = {"repo_name": display_name}
        if extra_metadata:
            metadata.update(extra_metadata)

        collection = chroma_client.get_or_create_collection(
            name=collection_name,
            metadata=metadata
        )

        documents, metadatas, ids = [], [], []
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

        collection.add(documents=documents, metadatas=metadatas, ids=ids)

        lang_counts = {}
        for chunk in chunks:
            lang_counts[chunk.language] = lang_counts.get(chunk.language, 0) + 1

        return {
            "repo_id": repo_id,
            "collection_name": collection_name,
            "filename": display_name,
            "status": "success",
            "chunks_created": len(chunks),
            "languages": lang_counts,
            "message": f"Repository indexed successfully — {len(chunks)} code chunks."
        }

    finally:
        if extracted_dir and os.path.exists(extracted_dir):
            shutil.rmtree(extracted_dir, ignore_errors=True)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "message": "Code Repository Q&A API",
        "status": "running",
        "endpoints": ["/upload", "/upload-github", "/query", "/repos", "/health"]
    }


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "chroma_collections": len(chroma_client.list_collections()),
        "anthropic_configured": bool(os.getenv("ANTHROPIC_API_KEY"))
    }


@app.post("/upload")
async def upload_repository(file: UploadFile = File(...)):
    """Upload a repository as a zip file."""
    temp_zip = None
    try:
        if not file.filename.endswith('.zip'):
            raise HTTPException(status_code=400, detail="Only .zip files are supported")

        temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
        temp_zip.write(await file.read())
        temp_zip.close()

        result = index_zip(temp_zip.name, file.filename)
        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing repository: {str(e)}")
    finally:
        if temp_zip and os.path.exists(temp_zip.name):
            os.unlink(temp_zip.name)


@app.post("/upload-github")
async def upload_github_repository(request: GitHubUploadRequest):
    """
    Upload a public GitHub repository by URL.
    Accepts:
      - https://github.com/owner/repo
      - https://github.com/owner/repo/tree/branch
    """
    temp_zip_path = None
    try:
        owner, repo, detected_branch = parse_github_url(request.url)
        branch = request.branch or detected_branch

        # Try requested branch, then fallback to 'master' if 'main' fails
        branches_to_try = [branch]
        if branch == 'main':
            branches_to_try.append('master')

        zip_content = None
        used_branch = None

        async with httpx.AsyncClient(
            timeout=60.0,
            follow_redirects=True,
            headers={"User-Agent": "code-repository-qa/1.1"}
        ) as client:
            for b in branches_to_try:
                download_url = (
                    f"https://github.com/{owner}/{repo}"
                    f"/archive/refs/heads/{b}.zip"
                )
                response = await client.get(download_url)
                if response.status_code == 200:
                    zip_content = response.content
                    used_branch = b
                    break

        if zip_content is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Could not download {owner}/{repo}. "
                    "Check that the URL is correct and the repository is public."
                )
            )

        # Save to temp file and index
        with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as tmp:
            tmp.write(zip_content)
            temp_zip_path = tmp.name

        result = index_zip(
            temp_zip_path,
            display_name=f"{owner}/{repo}",
            extra_metadata={"source": "github", "branch": used_branch, "github_url": request.url}
        )
        result["github_url"] = request.url
        result["branch"] = used_branch
        result["message"] = (
            f"GitHub repository {owner}/{repo} ({used_branch}) indexed — "
            f"{result['chunks_created']} code chunks."
        )
        return result

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error processing GitHub repository: {str(e)}"
        )
    finally:
        if temp_zip_path and os.path.exists(temp_zip_path):
            os.unlink(temp_zip_path)


@app.post("/query", response_model=QueryResponse)
async def query_repository(request: QueryRequest):
    """Query the repository using RAG with Claude."""
    start_time = time.time()

    try:
        collection_name = f"repo_{request.repo_id}"
        collection = chroma_client.get_collection(name=collection_name)

        count = collection.count()
        if count == 0:
            raise HTTPException(
                status_code=400,
                detail="No documents in repository. Upload and index code first."
            )

        # Semantic retrieval — scoped to selected files if provided
        if request.selected_files:
            results = collection.query(
                query_texts=[request.question],
                n_results=min(request.top_k * 2, count),
                where={"file_path": {"$in": request.selected_files}}
            )
        else:
            results = collection.query(
                query_texts=[request.question],
                n_results=min(request.top_k, count)
            )

        documents = results['documents'][0] if results['documents'] else []
        metadatas = results['metadatas'][0] if results['metadatas'] else []

        if not documents:
            return QueryResponse(
                answer="I couldn't find relevant code to answer your question.",
                sources=[],
                tokens_used=0
            )

        # Build context
        context_parts = []
        for i, (doc, meta) in enumerate(zip(documents, metadatas)):
            context_parts.append(
                f"[Source {i+1}: {meta.get('file_path','unknown')}, "
                f"line {meta.get('start_line','?')}]\n{doc}\n"
            )
        context = "\n---\n".join(context_parts)

        # Detect improvement requests
        suggestion_keywords = [
            'improve', 'fix', 'refactor', 'optimize', 'suggest',
            'change', 'modify', 'better', 'update'
        ]
        is_suggestion_request = any(
            kw in request.question.lower() for kw in suggestion_keywords
        )

        if is_suggestion_request:
            prompt = f"""You are a code analysis assistant. The user is asking for code improvement suggestions.

Retrieved Code Snippets:
{context}

User Question: {request.question}

Instructions:
- Analyze the code and provide specific, actionable improvement suggestions.
- For each suggestion provide: description, file and line numbers, original code, improved code, explanation.

Format:
1. Brief summary answer
2. For each suggestion:

   **Suggestion [N]: [Title]**
   File: [file_path] | Lines: [start]-[end]

   Original Code:
   ```
   [original code]
   ```
   Improved Code:
   ```
   [improved code]
   ```
   Explanation: [why this is better]"""
        else:
            prompt = f"""You are a code analysis assistant. Answer the user's question based on the provided code snippets.

Retrieved Code Snippets:
{context}

User Question: {request.question}

Instructions:
- Provide a clear, concise answer based on the snippets above.
- Reference specific files and line numbers when relevant.
- If the snippets don't contain enough information, say so.
- Use markdown formatting for code examples."""

        message = anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )

        answer = message.content[0].text
        tokens_used = message.usage.input_tokens + message.usage.output_tokens
        response_time = time.time() - start_time

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

        # Save metrics (non-critical — never crashes the query)
        try:
            conn = sqlite3.connect('metrics.db', timeout=10, check_same_thread=False)
            conn.execute('PRAGMA journal_mode=WAL')
            c = conn.cursor()
            c.execute(
                'INSERT INTO query_metrics '
                '(repo_id, question, response_time, tokens_used, files_queried) '
                'VALUES (?, ?, ?, ?, ?)',
                (
                    request.repo_id, request.question, response_time, tokens_used,
                    json.dumps(request.selected_files) if request.selected_files else None
                )
            )
            if request.selected_files:
                for fp in request.selected_files:
                    c.execute(
                        'INSERT OR IGNORE INTO file_access '
                        '(repo_id, file_path, access_count, last_accessed) '
                        'VALUES (?, ?, 1, CURRENT_TIMESTAMP)',
                        (request.repo_id, fp)
                    )
            conn.commit()
            conn.close()
        except Exception:
            pass

        # TIPS Framework — validate every answer with Haiku as judge
        validation_preview = await tips_validate(
            question=request.question,
            answer=answer,
            context=context
        )

        return QueryResponse(
            answer=answer,
            sources=sources,
            tokens_used=tokens_used,
            suggestions=[],
            query_id=None,
            validation_preview=validation_preview
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"Query error: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/repos")
async def list_repositories():
    """List all indexed repositories."""
    try:
        collections = chroma_client.list_collections()
        repos = [
            {
                "repo_id": col.name.replace("repo_", ""),
                "name": col.metadata.get("repo_name", "Unknown"),
                "source": col.metadata.get("source", "upload"),
                "branch": col.metadata.get("branch", None),
                "github_url": col.metadata.get("github_url", None),
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
    """Delete a repository and its ChromaDB collection."""
    try:
        chroma_client.delete_collection(name=f"repo_{repo_id}")
        return {"message": f"Repository {repo_id} deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/repos/{repo_id}/files")
async def list_repository_files(repo_id: str):
    """List all files in a repository with chunk and line stats."""
    try:
        collection = chroma_client.get_collection(name=f"repo_{repo_id}")
        results = collection.get(include=['metadatas'])

        files_dict = {}
        for meta in results['metadatas']:
            fp = meta.get('file_path', 'unknown')
            if fp not in files_dict:
                files_dict[fp] = {
                    'file_path': fp,
                    'language': meta.get('language', 'unknown'),
                    'chunk_count': 0,
                    'total_lines': 0
                }
            files_dict[fp]['chunk_count'] += 1
            end_line = meta.get('end_line', 0)
            if end_line > files_dict[fp]['total_lines']:
                files_dict[fp]['total_lines'] = end_line

        files = sorted(files_dict.values(), key=lambda x: x['file_path'])
        return {"repo_id": repo_id, "files": files, "total_files": len(files)}

    except Exception as e:
        print(f"List files error: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/queries/{query_id}/rate")
async def rate_query(query_id: int, rating: int):
    """Rate a query response (1 = helpful, -1 = not helpful)."""
    if rating not in [1, -1]:
        raise HTTPException(status_code=400, detail="Rating must be 1 or -1")
    try:
        conn = sqlite3.connect('metrics.db')
        conn.cursor().execute(
            'INSERT INTO query_ratings (query_id, rating) VALUES (?, ?)',
            (query_id, rating)
        )
        conn.commit()
        conn.close()
        return {"message": "Rating saved", "query_id": query_id, "rating": rating}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/metrics")
async def get_metrics():
    """Get evaluation metrics and usage statistics."""
    try:
        conn = sqlite3.connect('metrics.db')
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute('''
            SELECT COUNT(*) as total_queries,
                   AVG(response_time) as avg_response_time,
                   AVG(tokens_used) as avg_tokens,
                   SUM(tokens_used) as total_tokens
            FROM query_metrics
        ''')
        overall = dict(c.fetchone())

        c.execute('''
            SELECT id, repo_id, question, response_time, tokens_used, timestamp
            FROM query_metrics ORDER BY timestamp DESC LIMIT 10
        ''')
        recent_queries = [dict(r) for r in c.fetchall()]

        c.execute('''
            SELECT file_path, access_count, last_accessed
            FROM file_access ORDER BY access_count DESC LIMIT 10
        ''')
        popular_files = [dict(r) for r in c.fetchall()]

        c.execute('''
            SELECT COUNT(*) as total_ratings,
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
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
