from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import chromadb
from chromadb.config import Settings
import anthropic
import os
from typing import List, Optional
import uuid
import tempfile
import shutil
from code_parser import CodeParser

app = FastAPI(title="Code Repository Q&A API")

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize ChromaDB client (persistent storage)
chroma_client = chromadb.PersistentClient(path="./chroma_db")

# Initialize Anthropic client
anthropic_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Initialize code parser
code_parser = CodeParser(max_chunk_size=100, overlap=10)

# Global state for current collection
current_collection = None
current_repo_id = None


class QueryRequest(BaseModel):
    question: str
    repo_id: str
    top_k: Optional[int] = 5


class QueryResponse(BaseModel):
    answer: str
    sources: List[dict]
    tokens_used: int


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
        
        # Create prompt for Claude
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
        
        return QueryResponse(
            answer=answer,
            sources=sources,
            tokens_used=tokens_used
        )
        
    except Exception as e:
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)