"""
AI Engine for handling AI conversational nodes in DM flows.

This module is SEPARATE from flow_engine.py to avoid any interference
with existing flow logic. It handles:
- AI node execution
- AI message processing
- Knowledge retrieval (RAG)
- Credit deduction
- Goal completion checking
"""

import json
import logging
from typing import Optional, Dict, List, Tuple, Any
from django.utils import timezone
from openai import OpenAI

from core.models import Configuration
from .models import (
    FlowSession, FlowNode, FlowExecutionLog,
    SocialAgent, KnowledgeBase, KnowledgeItem, KnowledgeChunk,
    AINodeConfig, AIConversationMessage, AIUsageLog, AICollectedData
)
from .constants import (
    AI_CREDITS, AI_MODELS, MODEL_PRICING,
    EMBEDDING_SETTINGS, AI_CONVERSATION_SETTINGS,
    GOAL_COMPLETE_MARKERS, AI_SESSION_STATUS
)

logger = logging.getLogger(__name__)


# =============================================================================
# OpenAI Client
# =============================================================================

def get_openai_client() -> Optional[OpenAI]:
    """Get OpenAI client using API key from Configuration model"""
    api_key = Configuration.get_value('openai_api_key', '')
    if not api_key:
        logger.error("OpenAI API key not configured")
        return None
    return OpenAI(api_key=api_key)


# =============================================================================
# Credit Management
# =============================================================================

class CreditManager:
    """Handles credit checking and deduction"""

    @staticmethod
    def has_credits(user, required: float) -> bool:
        """Check if user has enough credits"""
        try:
            profile = user.profile
            return profile.credits >= required
        except Exception:
            return False

    @staticmethod
    def deduct_credits(user, amount: float, reason: str = '') -> bool:
        """Deduct credits from user balance"""
        try:
            profile = user.profile
            if profile.credits >= amount:
                profile.credits -= amount
                profile.save(update_fields=['credits', 'updated_at'])
                logger.info(f"Deducted {amount} credits from {user.email}. Reason: {reason}")
                return True
            return False
        except Exception as e:
            logger.error(f"Error deducting credits: {e}")
            return False

    @staticmethod
    def get_message_cost() -> float:
        """Get cost per AI message sent"""
        return AI_CREDITS.get('AI_MESSAGE_SENT_COST', 0.5)

    @staticmethod
    def get_received_message_cost() -> float:
        """Get cost for processing user message"""
        return AI_CREDITS.get('AI_MESSAGE_RECEIVED_COST', 0.1)


# =============================================================================
# Knowledge Retrieval (RAG)
# =============================================================================

class KnowledgeRetriever:
    """Handles knowledge base queries using embeddings"""

    def __init__(self, client: OpenAI):
        self.client = client
        self.embedding_model = AI_MODELS.get('embedding', 'text-embedding-3-small')

    def get_embedding(self, text: str) -> List[float]:
        """Generate embedding for text"""
        try:
            response = self.client.embeddings.create(
                model=self.embedding_model,
                input=text
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            return []

    def cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors"""
        if not vec1 or not vec2:
            return 0.0
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = sum(a * a for a in vec1) ** 0.5
        norm2 = sum(b * b for b in vec2) ** 0.5
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot_product / (norm1 * norm2)

    def retrieve_relevant_chunks(
        self,
        query: str,
        knowledge_bases: List[KnowledgeBase],
        top_k: int = None
    ) -> List[Dict]:
        """Retrieve most relevant chunks from knowledge bases"""
        if top_k is None:
            top_k = EMBEDDING_SETTINGS.get('max_chunks_per_query', 5)

        if not knowledge_bases:
            return []

        # Get query embedding
        query_embedding = self.get_embedding(query)
        if not query_embedding:
            return []

        # Get all chunks from the knowledge bases
        kb_ids = [kb.id for kb in knowledge_bases]
        chunks = KnowledgeChunk.objects.filter(
            knowledge_item__knowledge_base_id__in=kb_ids,
            knowledge_item__processing_status='completed'
        ).select_related('knowledge_item')

        # Calculate similarity scores
        scored_chunks = []
        for chunk in chunks:
            if chunk.embedding:
                similarity = self.cosine_similarity(query_embedding, chunk.embedding)
                scored_chunks.append({
                    'chunk_id': chunk.id,
                    'content': chunk.content,
                    'score': similarity,
                    'metadata': chunk.metadata,
                    'source': chunk.knowledge_item.title or chunk.knowledge_item.file_name
                })

        # Sort by similarity and return top K
        scored_chunks.sort(key=lambda x: x['score'], reverse=True)
        return scored_chunks[:top_k]


# =============================================================================
# AI Conversation Handler
# =============================================================================

class AIConversationHandler:
    """
    Handles AI conversation within a flow node.
    Completely separate from existing flow logic.
    """

    def __init__(self, session: FlowSession, ai_config: AINodeConfig):
        self.session = session
        self.ai_config = ai_config
        self.agent = ai_config.agent
        self.user = session.flow.user
        self.client = get_openai_client()
        self.knowledge_retriever = KnowledgeRetriever(self.client) if self.client else None

    def initialize_ai_conversation(self) -> Tuple[bool, str]:
        """
        Initialize AI conversation when flow enters AI node.
        Returns (success, first_message or error)
        """
        if not self.client:
            return False, "AI service not configured"

        # Check credits
        cost = CreditManager.get_message_cost()
        if not CreditManager.has_credits(self.user, cost):
            return False, "Insufficient credits for AI conversation"

        # Check if there's previous AI conversation history in this session
        previous_messages = AIConversationMessage.objects.filter(
            session=self.session
        ).exists()

        # Create or get AICollectedData record
        ai_data, created = AICollectedData.objects.get_or_create(
            session=self.session,
            defaults={
                'ai_config': self.ai_config,
                'schema_snapshot': self.ai_config.collection_schema,
            }
        )

        # If this is a new AI node (not the first), update config and merge schema
        if not created:
            ai_data.ai_config = self.ai_config
            # Merge new schema fields with existing (avoid duplicates)
            existing_fields = {f['field'] for f in ai_data.schema_snapshot or []}
            new_fields = [f for f in self.ai_config.collection_schema or []
                         if f['field'] not in existing_fields]
            if new_fields:
                ai_data.schema_snapshot = (ai_data.schema_snapshot or []) + new_fields
            ai_data.save(update_fields=['ai_config', 'schema_snapshot', 'updated_at'])

        # Recalculate completion status (handles case of no required fields)
        ai_data._recalculate_completion()
        ai_data.save(update_fields=['is_complete', 'completion_percentage', 'updated_at'])

        # Store flag for context-aware prompt generation
        self._has_previous_context = previous_messages

        # Generate or use custom first message
        if self.ai_config.first_message:
            first_message = self.ai_config.first_message
            input_tokens, output_tokens = 0, 0
        else:
            first_message, input_tokens, output_tokens = self._generate_first_message()

        if not first_message:
            return False, "Failed to generate AI response"

        # Log the AI message
        AIConversationMessage.objects.create(
            session=self.session,
            ai_config=self.ai_config,
            role='assistant',
            content=first_message,
            input_tokens=input_tokens,
            output_tokens=output_tokens
        )

        # Deduct credits and log usage
        CreditManager.deduct_credits(self.user, cost, "AI first message")
        self._log_usage('chat_completion', input_tokens, output_tokens, cost)

        # Update agent stats
        if self.agent:
            self.agent.increment_stats(conversations=1, messages=1)

        # Increment turn
        ai_data.increment_turn()

        return True, first_message

    def handle_user_message(self, message_text: str, instagram_message_id: str = '') -> Dict:
        """
        Handle incoming user message during AI conversation.
        Returns dict with: success, response, goal_complete, next_action, collected_data
        """
        result = {
            'success': False,
            'response': '',
            'goal_complete': False,
            'next_action': 'continue',  # continue, complete, max_turns, error
            'collected_data': {},
            'error': None
        }

        if not self.client:
            result['error'] = "AI service not configured"
            return result

        # Check for duplicate message
        if instagram_message_id:
            exists = AIConversationMessage.objects.filter(
                session=self.session,
                instagram_message_id=instagram_message_id
            ).exists()
            if exists:
                result['error'] = "Duplicate message"
                return result

        # Check credits
        received_cost = CreditManager.get_received_message_cost()
        send_cost = CreditManager.get_message_cost()
        total_cost = received_cost + send_cost

        if not CreditManager.has_credits(self.user, total_cost):
            result['error'] = "Insufficient credits"
            result['next_action'] = 'error'
            return result

        # Get AI collected data record
        try:
            ai_data = self.session.ai_collected_data
        except AICollectedData.DoesNotExist:
            ai_data = AICollectedData.objects.create(
                session=self.session,
                ai_config=self.ai_config,
                schema_snapshot=self.ai_config.collection_schema
            )

        # Check max turns
        if ai_data.turn_count >= self.ai_config.max_turns:
            result['next_action'] = 'max_turns'
            result['collected_data'] = ai_data.data
            return result

        # Log user message
        AIConversationMessage.objects.create(
            session=self.session,
            ai_config=self.ai_config,
            role='user',
            content=message_text,
            instagram_message_id=instagram_message_id
        )

        # Deduct credit for received message
        CreditManager.deduct_credits(self.user, received_cost, "AI message received")

        # Extract data from user message
        print(f"[AI DEBUG] Extracting data. Schema: {self.ai_config.collection_schema}", flush=True)
        print(f"[AI DEBUG] Existing data: {ai_data.data}", flush=True)
        extracted_data = self._extract_data_from_message(message_text, ai_data.data)
        print(f"[AI DEBUG] Extraction result: {extracted_data}", flush=True)

        if extracted_data:
            ai_data.update_multiple_fields(extracted_data)
            print(f"[AI DEBUG] After update - ai_data.data: {ai_data.data}", flush=True)
            print(f"[AI DEBUG] fields_collected: {ai_data.fields_collected}", flush=True)
            result['collected_data'] = ai_data.data
        else:
            print(f"[AI DEBUG] No data extracted from message: {message_text[:100]}", flush=True)

        # Check if goal is complete after extraction
        print(f"[AI DEBUG] is_complete={ai_data.is_complete}, "
              f"collected={ai_data.fields_collected}, completion={ai_data.completion_percentage}%", flush=True)

        if ai_data.is_complete:
            print(f"[AI DEBUG] Goal complete! Advancing to next node", flush=True)
            result['success'] = True
            result['goal_complete'] = True
            result['next_action'] = 'complete'
            # Generate completion message
            completion_msg, _, _ = self._generate_completion_message(ai_data.data)
            result['response'] = completion_msg
            self._log_assistant_message(completion_msg, 0, 0)
            return result

        # Generate AI response
        ai_response, input_tokens, output_tokens = self._generate_response(
            message_text, ai_data.data
        )

        if not ai_response:
            result['error'] = "Failed to generate AI response"
            result['next_action'] = 'error'
            return result

        # Log AI message
        self._log_assistant_message(ai_response, input_tokens, output_tokens)

        # Deduct credits and log usage
        CreditManager.deduct_credits(self.user, send_cost, "AI message sent")
        self._log_usage('chat_completion', input_tokens, output_tokens, send_cost)

        # Update agent stats
        if self.agent:
            self.agent.increment_stats(messages=1)

        # Increment turn
        ai_data.increment_turn()

        # Check for goal complete markers in response
        if self._check_goal_complete_marker(ai_response):
            print(f"[AI DEBUG] Goal complete marker detected in response!", flush=True)
            result['goal_complete'] = True
            result['next_action'] = 'complete'

        result['success'] = True
        result['response'] = self._clean_response(ai_response)
        result['collected_data'] = ai_data.data

        return result

    def _generate_first_message(self) -> Tuple[str, int, int]:
        """Generate the first AI message"""
        system_prompt = self._build_system_prompt(is_first=True)
        user_prompt = self._build_first_message_prompt()

        try:
            response = self.client.chat.completions.create(
                model=AI_MODELS.get('chat', 'gpt-4o-mini'),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=500,
                temperature=0.7
            )
            content = response.choices[0].message.content
            input_tokens = response.usage.prompt_tokens
            output_tokens = response.usage.completion_tokens
            return content, input_tokens, output_tokens
        except Exception as e:
            logger.error(f"Error generating first message: {e}")
            return "", 0, 0

    def _generate_response(self, user_message: str, collected_data: Dict) -> Tuple[str, int, int]:
        """Generate AI response to user message"""
        # Get conversation history
        messages = self._build_conversation_messages(user_message, collected_data)

        try:
            response = self.client.chat.completions.create(
                model=AI_MODELS.get('chat', 'gpt-4o-mini'),
                messages=messages,
                max_tokens=500,
                temperature=0.7
            )
            content = response.choices[0].message.content
            input_tokens = response.usage.prompt_tokens
            output_tokens = response.usage.completion_tokens
            return content, input_tokens, output_tokens
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            return "", 0, 0

    def _generate_completion_message(self, collected_data: Dict) -> Tuple[str, int, int]:
        """Generate a completion/thank you message"""
        prompt = f"""Generate a brief, friendly message thanking the user and confirming we have their information.
Collected data: {json.dumps(collected_data)}
Keep it short (1-2 sentences). Match the agent's personality."""

        try:
            response = self.client.chat.completions.create(
                model=AI_MODELS.get('chat', 'gpt-4o-mini'),
                messages=[
                    {"role": "system", "content": self._get_agent_prompt()},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=150,
                temperature=0.7
            )
            input_tokens = response.usage.prompt_tokens
            output_tokens = response.usage.completion_tokens

            # Deduct credits and log usage for completion message
            cost = CreditManager.get_message_cost()
            CreditManager.deduct_credits(self.user, cost, "AI completion message")
            self._log_usage('chat_completion', input_tokens, output_tokens, cost)

            return response.choices[0].message.content, input_tokens, output_tokens
        except Exception:
            return "Thank you! I have all the information I need.", 0, 0

    def _build_system_prompt(self, is_first: bool = False) -> str:
        """Build the system prompt for AI"""
        parts = []

        # Agent personality
        if self.agent:
            parts.append(self.agent.get_system_prompt())
        else:
            parts.append("You are a helpful social media assistant.")

        # Goal
        parts.append(f"\n\nYOUR GOAL: {self.ai_config.goal}")

        # Data to collect
        if self.ai_config.collection_schema:
            schema_desc = self._format_schema_for_prompt()
            parts.append(f"\n\nDATA TO COLLECT:\n{schema_desc}")
            parts.append("\nCollect this information naturally through conversation. Ask one question at a time.")

        # Instructions
        parts.append("""

IMPORTANT INSTRUCTIONS:
- Keep responses short and conversational (1-3 sentences)
- Ask one question at a time
- Be natural and friendly
- When you have collected ALL required information, include [GOAL_COMPLETE] at the end of your message
- Do not ask for information the user has already provided""")

        return "".join(parts)

    def _build_first_message_prompt(self) -> str:
        """Build prompt for generating first message"""
        context_info = ""
        if self.session.context_data:
            # Filter out internal flags from context
            visible_context = {k: v for k, v in self.session.context_data.items()
                              if not k.startswith('_')}
            if visible_context:
                context_info = f"\nData already collected: {json.dumps(visible_context)}"

        # Check if this is a continuation of previous AI conversation
        has_history = getattr(self, '_has_previous_context', False)

        if has_history:
            return f"""Continue the conversation with a new goal.
{context_info}
Your NEW goal: {self.ai_config.goal}
Acknowledge what was discussed before and smoothly transition to the new topic.
Keep it brief and natural. Don't repeat information already collected."""
        else:
            return f"""Generate your first message to start the conversation.
{context_info}
Remember your goal: {self.ai_config.goal}
Keep it brief and engaging. Don't ask too many questions at once."""

    def _build_conversation_messages(self, current_message: str, collected_data: Dict) -> List[Dict]:
        """Build messages array for OpenAI API"""
        messages = [{"role": "system", "content": self._build_system_prompt()}]

        # Add knowledge context if available
        knowledge_context = self._get_knowledge_context(current_message)
        if knowledge_context:
            messages.append({
                "role": "system",
                "content": f"RELEVANT KNOWLEDGE:\n{knowledge_context}"
            })

        # Add collected data context
        if collected_data:
            messages.append({
                "role": "system",
                "content": f"DATA COLLECTED SO FAR: {json.dumps(collected_data)}"
            })

        # Add conversation history
        history = AIConversationMessage.objects.filter(
            session=self.session
        ).order_by('created_at')[:AI_CONVERSATION_SETTINGS.get('max_context_messages', 20)]

        for msg in history:
            messages.append({"role": msg.role, "content": msg.content})

        # Add current user message
        messages.append({"role": "user", "content": current_message})

        return messages

    def _get_knowledge_context(self, query: str) -> str:
        """Retrieve relevant knowledge for the query"""
        if not self.knowledge_retriever:
            return ""

        knowledge_bases = self.ai_config.get_all_knowledge_bases()
        if not knowledge_bases:
            return ""

        chunks = self.knowledge_retriever.retrieve_relevant_chunks(query, knowledge_bases)
        if not chunks:
            return ""

        # Deduct RAG query cost and log usage
        rag_cost = AI_CREDITS.get('RAG_QUERY_COST', 0.1)
        CreditManager.deduct_credits(self.user, rag_cost, "RAG query")
        self._log_usage('rag_query', 0, 0, rag_cost)

        context_parts = []
        for chunk in chunks:
            context_parts.append(f"[{chunk['source']}]: {chunk['content']}")

        return "\n\n".join(context_parts)

    def _extract_data_from_message(self, message: str, existing_data: Dict) -> Dict:
        """Extract structured data from user message using LLM"""
        if not self.ai_config.collection_schema:
            print("[AI DEBUG] No collection_schema configured, skipping extraction", flush=True)
            return {}

        schema = self.ai_config.collection_schema
        missing_fields = [f for f in schema if not existing_data.get(f['field'])]
        print(f"[AI DEBUG] Schema has {len(schema)} fields, {len(missing_fields)} missing: "
              f"{[f['field'] for f in missing_fields]}", flush=True)

        if not missing_fields:
            print("[AI DEBUG] All fields already collected, skipping extraction", flush=True)
            return {}

        extraction_prompt = f"""Extract the following information from the user's message if present.
Return a JSON object with only the fields that were found in the message.

Fields to look for:
{json.dumps(missing_fields, indent=2)}

User message: "{message}"

Return ONLY a valid JSON object. If no fields found, return {{}}.
Example: {{"email": "user@example.com", "budget": "50L-1Cr"}}"""

        try:
            response = self.client.chat.completions.create(
                model=AI_MODELS.get('chat', 'gpt-4o-mini'),
                messages=[
                    {"role": "system", "content": "You extract structured data from text. Return only valid JSON."},
                    {"role": "user", "content": extraction_prompt}
                ],
                max_tokens=200,
                temperature=0
            )
            content = response.choices[0].message.content.strip()

            # Log usage and deduct credits for data extraction
            input_tokens = response.usage.prompt_tokens
            output_tokens = response.usage.completion_tokens
            extraction_cost = AI_CREDITS.get('DATA_EXTRACTION_COST', 0.2)
            CreditManager.deduct_credits(self.user, extraction_cost, "Data extraction")
            self._log_usage('data_extraction', input_tokens, output_tokens, extraction_cost)

            # Clean up response
            if content.startswith('```'):
                content = content.split('\n', 1)[1].rsplit('```', 1)[0]

            extracted = json.loads(content)
            if extracted:
                print(f"[AI DEBUG] Extracted data from message: {extracted}", flush=True)
            return extracted
        except json.JSONDecodeError as e:
            print(f"[AI DEBUG] JSON parse error: {e}. Raw content: {content[:200]}", flush=True)
            return {}
        except Exception as e:
            print(f"[AI DEBUG] Error extracting data: {e}", flush=True)
            return {}

    def _format_schema_for_prompt(self) -> str:
        """Format collection schema for prompt"""
        lines = []
        for field in self.ai_config.collection_schema:
            required = "(required)" if field.get('required') else "(optional)"
            field_type = field.get('type', 'text')
            label = field.get('label', field['field'])
            line = f"- {label} [{field_type}] {required}"
            if field.get('options'):
                line += f" Options: {', '.join(field['options'])}"
            lines.append(line)
        return "\n".join(lines)

    def _get_agent_prompt(self) -> str:
        """Get agent system prompt"""
        if self.agent:
            return self.agent.get_system_prompt()
        return "You are a helpful assistant."

    def _check_goal_complete_marker(self, response: str) -> bool:
        """Check if response contains goal complete marker"""
        for marker in GOAL_COMPLETE_MARKERS:
            if marker in response:
                return True
        return False

    def _clean_response(self, response: str) -> str:
        """Remove goal complete markers from response"""
        for marker in GOAL_COMPLETE_MARKERS:
            response = response.replace(marker, '').strip()
        return response

    def _log_assistant_message(self, content: str, input_tokens: int, output_tokens: int):
        """Log an assistant message"""
        AIConversationMessage.objects.create(
            session=self.session,
            ai_config=self.ai_config,
            role='assistant',
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens
        )

    def _log_usage(self, usage_type: str, input_tokens: int, output_tokens: int, credits: float):
        """Log AI usage"""
        model = AI_MODELS.get('chat', 'gpt-4o-mini')
        pricing = MODEL_PRICING.get(model, {'input': 0, 'output': 0})
        cost_usd = (input_tokens * pricing['input'] + output_tokens * pricing['output']) / 1_000_000

        AIUsageLog.log_usage(
            user=self.user,
            session=self.session,
            agent=self.agent,
            usage_type=usage_type,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            credits_charged=credits
        )


# =============================================================================
# AI Node Executor (Called from flow_engine.py)
# =============================================================================

class AINodeExecutor:
    """
    Executes AI node within flow.
    This is the interface called by flow_engine.py
    """

    @staticmethod
    def execute_ai_node(session: FlowSession, node: FlowNode) -> Dict:
        """
        Execute AI node - called when flow enters an AI node.
        Returns dict with: success, message, status
        """
        result = {
            'success': False,
            'message': '',
            'status': 'error',
            'should_wait': True  # AI nodes always wait for user reply
        }

        # Get AI config
        try:
            ai_config = node.ai_config
        except AINodeConfig.DoesNotExist:
            result['message'] = "AI node not configured"
            return result

        # Create handler and initialize
        handler = AIConversationHandler(session, ai_config)
        success, message = handler.initialize_ai_conversation()

        result['success'] = success
        result['message'] = message
        result['status'] = AI_SESSION_STATUS['AI_WAITING'] if success else AI_SESSION_STATUS['AI_ERROR']

        return result

    @staticmethod
    def handle_ai_message(session: FlowSession, message_text: str, instagram_message_id: str = '') -> Dict:
        """
        Handle user message during AI conversation.
        Returns dict with: success, response, next_node_id, should_complete_flow
        """
        print(f"[AI DEBUG] handle_ai_message called for session {session.id}", flush=True)

        result = {
            'success': False,
            'response': '',
            'next_node_id': None,
            'should_complete_flow': False,
            'should_continue_ai': True,
            'collected_data': {}
        }

        # Get current AI config
        current_node = session.current_node
        print(f"[AI DEBUG] current_node: {current_node}, type: {current_node.node_type if current_node else 'None'}", flush=True)

        if not current_node or current_node.node_type != 'ai_conversation':
            result['error'] = "Session not in AI conversation"
            print(f"[AI DEBUG] ERROR: {result['error']}", flush=True)
            return result

        try:
            ai_config = current_node.ai_config
            print(f"[AI DEBUG] ai_config loaded: {ai_config.id}", flush=True)
        except AINodeConfig.DoesNotExist:
            result['error'] = "AI node not configured"
            print(f"[AI DEBUG] ERROR: {result['error']}", flush=True)
            return result

        # Create handler and process message
        try:
            print(f"[AI DEBUG] Creating handler and processing message...", flush=True)
            handler = AIConversationHandler(session, ai_config)
            ai_result = handler.handle_user_message(message_text, instagram_message_id)
            print(f"[AI DEBUG] ai_result: success={ai_result.get('success')}, "
                  f"next_action={ai_result.get('next_action')}, error={ai_result.get('error')}", flush=True)
        except Exception as e:
            result['error'] = f"Handler error: {str(e)}"
            print(f"[AI DEBUG] EXCEPTION in handler: {e}", flush=True)
            import traceback
            traceback.print_exc()
            return result

        result['success'] = ai_result['success']
        result['response'] = ai_result['response']
        result['collected_data'] = ai_result['collected_data']

        # Determine next action
        if ai_result['next_action'] == 'complete':
            result['should_continue_ai'] = False
            # Determine next node based on config
            if ai_config.on_goal_complete == 'next_node':
                result['next_node_id'] = current_node.next_node_id
            elif ai_config.on_goal_complete == 'specific_node':
                result['next_node_id'] = ai_config.goal_complete_node_id
            elif ai_config.on_goal_complete == 'end_flow':
                result['should_complete_flow'] = True

            # Update session context with collected data
            session.context_data.update(ai_result['collected_data'])
            session.save(update_fields=['context_data', 'updated_at'])

        elif ai_result['next_action'] == 'max_turns':
            result['should_continue_ai'] = False
            if ai_config.on_max_turns == 'next_node':
                result['next_node_id'] = current_node.next_node_id
            elif ai_config.on_max_turns == 'specific_node':
                result['next_node_id'] = ai_config.max_turns_node_id
            else:
                result['should_complete_flow'] = True

            # Still save collected data
            session.context_data.update(ai_result['collected_data'])
            session.save(update_fields=['context_data', 'updated_at'])

        elif ai_result['next_action'] == 'error':
            result['should_continue_ai'] = False
            if ai_config.on_failure == 'specific_node':
                result['next_node_id'] = ai_config.failure_node_id
            else:
                result['should_complete_flow'] = True

        return result

    @staticmethod
    def is_ai_node(node: FlowNode) -> bool:
        """Check if node is an AI conversation node"""
        return node.node_type == 'ai_conversation'

    @staticmethod
    def is_session_in_ai_conversation(session: FlowSession) -> bool:
        """Check if session is currently in an AI conversation"""
        if not session.current_node:
            return False
        return session.current_node.node_type == 'ai_conversation' and \
               session.status in [AI_SESSION_STATUS['AI_ACTIVE'], AI_SESSION_STATUS['AI_WAITING'], 'waiting_reply']
