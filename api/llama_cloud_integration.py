import os
from flask import session
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class LlamaCloudRAG:
    """
    Wrapper class for LlamaCloud RAG integration.
    Handles retrieval of context from LlamaCloud API.
    """

    def __init__(self):
        logger.info("Initializing LlamaCloudRAG")

        # Get API key from environment variables for security
        self.api_key = os.getenv("LLAMA_CLOUD_API_KEY", "")
        self.project = os.getenv("LLAMA_CLOUD_PROJECT", "Default")
        self.index_name = os.getenv("LLAMA_CLOUD_INDEX", "coming-sole-2025-04-15")

        logger.info(f"LlamaCloud config: project={self.project}, index={self.index_name}")

        if not self.api_key:
            logger.warning("LLAMA_CLOUD_API_KEY not set. RAG functionality will be disabled.")
            self.enabled = False
        else:
            self.enabled = True
            self._initialize_index()

    def _initialize_index(self):
        """Initialize the LlamaCloud index."""
        try:
            logger.info(f"Attempting to initialize LlamaCloud index: {self.index_name}")

            # Import here to delay import until needed
            try:
                from llama_index.indices.managed.llama_cloud import LlamaCloudIndex
                logger.info("Successfully imported LlamaCloudIndex")

                self.index = LlamaCloudIndex(
                    name=self.index_name,
                    project=self.project,
                    api_key=self.api_key
                )
                logger.info(f"LlamaCloud index initialized: {self.index_name}")
            except ImportError as e:
                logger.error(f"Error importing LlamaCloudIndex: {e}")
                logger.warning("Using placeholder implementation - no actual RAG functionality")
                self.enabled = False

        except Exception as e:
            logger.exception(f"Error initializing LlamaCloud index: {e}")
            self.enabled = False

    def retrieve_context(self, query):
        """
        Retrieve context from LlamaCloud for a given query.

        Args:
            query (str): The user's query

        Returns:
            list: List of context nodes or empty list if retrieval fails
        """
        logger.info(f"Retrieve context called for query: {query[:50]}...")

        if not self.enabled:
            logger.warning("RAG functionality disabled - returning empty context")
            return self._generate_debug_context(query)

        try:
            logger.info(f"Retrieving context from LlamaCloud for query: {query[:50]}...")
            retriever = self.index.as_retriever()
            nodes = retriever.retrieve(query)
            logger.info(f"Retrieved {len(nodes)} context nodes")

            # Format nodes for display
            formatted_nodes = []
            for i, node in enumerate(nodes):
                formatted_node = {
                    'id': i,
                    'text': node.text,
                    'score': node.score if hasattr(node, 'score') else None,
                    'source': node.metadata.get('source', 'Unknown') if hasattr(node, 'metadata') else 'Unknown'
                }
                formatted_nodes.append(formatted_node)
                logger.debug(f"Node {i}: score={formatted_node['score']}, source={formatted_node['source']}")

            # Cache in session for re-use
            if 'rag_context' not in session:
                session['rag_context'] = {}

            session['rag_context'][query] = formatted_nodes
            return formatted_nodes

        except Exception as e:
            logger.exception(f"Error retrieving context: {e}")
            # Return debug context in case of error
            return self._generate_debug_context(query)

    def _generate_debug_context(self, query):
        """Generate placeholder context for debugging purposes"""
        logger.info("Generating debug context")
        example_context = [
            {
                'id': 0,
                'text': f"This is a debug context for: '{query}'. LlamaCloud integration is not fully functional.",
                'score': 0.95,
                'source': 'Debug Source'
            },
            {
                'id': 1,
                'text': "To fix this issue, ensure your LLAMA_CLOUD_API_KEY environment variable is set and the llama_index package is installed.",
                'score': 0.85,
                'source': 'Debug Source'
            }
        ]

        # Cache even debug context
        if 'rag_context' not in session:
            session['rag_context'] = {}

        session['rag_context'][query] = example_context
        return example_context

    def answer_query(self, query):
        """
        Get a direct answer from LlamaCloud for a given query.

        Args:
            query (str): The user's query

        Returns:
            str: The response text or error message
        """
        if not self.enabled:
            return "RAG functionality is currently disabled."

        try:
            query_engine = self.index.as_query_engine()
            response = query_engine.query(query)
            return str(response)
        except Exception as e:
            logger.exception(f"Error answering query: {e}")
            return f"Error generating response: {str(e)}"


# Singleton instance
logger.info("Creating LlamaCloudRAG singleton instance")
llama_rag = LlamaCloudRAG()
logger.info(f"LlamaCloudRAG instance created with enabled={llama_rag.enabled}")