# Code Repository Q&A System
# Copyright (c) 2025 James [Your Last Name]
# Licensed under the MIT License
# See LICENSE file in the project root for full license text

"""
Main application module for Code Repository Q&A System.
Provides FastAPI endpoints for semantic code search using RAG architecture.
"""
import os
import zipfile
import tempfile
import shutil
from typing import List, Dict, Tuple
from pathlib import Path
import re


class CodeChunk:
    """Represents a chunk of code with metadata"""
    def __init__(self, content: str, file_path: str, start_line: int, 
                 end_line: int, language: str, chunk_type: str = "block"):
        self.content = content
        self.file_path = file_path
        self.start_line = start_line
        self.end_line = end_line
        self.language = language
        self.chunk_type = chunk_type  # function, class, block, etc.
    
    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "file_path": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "language": self.language,
            "chunk_type": self.chunk_type
        }


class CodeParser:
    """Parse code repositories into semantically meaningful chunks"""
    
    # File extensions to language mapping
    LANGUAGE_MAP = {
        '.py': 'python',
        '.js': 'javascript',
        '.jsx': 'javascript',
        '.ts': 'typescript',
        '.tsx': 'typescript',
        '.java': 'java',
        '.cpp': 'cpp',
        '.c': 'c',
        '.h': 'c',
        '.hpp': 'cpp',
        '.cs': 'csharp',
        '.go': 'go',
        '.rs': 'rust',
        '.rb': 'ruby',
        '.php': 'php',
        '.swift': 'swift',
        '.kt': 'kotlin',
        '.r': 'r',
        '.sql': 'sql',
        '.sh': 'bash',
        '.yaml': 'yaml',
        '.yml': 'yaml',
        '.json': 'json',
        '.xml': 'xml',
        '.html': 'html',
        '.css': 'css',
        '.md': 'markdown',
    }
    
    # Files/directories to ignore
    IGNORE_PATTERNS = {
        '__pycache__', 'node_modules', '.git', '.venv', 'venv',
        'dist', 'build', '.next', '.cache', 'target', 'bin', 'obj',
        '.pytest_cache', 'coverage', '.idea', '.vscode'
    }
    
    # Binary and non-text extensions to skip
    SKIP_EXTENSIONS = {
        '.pyc', '.pyo', '.so', '.dylib', '.dll', '.exe', '.bin',
        '.jpg', '.jpeg', '.png', '.gif', '.pdf', '.zip', '.tar',
        '.gz', '.mp4', '.mp3', '.lock', '.min.js', '.map'
    }
    
    def __init__(self, max_chunk_size: int = 1000, overlap: int = 100):
        self.max_chunk_size = max_chunk_size
        self.overlap = overlap
    
    def extract_zip(self, zip_path: str) -> str:
        """Extract zip file to temporary directory"""
        temp_dir = tempfile.mkdtemp()
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)
            return temp_dir
        except Exception as e:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise Exception(f"Failed to extract zip: {str(e)}")
    
    def should_ignore(self, path: Path) -> bool:
        """Check if path should be ignored"""
        parts = path.parts
        return any(pattern in parts for pattern in self.IGNORE_PATTERNS)
    
    def get_language(self, file_path: str) -> str:
        """Determine language from file extension"""
        ext = Path(file_path).suffix.lower()
        return self.LANGUAGE_MAP.get(ext, 'text')
    
    def parse_repository(self, repo_path: str) -> List[CodeChunk]:
        """Parse entire repository into chunks"""
        chunks = []
        repo_path = Path(repo_path)
        
        # Walk through all files
        for file_path in repo_path.rglob('*'):
            if not file_path.is_file():
                continue
            
            # Skip ignored paths and extensions
            if self.should_ignore(file_path):
                continue
            
            if file_path.suffix.lower() in self.SKIP_EXTENSIONS:
                continue
            
            # Get relative path from repo root
            try:
                rel_path = file_path.relative_to(repo_path)
            except ValueError:
                continue
            
            # Parse the file
            file_chunks = self.parse_file(str(file_path), str(rel_path))
            chunks.extend(file_chunks)
        
        return chunks
    
    def parse_file(self, file_path: str, rel_path: str) -> List[CodeChunk]:
        """Parse a single file into chunks"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except Exception as e:
            print(f"Error reading {file_path}: {e}")
            return []
        
        if not content.strip():
            return []
        
        language = self.get_language(file_path)
        
        # Try semantic chunking first (for supported languages)
        if language == 'python':
            return self.chunk_python(content, rel_path, language)
        elif language in ['javascript', 'typescript']:
            return self.chunk_javascript(content, rel_path, language)
        else:
            # Fallback to simple chunking
            return self.chunk_by_lines(content, rel_path, language)
    
    def chunk_python(self, content: str, file_path: str, language: str) -> List[CodeChunk]:
        """Chunk Python code by functions and classes"""
        chunks = []
        lines = content.split('\n')
        
        # Pattern to match function/class definitions
        func_pattern = re.compile(r'^(def|class)\s+(\w+)')
        
        current_chunk = []
        current_start = 1
        indent_level = 0
        in_definition = False
        
        for i, line in enumerate(lines, 1):
            stripped = line.lstrip()
            
            # Check if this is a function or class definition
            match = func_pattern.match(stripped)
            
            if match and not in_definition:
                # Save previous chunk if it exists
                if current_chunk:
                    chunk_content = '\n'.join(current_chunk)
                    if chunk_content.strip():
                        chunks.append(CodeChunk(
                            content=chunk_content,
                            file_path=file_path,
                            start_line=current_start,
                            end_line=i - 1,
                            language=language,
                            chunk_type="block"
                        ))
                
                # Start new chunk
                current_chunk = [line]
                current_start = i
                in_definition = True
                indent_level = len(line) - len(stripped)
            
            elif in_definition:
                current_chunk.append(line)
                
                # Check if we've left the definition (unindent or empty line followed by new def)
                if stripped and not line.startswith(' ' * (indent_level + 1)) and i > current_start:
                    # Check if next line is a new definition at same level
                    if func_pattern.match(stripped):
                        # End current chunk (don't include this line)
                        chunk_content = '\n'.join(current_chunk[:-1])
                        if chunk_content.strip():
                            chunks.append(CodeChunk(
                                content=chunk_content,
                                file_path=file_path,
                                start_line=current_start,
                                end_line=i - 1,
                                language=language,
                                chunk_type=current_chunk[0].strip().split()[0]
                            ))
                        
                        # Start new chunk with this line
                        current_chunk = [line]
                        current_start = i
                        indent_level = len(line) - len(stripped)
            else:
                current_chunk.append(line)
        
        # Add final chunk
        if current_chunk:
            chunk_content = '\n'.join(current_chunk)
            if chunk_content.strip():
                chunks.append(CodeChunk(
                    content=chunk_content,
                    file_path=file_path,
                    start_line=current_start,
                    end_line=len(lines),
                    language=language,
                    chunk_type="block"
                ))
        
        # If no semantic chunks found or file is small, return whole file
        if not chunks or len(chunks) == 1 and len(content) < self.max_chunk_size:
            return [CodeChunk(
                content=content,
                file_path=file_path,
                start_line=1,
                end_line=len(lines),
                language=language,
                chunk_type="file"
            )]
        
        return chunks
    
    def chunk_javascript(self, content: str, file_path: str, language: str) -> List[CodeChunk]:
        """Chunk JavaScript/TypeScript code by functions"""
        chunks = []
        lines = content.split('\n')
        
        # Pattern for function declarations
        func_pattern = re.compile(r'^\s*(export\s+)?(async\s+)?(function|const|let|var)\s+\w+')
        class_pattern = re.compile(r'^\s*(export\s+)?(default\s+)?class\s+\w+')
        
        current_chunk = []
        current_start = 1
        brace_count = 0
        in_definition = False
        
        for i, line in enumerate(lines, 1):
            if func_pattern.match(line) or class_pattern.match(line):
                if current_chunk and not in_definition:
                    chunk_content = '\n'.join(current_chunk)
                    if chunk_content.strip():
                        chunks.append(CodeChunk(
                            content=chunk_content,
                            file_path=file_path,
                            start_line=current_start,
                            end_line=i - 1,
                            language=language,
                            chunk_type="block"
                        ))
                
                current_chunk = [line]
                current_start = i
                in_definition = True
                brace_count = line.count('{') - line.count('}')
            else:
                current_chunk.append(line)
                if in_definition:
                    brace_count += line.count('{') - line.count('}')
                    if brace_count == 0 and '{' in ''.join(current_chunk):
                        # End of function/class
                        chunk_content = '\n'.join(current_chunk)
                        if chunk_content.strip():
                            chunks.append(CodeChunk(
                                content=chunk_content,
                                file_path=file_path,
                                start_line=current_start,
                                end_line=i,
                                language=language,
                                chunk_type="function"
                            ))
                        current_chunk = []
                        current_start = i + 1
                        in_definition = False
        
        # Add final chunk
        if current_chunk:
            chunk_content = '\n'.join(current_chunk)
            if chunk_content.strip():
                chunks.append(CodeChunk(
                    content=chunk_content,
                    file_path=file_path,
                    start_line=current_start,
                    end_line=len(lines),
                    language=language,
                    chunk_type="block"
                ))
        
        if not chunks:
            return [CodeChunk(
                content=content,
                file_path=file_path,
                start_line=1,
                end_line=len(lines),
                language=language,
                chunk_type="file"
            )]
        
        return chunks
    
    def chunk_by_lines(self, content: str, file_path: str, language: str) -> List[CodeChunk]:
        """Fallback: chunk by lines with overlap"""
        lines = content.split('\n')
        chunks = []
        
        if len(lines) <= self.max_chunk_size:
            # Small file, return as single chunk
            return [CodeChunk(
                content=content,
                file_path=file_path,
                start_line=1,
                end_line=len(lines),
                language=language,
                chunk_type="file"
            )]
        
        # Chunk with overlap
        i = 0
        while i < len(lines):
            end = min(i + self.max_chunk_size, len(lines))
            chunk_lines = lines[i:end]
            
            chunks.append(CodeChunk(
                content='\n'.join(chunk_lines),
                file_path=file_path,
                start_line=i + 1,
                end_line=end,
                language=language,
                chunk_type="block"
            ))
            
            # Move forward with overlap
            i += self.max_chunk_size - self.overlap
        
        return chunks