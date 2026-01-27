#pylint: disable=all
"""
AI Social Agent Views

Views for managing:
- Social Agents (create, edit, delete, list)
- Knowledge Bases (create, add items, delete)
- AI Node Configuration
- AI Collected Data display
"""

import json
import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View
from django.http import JsonResponse, HttpResponse
from django.core.paginator import Paginator
from django.db.models import Sum, Count
from django.utils import timezone

from .models import (
    SocialAgent, KnowledgeBase, KnowledgeItem, KnowledgeChunk,
    AINodeConfig, AIConversationMessage, AIUsageLog, AICollectedData,
    FlowNode, FlowSession, DMFlow
)
from .knowledge_service import KnowledgeService
from .constants import SUPPORTED_DOCUMENT_TYPES, AI_CREDITS
from core.models import Configuration
from core.subscription_utils import check_feature_access

logger = logging.getLogger(__name__)


# =============================================================================
# Feature Access Mixin for AI Features
# =============================================================================

class AIFeatureMixin:
    """Mixin to check if user has AI feature access"""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')

        # Staff users bypass all checks
        if request.user.is_staff:
            return super().dispatch(request, *args, **kwargs)

        # Check for AI feature access
        can_access, message, _ = check_feature_access(request.user, 'ai_social_agent')
        if not can_access:
            messages.error(request, 'You need to upgrade your plan to access AI Social Agents.')
            return redirect('subscription')

        return super().dispatch(request, *args, **kwargs)


# =============================================================================
# Social Agent Views
# =============================================================================

class AgentListView(LoginRequiredMixin, AIFeatureMixin, View):
    """List all social agents for the user"""

    def get(self, request):
        agents = SocialAgent.objects.filter(user=request.user).order_by('-created_at')

        # Get stats for each agent
        agent_data = []
        for agent in agents:
            kb_count = agent.knowledge_bases.count()
            total_chunks = KnowledgeChunk.objects.filter(
                knowledge_item__knowledge_base__agent=agent
            ).count()
            agent_data.append({
                'agent': agent,
                'kb_count': kb_count,
                'total_chunks': total_chunks,
            })

        context = {
            'agent_data': agent_data,
            'page_title': 'Social Agents',
        }
        return render(request, 'instagram/ai/agent_list.html', context)


class AgentCreateView(LoginRequiredMixin, AIFeatureMixin, View):
    """Create a new social agent"""

    def get(self, request):
        context = {
            'page_title': 'Create Agent',
            'tone_choices': ['friendly', 'professional', 'casual', 'formal', 'enthusiastic'],
        }
        return render(request, 'instagram/ai/agent_form.html', context)

    def post(self, request):
        name = request.POST.get('name', '').strip()
        personality = request.POST.get('personality', '').strip()
        tone = request.POST.get('tone', 'friendly')
        language_style = request.POST.get('language_style', '').strip()
        boundaries = request.POST.get('boundaries', '').strip()
        custom_system_prompt = request.POST.get('custom_system_prompt', '').strip()

        # Validation
        if not name:
            messages.error(request, 'Agent name is required.')
            return redirect('ai_agent_create')

        if not personality:
            messages.error(request, 'Agent personality is required.')
            return redirect('ai_agent_create')

        # Create agent
        agent = SocialAgent.objects.create(
            user=request.user,
            name=name,
            personality=personality,
            tone=tone,
            language_style=language_style,
            boundaries=boundaries,
            custom_system_prompt=custom_system_prompt,
        )

        # Create default knowledge base for the agent
        KnowledgeBase.objects.create(
            user=request.user,
            agent=agent,
            name=f"{name} - Knowledge Base",
            description=f"Default knowledge base for {name}",
        )

        messages.success(request, f'Agent "{name}" created successfully!')
        return redirect('ai_agent_detail', agent_id=agent.id)


class AgentDetailView(LoginRequiredMixin, AIFeatureMixin, View):
    """View agent details and manage knowledge bases"""

    def get(self, request, agent_id):
        agent = get_object_or_404(SocialAgent, id=agent_id, user=request.user)
        knowledge_bases = agent.knowledge_bases.all()

        # Get usage stats
        usage_stats = AIUsageLog.objects.filter(agent=agent).aggregate(
            total_messages=Count('id'),
            total_tokens=Sum('total_tokens'),
            total_credits=Sum('credits_charged'),
        )

        context = {
            'agent': agent,
            'knowledge_bases': knowledge_bases,
            'usage_stats': usage_stats,
            'page_title': agent.name,
            'system_prompt_preview': agent.get_system_prompt()[:500] + '...' if len(agent.get_system_prompt()) > 500 else agent.get_system_prompt(),
        }
        return render(request, 'instagram/ai/agent_detail.html', context)


class AgentEditView(LoginRequiredMixin, AIFeatureMixin, View):
    """Edit a social agent"""

    def get(self, request, agent_id):
        agent = get_object_or_404(SocialAgent, id=agent_id, user=request.user)
        context = {
            'agent': agent,
            'page_title': f'Edit {agent.name}',
            'tone_choices': ['friendly', 'professional', 'casual', 'formal', 'enthusiastic'],
        }
        return render(request, 'instagram/ai/agent_form.html', context)

    def post(self, request, agent_id):
        agent = get_object_or_404(SocialAgent, id=agent_id, user=request.user)

        agent.name = request.POST.get('name', agent.name).strip()
        agent.personality = request.POST.get('personality', agent.personality).strip()
        agent.tone = request.POST.get('tone', agent.tone)
        agent.language_style = request.POST.get('language_style', '').strip()
        agent.boundaries = request.POST.get('boundaries', '').strip()
        agent.custom_system_prompt = request.POST.get('custom_system_prompt', '').strip()
        agent.is_active = request.POST.get('is_active') == 'on'

        agent.save()

        messages.success(request, f'Agent "{agent.name}" updated successfully!')
        return redirect('ai_agent_detail', agent_id=agent.id)


class AgentDeleteView(LoginRequiredMixin, AIFeatureMixin, View):
    """Delete a social agent"""

    def post(self, request, agent_id):
        agent = get_object_or_404(SocialAgent, id=agent_id, user=request.user)
        name = agent.name

        # Delete associated knowledge bases and their S3 files
        for kb in agent.knowledge_bases.all():
            service = KnowledgeService(request.user)
            service.delete_knowledge_base(kb)

        agent.delete()
        messages.success(request, f'Agent "{name}" deleted successfully!')
        return redirect('ai_agent_list')


# =============================================================================
# Knowledge Base Views
# =============================================================================

class KnowledgeBaseDetailView(LoginRequiredMixin, AIFeatureMixin, View):
    """View knowledge base details and items"""

    def get(self, request, kb_id):
        kb = get_object_or_404(KnowledgeBase, id=kb_id, user=request.user)
        items = kb.items.all().order_by('-created_at')

        context = {
            'kb': kb,
            'items': items,
            'page_title': kb.name,
            'supported_types': SUPPORTED_DOCUMENT_TYPES,
        }
        return render(request, 'instagram/ai/knowledge_base_detail.html', context)


class KnowledgeBaseCreateView(LoginRequiredMixin, AIFeatureMixin, View):
    """Create a new knowledge base"""

    def get(self, request):
        agents = SocialAgent.objects.filter(user=request.user, is_active=True)
        context = {
            'agents': agents,
            'page_title': 'Create Knowledge Base',
        }
        return render(request, 'instagram/ai/knowledge_base_form.html', context)

    def post(self, request):
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        agent_id = request.POST.get('agent_id')

        if not name:
            messages.error(request, 'Knowledge base name is required.')
            return redirect('ai_kb_create')

        agent = None
        if agent_id:
            agent = get_object_or_404(SocialAgent, id=agent_id, user=request.user)

        kb = KnowledgeBase.objects.create(
            user=request.user,
            agent=agent,
            name=name,
            description=description,
        )

        messages.success(request, f'Knowledge base "{name}" created successfully!')
        return redirect('ai_kb_detail', kb_id=kb.id)


class KnowledgeItemAddTextView(LoginRequiredMixin, AIFeatureMixin, View):
    """Add text content to knowledge base"""

    def post(self, request, kb_id):
        kb = get_object_or_404(KnowledgeBase, id=kb_id, user=request.user)

        title = request.POST.get('title', '').strip()
        content = request.POST.get('content', '').strip()

        if not title or not content:
            messages.error(request, 'Title and content are required.')
            return redirect('ai_kb_detail', kb_id=kb.id)

        # Check credits
        profile = request.user.profile
        estimated_cost = AI_CREDITS.get('EMBEDDING_COST_PER_PAGE', 0.5)
        if not profile.has_credits(estimated_cost):
            messages.error(request, 'Insufficient credits to process this content.')
            return redirect('ai_kb_detail', kb_id=kb.id)

        service = KnowledgeService(request.user)
        item = service.add_text_item(kb, title, content, process_now=True)

        if item.processing_status == 'completed':
            messages.success(request, f'Text "{title}" added and processed successfully!')
        else:
            messages.warning(request, f'Text "{title}" added but processing failed: {item.processing_error}')

        return redirect('ai_kb_detail', kb_id=kb.id)


class KnowledgeItemUploadView(LoginRequiredMixin, AIFeatureMixin, View):
    """Upload document to knowledge base"""

    def post(self, request, kb_id):
        kb = get_object_or_404(KnowledgeBase, id=kb_id, user=request.user)

        uploaded_file = request.FILES.get('document')
        if not uploaded_file:
            messages.error(request, 'Please select a file to upload.')
            return redirect('ai_kb_detail', kb_id=kb.id)

        # Determine file type
        file_ext = uploaded_file.name.lower().split('.')[-1]
        item_type = None
        for type_key, type_config in SUPPORTED_DOCUMENT_TYPES.items():
            if f'.{file_ext}' in type_config['extensions']:
                item_type = type_key
                break

        if not item_type:
            messages.error(request, f'Unsupported file type: .{file_ext}')
            return redirect('ai_kb_detail', kb_id=kb.id)

        # Check credits
        profile = request.user.profile
        pages_estimate = uploaded_file.size / 3000  # Rough estimate
        estimated_cost = pages_estimate * AI_CREDITS.get('EMBEDDING_COST_PER_PAGE', 0.5)
        if not profile.has_credits(estimated_cost):
            messages.error(request, 'Insufficient credits to process this document.')
            return redirect('ai_kb_detail', kb_id=kb.id)

        try:
            service = KnowledgeService(request.user)
            item, error = service.add_document_item(kb, uploaded_file, item_type, process_now=True)

            if error:
                logger.error(f"Document upload failed for user {request.user.id}: {error}")
                messages.error(request, f'Failed to upload document: {error}')
            elif item.processing_status == 'completed':
                messages.success(request, f'Document "{uploaded_file.name}" uploaded and processed successfully!')
            else:
                logger.warning(f"Document processing failed: {item.processing_error}")
                messages.warning(request, f'Document uploaded but processing failed: {item.processing_error}')
        except Exception as e:
            logger.exception(f"Unexpected error uploading document for user {request.user.id}")
            messages.error(request, f'An unexpected error occurred: {str(e)}')

        return redirect('ai_kb_detail', kb_id=kb.id)


class KnowledgeItemDeleteView(LoginRequiredMixin, AIFeatureMixin, View):
    """Delete a knowledge item"""

    def post(self, request, item_id):
        item = get_object_or_404(KnowledgeItem, id=item_id, knowledge_base__user=request.user)
        kb_id = item.knowledge_base_id
        title = item.title or item.file_name

        service = KnowledgeService(request.user)
        service.delete_item(item)

        messages.success(request, f'Item "{title}" deleted successfully!')
        return redirect('ai_kb_detail', kb_id=kb_id)


class KnowledgeItemReprocessView(LoginRequiredMixin, AIFeatureMixin, View):
    """Reprocess a knowledge item"""

    def post(self, request, item_id):
        item = get_object_or_404(KnowledgeItem, id=item_id, knowledge_base__user=request.user)

        service = KnowledgeService(request.user)
        success = service.reprocess_item(item)

        if success:
            messages.success(request, f'Item reprocessed successfully!')
        else:
            messages.error(request, f'Reprocessing failed: {item.processing_error}')

        return redirect('ai_kb_detail', kb_id=item.knowledge_base_id)


class KnowledgeBaseDeleteView(LoginRequiredMixin, AIFeatureMixin, View):
    """Delete a knowledge base"""

    def post(self, request, kb_id):
        kb = get_object_or_404(KnowledgeBase, id=kb_id, user=request.user)
        name = kb.name
        agent_id = kb.agent_id

        service = KnowledgeService(request.user)
        service.delete_knowledge_base(kb)

        messages.success(request, f'Knowledge base "{name}" deleted successfully!')

        if agent_id:
            return redirect('ai_agent_detail', agent_id=agent_id)
        return redirect('ai_agent_list')


# =============================================================================
# AI Node Configuration Views
# =============================================================================

class AINodeConfigView(LoginRequiredMixin, AIFeatureMixin, View):
    """Configure AI node for a flow"""

    def get(self, request, node_id):
        node = get_object_or_404(FlowNode, id=node_id, flow__user=request.user)

        if node.node_type != 'ai_conversation':
            messages.error(request, 'This node is not an AI conversation node.')
            return redirect('flow_edit', pk=node.flow_id)

        # Get or create AI config
        ai_config, created = AINodeConfig.objects.get_or_create(
            flow_node=node,
            defaults={'goal': '', 'collection_schema': []}
        )

        agents = SocialAgent.objects.filter(user=request.user, is_active=True)
        knowledge_bases = KnowledgeBase.objects.filter(user=request.user, is_active=True)

        # Get other nodes in the flow for branching
        flow_nodes = FlowNode.objects.filter(flow=node.flow).exclude(id=node.id)

        context = {
            'node': node,
            'ai_config': ai_config,
            'agents': agents,
            'knowledge_bases': knowledge_bases,
            'flow_nodes': flow_nodes,
            'page_title': f'Configure AI Node - {node.flow.title}',
            'field_types': ['text', 'email', 'phone', 'number', 'select'],
        }
        return render(request, 'instagram/ai/ai_node_config.html', context)

    def post(self, request, node_id):
        node = get_object_or_404(FlowNode, id=node_id, flow__user=request.user)

        ai_config, _ = AINodeConfig.objects.get_or_create(
            flow_node=node,
            defaults={'goal': '', 'collection_schema': []}
        )

        # Update basic settings
        agent_id = request.POST.get('agent_id')
        if agent_id:
            ai_config.agent = get_object_or_404(SocialAgent, id=agent_id, user=request.user)
        else:
            ai_config.agent = None

        ai_config.goal = request.POST.get('goal', '').strip()
        ai_config.first_message = request.POST.get('first_message', '').strip()
        ai_config.max_turns = int(request.POST.get('max_turns', 10))
        ai_config.timeout_minutes = int(request.POST.get('timeout_minutes', 60))

        # Flow connection is handled in the flow editor via next_node
        # Goal completion, max turns, and failure all use the flow's next_node connection

        # Parse collection schema from form
        schema = []
        field_names = request.POST.getlist('field_name[]')
        field_types = request.POST.getlist('field_type[]')
        field_labels = request.POST.getlist('field_label[]')
        field_required = request.POST.getlist('field_required[]')
        field_options = request.POST.getlist('field_options[]')

        for i, name in enumerate(field_names):
            if name.strip():
                field = {
                    'field': name.strip(),
                    'type': field_types[i] if i < len(field_types) else 'text',
                    'label': field_labels[i] if i < len(field_labels) else name.strip(),
                    'required': str(i) in field_required,
                }
                if field['type'] == 'select' and i < len(field_options):
                    options = [o.strip() for o in field_options[i].split(',') if o.strip()]
                    field['options'] = options
                schema.append(field)

        ai_config.collection_schema = schema

        ai_config.save()

        messages.success(request, 'AI node configuration saved successfully!')
        return redirect('flow_edit', pk=node.flow_id)


# =============================================================================
# AI Collected Data Views
# =============================================================================

class AICollectedDataListView(LoginRequiredMixin, AIFeatureMixin, View):
    """List all AI collected data for user's flows"""

    def get(self, request):
        # Get flow filter
        flow_id = request.GET.get('flow')
        agent_id = request.GET.get('agent')
        status = request.GET.get('status')

        # Base queryset
        collected_data = AICollectedData.objects.filter(
            session__flow__user=request.user
        ).select_related(
            'session', 'session__flow', 'ai_config', 'ai_config__agent'
        ).order_by('-created_at')

        # Apply filters
        if flow_id:
            collected_data = collected_data.filter(session__flow_id=flow_id)
        if agent_id:
            collected_data = collected_data.filter(ai_config__agent_id=agent_id)
        if status == 'complete':
            collected_data = collected_data.filter(is_complete=True)
        elif status == 'incomplete':
            collected_data = collected_data.filter(is_complete=False)

        # Pagination
        paginator = Paginator(collected_data, 20)
        page = request.GET.get('page', 1)
        collected_data = paginator.get_page(page)

        # Get filter options
        flows = DMFlow.objects.filter(user=request.user)
        agents = SocialAgent.objects.filter(user=request.user)

        # Build dynamic columns from all schemas
        all_fields = set()
        for data in collected_data:
            if data.schema_snapshot:
                for field in data.schema_snapshot:
                    all_fields.add(field.get('field', ''))

        context = {
            'collected_data': collected_data,
            'flows': flows,
            'agents': agents,
            'all_fields': sorted(all_fields),
            'current_flow': flow_id,
            'current_agent': agent_id,
            'current_status': status,
            'page_title': 'AI Collected Data',
        }
        return render(request, 'instagram/ai/collected_data_list.html', context)


class AICollectedDataDetailView(LoginRequiredMixin, AIFeatureMixin, View):
    """View detailed AI collected data for a session"""

    def get(self, request, session_id):
        session = get_object_or_404(FlowSession, id=session_id, flow__user=request.user)

        try:
            collected_data = session.ai_collected_data
        except AICollectedData.DoesNotExist:
            collected_data = None

        # Get conversation messages
        messages_list = AIConversationMessage.objects.filter(
            session=session
        ).order_by('created_at')

        # Get usage logs
        usage_logs = AIUsageLog.objects.filter(session=session).order_by('created_at')
        total_credits = usage_logs.aggregate(total=Sum('credits_charged'))['total'] or 0

        context = {
            'session': session,
            'collected_data': collected_data,
            'messages': messages_list,
            'usage_logs': usage_logs,
            'total_credits': total_credits,
            'page_title': f'AI Session - @{session.instagram_username}',
        }
        return render(request, 'instagram/ai/collected_data_detail.html', context)


class AICollectedDataExportView(LoginRequiredMixin, AIFeatureMixin, View):
    """Export AI collected data as CSV"""

    def get(self, request):
        import csv

        flow_id = request.GET.get('flow')

        # Get data
        collected_data = AICollectedData.objects.filter(
            session__flow__user=request.user,
            is_complete=True
        ).select_related('session', 'session__flow')

        if flow_id:
            collected_data = collected_data.filter(session__flow_id=flow_id)

        # Build response
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="ai_collected_data.csv"'

        # Collect all fields
        all_fields = set(['instagram_username', 'flow_name', 'completion_percentage', 'created_at'])
        for data in collected_data:
            if data.data:
                all_fields.update(data.data.keys())

        all_fields = sorted(all_fields)

        writer = csv.writer(response)
        writer.writerow(all_fields)

        for data in collected_data:
            row = []
            for field in all_fields:
                if field == 'instagram_username':
                    row.append(data.session.instagram_username)
                elif field == 'flow_name':
                    row.append(data.session.flow.title)
                elif field == 'completion_percentage':
                    row.append(data.completion_percentage)
                elif field == 'created_at':
                    row.append(data.created_at.strftime('%Y-%m-%d %H:%M'))
                else:
                    row.append(data.data.get(field, ''))
            writer.writerow(row)

        return response


# =============================================================================
# AI Usage Stats View
# =============================================================================

class AIUsageStatsView(LoginRequiredMixin, AIFeatureMixin, View):
    """View AI usage statistics"""

    def get(self, request):
        # Overall stats
        total_stats = AIUsageLog.objects.filter(user=request.user).aggregate(
            total_calls=Count('id'),
            total_tokens=Sum('total_tokens'),
            total_credits=Sum('credits_charged'),
            total_cost_usd=Sum('cost_usd'),
        )

        # Stats by agent
        agent_stats = AIUsageLog.objects.filter(
            user=request.user,
            agent__isnull=False
        ).values('agent__name').annotate(
            calls=Count('id'),
            tokens=Sum('total_tokens'),
            credits=Sum('credits_charged'),
        ).order_by('-credits')

        # Stats by usage type
        type_stats = AIUsageLog.objects.filter(
            user=request.user
        ).values('usage_type').annotate(
            calls=Count('id'),
            tokens=Sum('total_tokens'),
            credits=Sum('credits_charged'),
        ).order_by('-credits')

        # Recent usage (last 30 days)
        thirty_days_ago = timezone.now() - timezone.timedelta(days=30)
        daily_stats = AIUsageLog.objects.filter(
            user=request.user,
            created_at__gte=thirty_days_ago
        ).extra(
            select={'day': 'date(created_at)'}
        ).values('day').annotate(
            credits=Sum('credits_charged'),
            calls=Count('id'),
        ).order_by('day')

        # Current credits balance
        profile = request.user.profile

        context = {
            'total_stats': total_stats,
            'agent_stats': agent_stats,
            'type_stats': type_stats,
            'daily_stats': list(daily_stats),
            'credits_balance': profile.credits,
            'page_title': 'AI Usage Statistics',
        }
        return render(request, 'instagram/ai/usage_stats.html', context)


# =============================================================================
# API Endpoints for AJAX
# =============================================================================

class AgentPreviewAPIView(LoginRequiredMixin, View):
    """API to preview agent system prompt"""

    def get(self, request, agent_id):
        agent = get_object_or_404(SocialAgent, id=agent_id, user=request.user)
        return JsonResponse({
            'name': agent.name,
            'system_prompt': agent.get_system_prompt(),
            'personality': agent.personality,
            'tone': agent.tone,
        })


class KnowledgeSearchAPIView(LoginRequiredMixin, View):
    """API to search knowledge base"""

    def post(self, request, kb_id):
        kb = get_object_or_404(KnowledgeBase, id=kb_id, user=request.user)

        try:
            data = json.loads(request.body)
            query = data.get('query', '')
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        if not query:
            return JsonResponse({'error': 'Query required'}, status=400)

        # Search using knowledge retriever
        from .ai_engine import KnowledgeRetriever, get_openai_client

        client = get_openai_client()
        if not client:
            return JsonResponse({'error': 'AI service not configured'}, status=500)

        retriever = KnowledgeRetriever(client)
        results = retriever.retrieve_relevant_chunks(query, [kb], top_k=5)

        return JsonResponse({
            'results': results
        })


class AINodeSchemaAPIView(LoginRequiredMixin, View):
    """API to get/update AI node schema"""

    def get(self, request, node_id):
        node = get_object_or_404(FlowNode, id=node_id, flow__user=request.user)

        try:
            ai_config = node.ai_config
            return JsonResponse({
                'schema': ai_config.collection_schema,
                'goal': ai_config.goal,
            })
        except AINodeConfig.DoesNotExist:
            return JsonResponse({
                'schema': [],
                'goal': '',
            })
