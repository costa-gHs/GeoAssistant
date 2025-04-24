import os
import time
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

is_vercel = os.environ.get('VERCEL', False) or os.environ.get('VERCEL_ENV')


class LlamaCloudRAG:
    """
    Wrapper class for LlamaCloud RAG integration.
    Optimized for serverless environments to minimize memory usage.
    """

    def __init__(self):
        logger.info("Initializing LlamaCloudRAG")

        # Fazer inicialização preguiçosa (lazy) para reduzir uso de memória
        self._initialized = False
        self._index = None

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
            # Não inicializar imediatamente - espere pela primeira chamada

    def _initialize_index(self):
        """Initialize the LlamaCloud index lazily."""
        if self._initialized:
            return

        try:
            logger.info(f"Lazy initialization of LlamaCloud index: {self.index_name}")

            # Import here to delay import until needed
            try:
                from llama_index.indices.managed.llama_cloud import LlamaCloudIndex
                logger.info("Successfully imported LlamaCloudIndex")

                # Definir timeout menor em ambiente Vercel
                timeout = 5 if is_vercel else 10

                self._index = LlamaCloudIndex(
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

        self._initialized = True

    def retrieve_context(self, query):
        """
        Retrieve context from LlamaCloud for a given query.
        Optimized to minimize response size for Vercel.

        Args:
            query (str): The user's query

        Returns:
            list: List of context nodes or empty list if retrieval fails
        """
        logger.info(f"Retrieve context called for query: {query[:50]}...")
        start_time = time.time()

        if not self.enabled:
            logger.warning("RAG functionality disabled - returning debug context")
            return self._generate_debug_context(query)

        # Inicializar preguiçosamente
        if not self._initialized:
            self._initialize_index()

        # Se falhar na inicialização
        if not self.enabled or not self._index:
            logger.warning("Index initialization failed - returning debug context")
            return self._generate_debug_context(query)

        try:
            retriever = self._index.as_retriever()

            # Definir limite menor em Vercel para prevenir timeouts
            limit = 3 if is_vercel else 5

            # Executar com timeout para evitar bloqueios
            retrieval_timeout = 4 if is_vercel else 8  # segundos

            # Tentar com timeout manual
            retrieval_start = time.time()
            try:
                nodes = retriever.retrieve(query)

                # Verificar se estamos excedendo o timeout
                if time.time() - retrieval_start > retrieval_timeout:
                    logger.warning(
                        f"Retrieval taking too long ({time.time() - retrieval_start:.2f}s) - using partial results")
                    # Continuar mesmo assim
            except Exception as e:
                logger.error(f"Error during retrieval: {e}")
                return self._generate_debug_context(query)

            elapsed = time.time() - start_time
            logger.info(f"Retrieved {len(nodes)} context nodes in {elapsed:.2f}s")

            # Modificar para Vercel: limitar número de resultados
            if is_vercel and len(nodes) > limit:
                logger.info(f"Vercel environment: limiting results to {limit}")
                nodes = nodes[:limit]

            # Format nodes for display with minimal data
            formatted_nodes = []
            for i, node in enumerate(nodes):
                # Limite muito menor para texto em ambiente serverless
                max_text_length = 250 if is_vercel else 500

                if hasattr(node, 'text'):
                    text = node.text
                    if len(text) > max_text_length:
                        text = text[:max_text_length] + "..."
                else:
                    text = "No text available"

                # Eliminar campos não essenciais para reduzir tamanho
                formatted_node = {
                    'id': i,
                    'text': text,
                    'score': float(node.score) if hasattr(node, 'score') else None
                }

                # Adicionar fonte apenas se não for ambiente Vercel
                if not is_vercel and hasattr(node, 'metadata'):
                    formatted_node['source'] = node.metadata.get('source', 'Unknown')

                formatted_nodes.append(formatted_node)

            return formatted_nodes

        except Exception as e:
            elapsed = time.time() - start_time
            logger.exception(f"Error retrieving context after {elapsed:.2f}s: {e}")
            return self._generate_debug_context(query)

    def _generate_debug_context(self, query):
        """Generate minimal debug context - especially for Vercel"""
        logger.info("Generating debug context")

        # Versão muito simplificada para Vercel
        if is_vercel:
            return [
                {
                    'id': 0,
                    'text': f"Debug context for Vercel environment. Query: '{query[:30]}...'",
                    'score': 0.95
                }
            ]

        # Versão normal
        example_context = [
            {
                'id': 0,
                'text': f"This is a debug context for: '{query}'. Make sure LLAMA_CLOUD_API_KEY is set.",
                'score': 0.95,
                'source': 'Debug'
            },
            {
                'id': 1,
                'text': "To enable RAG, ensure the llama_index package is installed.",
                'score': 0.85,
                'source': 'Debug'
            }
        ]

        return example_context


# Singleton instance - com inicialização preguiçosa
logger.info("Creating LlamaCloudRAG singleton instance")
llama_rag = LlamaCloudRAG()
logger.info(f"LlamaCloudRAG instance prepared with enabled={llama_rag.enabled}")