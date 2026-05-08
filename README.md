# 🤖 Code Repository Q&A System

An intelligent AI-powered application that allows you to upload code repositories and ask questions about them using natural language. Built with RAG (Retrieval Augmented Generation), ChromaDB for vector search, and Anthropic's Claude for intelligent responses.

## 🎯 Project Overview

This is a production-ready work sample demonstrating:
- **RAG Architecture**: Semantic search over code using vector embeddings
- **Intelligent Code Parsing**: Language-aware chunking that respects code structure
- **Full-Stack Development**: React frontend + Python FastAPI backend
- **AI Integration**: Anthropic Claude API for natural language understanding
- **Vector Database**: ChromaDB for efficient similarity search

Perfect for AI Engineer portfolios - shows end-to-end product development skills.

## ✨ Key Features
(https://code-repository-qa-zl72-git-main-james-docktors-projects.vercel.app/)
### Backend
- ✅ Intelligent code parser supporting 20+ programming languages
- ✅ Semantic chunking (functions, classes) for Python & JavaScript
- ✅ Vector embeddings with ChromaDB
- ✅ RESTful API with FastAPI
- ✅ Source code citations with file paths and line numbers
- ✅ Token usage tracking for cost monitoring
- ✅ Multi-repository support

### Frontend
- ✅ Modern React UI with Tailwind CSS
- ✅ Drag-and-drop repository upload
- ✅ Real-time chat interface
- ✅ Code snippet display with metadata
- ✅ Repository management (upload, select, delete)
- ✅ Responsive design

## 🏗️ Architecture

```
┌─────────────────┐
│  React Frontend │
│   (Port 3000)   │
└────────┬────────┘
         │
         │ HTTP/REST
         ▼
┌─────────────────┐
│ FastAPI Backend │
│   (Port 8000)   │
└────────┬────────┘
         │
    ┌────┴─────┬──────────┐
    │          │          │
    ▼          ▼          ▼
┌────────┐ ┌────────┐ ┌────────┐
│ChromaDB│ │ Claude │ │  Code  │
│ Vector │ │  API   │ │ Parser │
│   DB   │ │        │ │        │
└────────┘ └────────┘ └────────┘
```

## 🚀 Quick Start

### Prerequisites
- Python 3.9+
- Node.js 16+
- Anthropic API key ([Get one here](https://console.anthropic.com/))

### Backend Setup

```bash
# Navigate to backend directory
cd backend

# Install dependencies
pip install -r requirements.txt

# Create .env file
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY

# Run the server
python main.py
```

Backend runs at `http://localhost:8000` with API docs at `http://localhost:8000/docs`

### Frontend Setup

```bash
# Navigate to frontend directory
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

Frontend runs at `http://localhost:3000`

## 📁 Project Structure

```
code-qa-system/
├── backend/
│   ├── main.py              # FastAPI application
│   ├── code_parser.py       # Code parsing logic
│   ├── requirements.txt     # Python dependencies
│   ├── .env.example         # Environment template
│   └── .gitignore           # Git ignore rules
│
├── frontend/
│   ├── src/
│   │   ├── App.jsx          # Main React component
│   │   ├── main.jsx         # React entry point
│   │   └── index.css        # Tailwind styles
│   ├── index.html           # HTML template
│   ├── package.json         # Node dependencies
│   ├── vite.config.js       # Vite configuration
│   ├── tailwind.config.js   # Tailwind configuration
│   └── .gitignore           # Git ignore rules
│
└── README.md                # This file
```

## 🎮 How to Use

1. **Start both servers** (backend on 8000, frontend on 3000)

2. **Upload a repository**:
   - Create a .zip file of any code repository
   - Click "Upload Repository" button
   - Select your .zip file
   - Wait for parsing to complete

3. **Ask questions**:
   - Type natural language questions in the chat
   - Examples:
     - "What does the main function do?"
     - "How is authentication handled?"
     - "What API endpoints are available?"
     - "Explain the database schema"

4. **View results**:
   - Get AI-generated answers
   - See source code citations
   - Check file paths and line numbers
   - Monitor token usage

## 💡 Technical Highlights

### Intelligent Code Parsing
- **Language Detection**: Automatic identification of 20+ languages
- **Semantic Chunking**: Splits code by functions/classes, not arbitrary lines
- **Metadata Tracking**: Preserves file paths, line numbers, language info
- **Smart Filtering**: Ignores node_modules, .git, binaries, etc.

### RAG Pipeline
1. User uploads code → Parser extracts chunks
2. ChromaDB generates embeddings automatically
3. User asks question → Query embedded
4. Vector search finds relevant chunks
5. Claude receives context + question
6. Response includes answer + citations

### Production Features
- ✅ Error handling and validation
- ✅ CORS configuration
- ✅ Persistent storage
- ✅ Token usage tracking
- ✅ Multi-repository support
- ✅ Clean architecture
- ✅ Comprehensive documentation

## 📊 Supported Languages

Python • JavaScript • TypeScript • Java • C/C++ • C# • Go • Rust • Ruby • PHP • Swift • Kotlin • R • SQL • Bash • YAML • JSON • HTML • CSS • Markdown

## 🎯 Use Cases

- **Code Documentation**: Generate documentation from codebases
- **Onboarding**: Help new developers understand projects
- **Code Review**: Query specific implementation details
- **Debugging**: Find how features are implemented
- **Learning**: Understand unfamiliar codebases
- **API Discovery**: Find available endpoints and functions

## 🧪 API Endpoints

### `POST /upload`
Upload a zipped code repository for indexing.

### `POST /query`
Query a repository with natural language.

**Request**:
```json
{
  "question": "How does authentication work?",
  "repo_id": "uuid",
  "top_k": 5
}
```

### `GET /repos`
List all uploaded repositories.

### `DELETE /repos/{repo_id}`
Delete a repository and its indexed data.

### `GET /health`
Health check and system status.

## 🚧 Future Enhancements

- [ ] GitHub URL support (clone repos directly)
- [ ] Syntax highlighting for code snippets
- [ ] Code modification suggestions
- [ ] Multi-file context windows
- [ ] Evaluation metrics dashboard
- [ ] Caching for repeated queries
- [ ] Fine-tuned embeddings for code
- [ ] Support for non-code files (docs, configs)

## 🐛 Troubleshooting

**Upload fails**:
- Ensure file is a valid .zip
- Check backend is running
- Verify .zip contains code files

**No answers**:
- Confirm repository is selected
- Check if chunks were created
- Verify ANTHROPIC_API_KEY is set

**CORS errors**:
- Ensure backend CORS allows frontend origin
- Check both servers are running on correct ports

**Slow responses**:
- Large repos take time to parse
- First query may be slower (embedding generation)
- Check your internet connection (API calls)

## 📝 License

This is a portfolio/work sample project. Feel free to use as reference.

## 🙏 Acknowledgments

- **Anthropic** for Claude API
- **ChromaDB** for vector database
- **FastAPI** for backend framework
- **React** for frontend framework

---

**Portfolio Note**: This project demonstrates end-to-end AI application development including RAG architecture, semantic search, code parsing, full-stack development, and production-ready features. Perfect showcase for AI Engineer positions.
