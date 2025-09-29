"""
RAG Service for Discord Bot Template Retrieval
Uses ChromaDB + LangChain for semantic search of bot templates
Embeddings are created ONCE and cached for performance
"""

import os
import json
import hashlib
from typing import List, Dict, Any, Optional
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain.schema import Document

class TemplateRAG:
    """
    Singleton RAG service for template retrieval
    - Embeds templates once on initialization
    - Persists embeddings to disk (ChromaDB)
    - Provides fast semantic search
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.templates_path = os.path.join(
            os.path.dirname(__file__),
            "templates",
            "discord_templates.json"
        )
        self.chroma_dir = os.path.join(
            os.path.dirname(__file__),
            "chroma_db"
        )
        self.hash_file = os.path.join(self.chroma_dir, "template_hash.txt")

        self.vector_store: Optional[Chroma] = None
        self.embeddings = None
        self.templates_data: List[Dict[str, Any]] = []

        self._initialized = True

    def _calculate_templates_hash(self) -> str:
        """Calculate hash of templates file to detect changes"""
        if not os.path.exists(self.templates_path):
            return ""

        with open(self.templates_path, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()

    def _should_reinitialize(self) -> bool:
        """Check if templates have changed since last initialization"""
        current_hash = self._calculate_templates_hash()

        if not os.path.exists(self.hash_file):
            return True

        try:
            with open(self.hash_file, 'r') as f:
                stored_hash = f.read().strip()
            return current_hash != stored_hash
        except:
            return True

    def _save_hash(self):
        """Save current templates hash"""
        os.makedirs(self.chroma_dir, exist_ok=True)
        current_hash = self._calculate_templates_hash()
        with open(self.hash_file, 'w') as f:
            f.write(current_hash)

    def _load_templates(self) -> List[Dict[str, Any]]:
        """Load templates from JSON file"""
        if not os.path.exists(self.templates_path):
            print(f"[RAG] WARNING: Templates file not found at {self.templates_path}")
            return []

        try:
            with open(self.templates_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                templates = data.get('templates', [])
                print(f"[RAG] Loaded {len(templates)} templates from JSON")
                return templates
        except Exception as e:
            print(f"[RAG] ERROR loading templates: {e}")
            return []

    def _create_documents(self) -> List[Document]:
        """Convert templates to LangChain Document objects"""
        documents = []

        for template in self.templates_data:
            # Create rich content for better semantic search
            content = f"""
Category: {template.get('category', 'unknown')}
Name: {template.get('name', 'unknown')}
Description: {template.get('description', '')}
Tags: {', '.join(template.get('tags', []))}

Code Implementation:
{template.get('code', '')}
"""

            metadata = {
                'category': template.get('category', 'unknown'),
                'name': template.get('name', 'unknown'),
                'description': template.get('description', ''),
                'tags': ', '.join(template.get('tags', [])),
                'dependencies': ', '.join(template.get('dependencies', []))
            }

            documents.append(Document(page_content=content, metadata=metadata))

        return documents

    def initialize(self, force_reinit: bool = False):
        """
        Initialize or reinitialize the RAG system
        - Loads templates from JSON
        - Creates embeddings (if needed)
        - Sets up ChromaDB vector store

        Args:
            force_reinit: Force reinitialization even if templates haven't changed
        """
        import time
        start = time.time()

        print("[RAG] Initializing template RAG system...")

        # Check if we need to reinitialize
        if not force_reinit and not self._should_reinitialize():
            if os.path.exists(self.chroma_dir) and self.vector_store is None:
                print("[RAG] Loading existing embeddings from disk...")
                try:
                    self.templates_data = self._load_templates()
                    self.embeddings = HuggingFaceEmbeddings(
                        model_name="sentence-transformers/all-MiniLM-L6-v2",
                        model_kwargs={'device': 'cpu'},
                        encode_kwargs={'normalize_embeddings': True}
                    )
                    self.vector_store = Chroma(
                        persist_directory=self.chroma_dir,
                        embedding_function=self.embeddings,
                        collection_name="discord_templates"
                    )
                    elapsed = time.time() - start
                    print(f"[RAG] ✅ Loaded existing embeddings in {elapsed:.2f}s")
                    return
                except Exception as e:
                    print(f"[RAG] Failed to load existing embeddings: {e}")
                    print("[RAG] Will create new embeddings...")

        # Load templates
        self.templates_data = self._load_templates()
        if not self.templates_data:
            print("[RAG] WARNING: No templates loaded, RAG system disabled")
            return

        # Initialize embeddings model (lightweight, fast)
        print("[RAG] Initializing embeddings model (all-MiniLM-L6-v2)...")
        self.embeddings = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            model_kwargs={'device': 'cpu'},
            encode_kwargs={'normalize_embeddings': True}
        )

        # Create documents
        documents = self._create_documents()
        print(f"[RAG] Created {len(documents)} document embeddings...")

        # Create or update vector store
        if os.path.exists(self.chroma_dir) and force_reinit:
            import shutil
            print("[RAG] Removing old embeddings...")
            shutil.rmtree(self.chroma_dir)

        print("[RAG] Creating ChromaDB vector store...")
        self.vector_store = Chroma.from_documents(
            documents=documents,
            embedding=self.embeddings,
            persist_directory=self.chroma_dir,
            collection_name="discord_templates"
        )

        # Save hash for future checks
        self._save_hash()

        elapsed = time.time() - start
        print(f"[RAG] ✅ Template RAG initialized in {elapsed:.2f}s")

    def get_relevant_templates(
        self,
        user_query: str,
        k: int = 3,
        category_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieve most relevant templates for a user query

        Args:
            user_query: User's bot description/request
            k: Number of templates to retrieve (default: 3)
            category_filter: Optional category to filter by

        Returns:
            List of template dictionaries with metadata
        """
        if self.vector_store is None:
            print("[RAG] WARNING: Vector store not initialized")
            return []

        try:
            # Use LangChain's similarity search
            if category_filter:
                filter_dict = {"category": category_filter}
                docs = self.vector_store.similarity_search(
                    user_query,
                    k=k,
                    filter=filter_dict
                )
            else:
                docs = self.vector_store.similarity_search(user_query, k=k)

            # Convert back to template format
            results = []
            for doc in docs:
                # Find the original template by name
                template_name = doc.metadata.get('name')
                for template in self.templates_data:
                    if template.get('name') == template_name:
                        results.append(template)
                        break

            print(f"[RAG] Retrieved {len(results)} relevant templates for query: '{user_query[:50]}...'")
            for i, t in enumerate(results, 1):
                print(f"[RAG]   {i}. {t.get('name')} ({t.get('category')})")

            return results

        except Exception as e:
            print(f"[RAG] ERROR during retrieval: {e}")
            return []

    def format_templates_for_prompt(self, templates: List[Dict[str, Any]]) -> str:
        """
        Format retrieved templates for inclusion in AI prompt

        Args:
            templates: List of template dictionaries

        Returns:
            Formatted string for AI prompt
        """
        if not templates:
            return "No specific templates found."

        formatted = []
        for i, template in enumerate(templates, 1):
            formatted.append(f"""
REFERENCE TEMPLATE {i}: {template.get('name', 'unknown')}
Category: {template.get('category', 'unknown')}
Description: {template.get('description', '')}
Tags: {', '.join(template.get('tags', []))}

Example Code Pattern:
```python
{template.get('code', '')[:1000]}{'...' if len(template.get('code', '')) > 1000 else ''}
```
""")

        return "\n".join(formatted)

    def reinitialize(self):
        """Force reinitialize the RAG system"""
        print("[RAG] Force reinitializing...")
        self.initialize(force_reinit=True)

    def get_all_categories(self) -> List[str]:
        """Get list of all template categories"""
        return list(set(t.get('category', 'unknown') for t in self.templates_data))

    def get_templates_by_category(self, category: str) -> List[Dict[str, Any]]:
        """Get all templates in a specific category"""
        return [t for t in self.templates_data if t.get('category') == category]


# Global singleton instance
_rag_instance: Optional[TemplateRAG] = None

def get_rag_service() -> TemplateRAG:
    """Get or create the global RAG service instance"""
    global _rag_instance
    if _rag_instance is None:
        _rag_instance = TemplateRAG()
    return _rag_instance
