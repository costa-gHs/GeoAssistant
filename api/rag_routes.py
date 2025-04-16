from flask import Blueprint, request, jsonify, session
import logging
import os

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create the blueprint
rag_routes_bp = Blueprint('rag_routes', __name__)

# Define the specific assistant ID for RAG integration
RAG_ASSISTANT_ID = "asst_LqpNV5KZlig3wHiaY7RaAofw"

# Import LlamaCloud integration with error handling
try:
    from .llama_cloud_integration import llama_rag

    logger.info("LlamaCloud integration imported successfully")
except ImportError as e:
    logger.error(f"Error importing LlamaCloud integration: {e}")


    # Create a mock llama_rag for fallback
    class MockLlamaRAG:
        def __init__(self):
            self.enabled = False
            self.index_name = "MOCK_INDEX"
            logger.warning("Using mock LlamaRAG implementation - RAG functionality disabled")

        def retrieve_context(self, query):
            logger.info(f"Mock retrieve_context called for query: {query}")
            return []


    llama_rag = MockLlamaRAG()


@rag_routes_bp.route('/api/rag/context', methods=['POST'])
def get_rag_context():
    """
    Endpoint to retrieve RAG context for a given query.
    IMPORTANT: This implementation doesn't store context in session to avoid cookie size limits.
    """
    logger.info("RAG Context API endpoint called")

    if 'usuario_id' not in session:
        logger.warning("Authentication required for RAG context")
        return jsonify({'success': False, 'error': 'Authentication required'}), 403

    try:
        data = request.get_json()
        query = data.get('query', '')
        assistant_id = data.get('assistant_id', '')

        logger.info(f"RAG context requested: assistant_id={assistant_id}, query={query[:50]}...")

        # Only process for the specific RAG assistant
        if assistant_id != RAG_ASSISTANT_ID:
            logger.warning(f"RAG context requested for non-RAG assistant: {assistant_id}")
            return jsonify({
                'success': False,
                'error': 'RAG context is only available for specific assistants'
            }), 400

        if not query:
            logger.warning("Empty query provided for RAG context")
            return jsonify({'success': False, 'error': 'Query is required'}), 400

        # Retrieve context directly - don't store in session
        logger.info(f"Retrieving RAG context from LlamaCloud for query: {query[:50]}...")
        context = llama_rag.retrieve_context(query)
        logger.info(f"Retrieved {len(context)} context items")

        return jsonify({
            'success': True,
            'context': context
        })

    except Exception as e:
        logger.exception(f"Error in RAG context retrieval: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@rag_routes_bp.route('/api/rag/check_assistant', methods=['GET'])
def check_rag_assistant():
    """
    Check if the given assistant ID is RAG-enabled.
    """
    assistant_id = request.args.get('assistant_id', '')
    logger.info(f"Checking if assistant {assistant_id} is RAG-enabled")

    result = {
        'is_rag_enabled': assistant_id == RAG_ASSISTANT_ID,
        'rag_status': {
            'enabled': llama_rag.enabled,
            'index_name': llama_rag.index_name if hasattr(llama_rag, 'index_name') else None
        }
    }

    logger.info(f"RAG check result: {result}")
    return jsonify(result)


# Log that the blueprint is defined
logger.info(f"RAG routes blueprint defined with assistant ID: {RAG_ASSISTANT_ID}")