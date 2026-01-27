"""
AI and Credit configuration constants for Instagram automation
"""

# =============================================================================
# CREDIT COSTS (Configurable)
# =============================================================================

AI_CREDITS = {
    # Per message costs
    'AI_MESSAGE_SENT_COST': 0.5,          # Per AI message sent to user
    'AI_MESSAGE_RECEIVED_COST': 0.1,      # Per user message processed by AI

    # Embedding costs
    'EMBEDDING_COST_PER_1K_TOKENS': 0.02,  # text-embedding-3-small rate
    'EMBEDDING_COST_PER_PAGE': 0.5,        # Approximate per document page

    # RAG costs
    'RAG_QUERY_COST': 0.1,                 # Per knowledge retrieval query

    # Data extraction
    'DATA_EXTRACTION_COST': 0.2,           # Per structured data extraction
}


# =============================================================================
# AI MODEL CONFIGURATIONS
# =============================================================================

AI_MODELS = {
    'chat': 'gpt-4o-mini',                 # Primary chat model
    'chat_fallback': 'gpt-3.5-turbo',      # Fallback model
    'embedding': 'text-embedding-3-small',  # Embedding model
}

# Model pricing (USD per 1M tokens) - for cost tracking
MODEL_PRICING = {
    'gpt-4o-mini': {
        'input': 0.15,
        'output': 0.60,
    },
    'gpt-4o': {
        'input': 2.50,
        'output': 10.00,
    },
    'gpt-3.5-turbo': {
        'input': 0.50,
        'output': 1.50,
    },
    'text-embedding-3-small': {
        'input': 0.02,
        'output': 0,
    },
}


# =============================================================================
# EMBEDDING SETTINGS
# =============================================================================

EMBEDDING_SETTINGS = {
    'chunk_size': 500,              # Tokens per chunk
    'chunk_overlap': 50,            # Overlap between chunks
    'max_chunks_per_query': 5,      # Top K for RAG retrieval
    'embedding_dimensions': 1536,   # text-embedding-3-small dimensions
}


# =============================================================================
# AI CONVERSATION SETTINGS
# =============================================================================

AI_CONVERSATION_SETTINGS = {
    'default_max_turns': 10,        # Default max conversation turns
    'default_timeout_minutes': 60,  # Default session timeout
    'max_context_messages': 20,     # Max messages to include in context
    'summary_threshold': 10,        # Generate summary after N messages
}


# =============================================================================
# DOCUMENT PROCESSING
# =============================================================================

SUPPORTED_DOCUMENT_TYPES = {
    'pdf': {
        'mime_types': ['application/pdf'],
        'max_size_mb': 10,
        'extensions': ['.pdf'],
    },
    'docx': {
        'mime_types': ['application/vnd.openxmlformats-officedocument.wordprocessingml.document'],
        'max_size_mb': 10,
        'extensions': ['.docx'],
    },
    'text': {
        'mime_types': ['text/plain'],
        'max_size_mb': 5,
        'extensions': ['.txt'],
    },
    'csv': {
        'mime_types': ['text/csv', 'application/csv'],
        'max_size_mb': 10,
        'extensions': ['.csv'],
    },
    'excel': {
        'mime_types': [
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'application/vnd.ms-excel'
        ],
        'max_size_mb': 10,
        'extensions': ['.xlsx', '.xls'],
    },
}


# =============================================================================
# CONFIGURATION KEYS (stored in Configuration model)
# =============================================================================

CONFIG_KEYS = {
    'OPENAI_API_KEY': 'openai_api_key',
    'AI_ENABLED': 'ai_features_enabled',
}


# =============================================================================
# AI NODE STATUS
# =============================================================================

AI_SESSION_STATUS = {
    'AI_ACTIVE': 'ai_active',              # AI conversation in progress
    'AI_WAITING': 'ai_waiting_reply',      # Waiting for user reply
    'AI_COMPLETE': 'ai_complete',          # AI goal achieved
    'AI_MAX_TURNS': 'ai_max_turns',        # Max turns reached
    'AI_TIMEOUT': 'ai_timeout',            # Session timed out
    'AI_ERROR': 'ai_error',                # Error occurred
}


# =============================================================================
# GOAL COMPLETION MARKERS
# =============================================================================

# AI will include these in response to signal completion
GOAL_COMPLETE_MARKERS = [
    '[GOAL_COMPLETE]',
    '[CONVERSATION_END]',
]
