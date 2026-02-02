from django.db import models
from django.db.models import F
from django.conf import settings


class InstagramAccount(models.Model):
    """Stores Instagram Business account connection for a user"""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='instagram_account'
    )

    # Instagram Business Account Details
    instagram_user_id = models.CharField(max_length=255, blank=True, null=True)
    username = models.CharField(max_length=255, blank=True, null=True)
    access_token = models.TextField(blank=True, null=True)
    token_expires_at = models.DateTimeField(blank=True, null=True)

    # Additional data stored as JSON
    instagram_data = models.JSONField(default=dict, blank=True)

    # Status
    is_active = models.BooleanField(default=True)

    # Lifetime statistics (persists even when flows are deleted)
    total_dms_sent = models.PositiveIntegerField(default=0)
    total_comments_replied = models.PositiveIntegerField(default=0)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"@{self.username}" if self.username else f"User {self.user_id}"

    @property
    def is_connected(self):
        """Check if Instagram is connected and token is valid"""
        from django.utils import timezone
        if not self.access_token:
            return False
        if self.token_expires_at and self.token_expires_at < timezone.now():
            return False
        return True

    def increment_dms_sent(self, count=1):
        """Increment DMs sent counter atomically"""
        InstagramAccount.objects.filter(pk=self.pk).update(
            total_dms_sent=F('total_dms_sent') + count
        )

    def increment_comments_replied(self, count=1):
        """Increment comments replied counter atomically"""
        InstagramAccount.objects.filter(pk=self.pk).update(
            total_comments_replied=F('total_comments_replied') + count
        )

    class Meta:
        verbose_name = "Instagram Account"
        verbose_name_plural = "Instagram Accounts"


class APICallLog(models.Model):
    """
    Logs Instagram API calls for rate limiting tracking.
    Used to count messages sent in rolling time windows.
    """
    CALL_TYPE_CHOICES = [
        ('dm', 'Direct Message'),
        ('comment_reply', 'Comment Reply'),
    ]

    account = models.ForeignKey(
        InstagramAccount,
        on_delete=models.CASCADE,
        related_name='api_call_logs'
    )
    call_type = models.CharField(max_length=20, choices=CALL_TYPE_CHOICES)
    endpoint = models.CharField(max_length=255)
    recipient_id = models.CharField(max_length=255, blank=True)
    success = models.BooleanField(default=True)
    sent_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "API Call Log"
        verbose_name_plural = "API Call Logs"
        indexes = [
            models.Index(fields=['account', 'sent_at']),
            models.Index(fields=['account', 'call_type', 'sent_at']),
        ]

    @classmethod
    def get_calls_last_hour(cls, account, call_type=None):
        """Count API calls in the last hour for an account."""
        from django.utils import timezone
        from datetime import timedelta
        one_hour_ago = timezone.now() - timedelta(hours=1)
        qs = cls.objects.filter(account=account, sent_at__gte=one_hour_ago, success=True)
        if call_type:
            qs = qs.filter(call_type=call_type)
        return qs.count()

    @classmethod
    def log_call(cls, account, call_type, endpoint, recipient_id='', success=True):
        """Log an API call and update account counters."""
        log = cls.objects.create(
            account=account,
            call_type=call_type,
            endpoint=endpoint,
            recipient_id=recipient_id,
            success=success
        )
        # Update account-level counters for successful calls
        if success:
            if call_type == 'dm':
                account.increment_dms_sent()
            elif call_type == 'comment_reply':
                account.increment_comments_replied()
        return log


# =============================================================================
# DM Flow Builder Models
# =============================================================================

class DMFlow(models.Model):
    """A DM automation flow with multiple steps"""
    TRIGGER_TYPE_CHOICES = [
        ('comment_keyword', 'Comment with Keyword'),
        ('comment_any', 'Any Comment'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='dm_flows'
    )

    # Flow details
    title = models.CharField(max_length=100, help_text="Name for this flow")
    description = models.TextField(blank=True, help_text="Optional description")

    # Trigger configuration
    trigger_type = models.CharField(
        max_length=20,
        choices=TRIGGER_TYPE_CHOICES,
        default='comment_keyword'
    )
    instagram_post_id = models.CharField(
        max_length=255,
        blank=True,
        help_text="Instagram post ID (optional - leave blank for all posts)"
    )
    keywords = models.TextField(
        blank=True,
        help_text="Comma-separated keywords to trigger this flow"
    )

    # Status
    is_active = models.BooleanField(default=True)

    # Statistics
    total_triggered = models.PositiveIntegerField(default=0)
    total_completed = models.PositiveIntegerField(default=0)

    # Metadata
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} ({self.user.email})"

    def get_keywords_list(self):
        """Return keywords as a list"""
        if not self.keywords:
            return []
        return [kw.strip().lower() for kw in self.keywords.split(',') if kw.strip()]

    def matches_comment(self, comment_text):
        """Check if comment text matches this flow's trigger"""
        if self.trigger_type == 'comment_any':
            return True
        keywords = self.get_keywords_list()
        if not keywords:
            return True
        comment_lower = comment_text.lower()
        return any(keyword in comment_lower for keyword in keywords)

    def get_first_node(self):
        """Get the first node in this flow (lowest order)"""
        return self.nodes.filter(order__isnull=False).order_by('order').first()

    def increment_triggered(self):
        """Increment the triggered counter atomically"""
        DMFlow.objects.filter(pk=self.pk).update(total_triggered=F('total_triggered') + 1)

    def increment_completed(self):
        """Increment the completed counter atomically"""
        DMFlow.objects.filter(pk=self.pk).update(total_completed=F('total_completed') + 1)

    class Meta:
        verbose_name = "DM Flow"
        verbose_name_plural = "DM Flows"
        ordering = ['-created_at']


class FlowNode(models.Model):
    """A single step/node in a DM flow"""
    NODE_TYPE_CHOICES = [
        ('comment_reply', 'Comment Reply'),
        ('message_text', 'Text Message'),
        ('message_quick_reply', 'Quick Reply Message'),
        ('message_button_template', 'Button Template'),
        ('message_link', 'Link Message'),
        ('condition_follower', 'Follower Check'),
        ('condition_user_interacted', 'Returning User Check'),
        ('collect_data', 'Collect Data'),
        ('ai_conversation', 'AI Conversation'),  # AI-powered conversational node
    ]
    # condition_user_interacted config: {"true_node_id": N, "false_node_id": N, "time_period": "ever|24h|7d|30d"}

    flow = models.ForeignKey(
        DMFlow,
        on_delete=models.CASCADE,
        related_name='nodes'
    )

    # Node details
    order = models.PositiveIntegerField(
        help_text="Order of this node in the flow (0 = first)"
    )
    node_type = models.CharField(max_length=30, choices=NODE_TYPE_CHOICES)
    name = models.CharField(
        max_length=100,
        blank=True,
        help_text="Optional label for this step"
    )

    # Configuration varies by node type (stored as JSON)
    # comment_reply: {"text": "...", "variations": ["...", "..."]}
    # message_text: {"text": "...", "variations": ["...", "..."]}
    # message_quick_reply: {"text": "..."} (QuickReplyOptions are separate)
    # message_button_template: {"text": "...", "buttons": [{"type": "web_url|postback", "title": "...", "url": "...", "payload": "..."}]}
    # message_link: {"text": "...", "url": "..."}
    # condition_follower: {"true_node_id": N, "false_node_id": N, "follower_test_content": {...}}
    # collect_data: {"field_type": "name|email|phone|custom", "prompt_text": "...", "variable_name": "...", "validation": "..."}
    config = models.JSONField(default=dict, blank=True)

    # For simple sequential flows, points to next node
    # For branching, use config to specify target nodes
    next_node = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='previous_nodes',
        help_text="Next node in the flow (for sequential flows)"
    )

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        label = self.name or self.get_node_type_display()
        return f"{self.flow.title} - Step {self.order}: {label}"

    def get_text_with_variation(self):
        """Get text, randomly selecting from variations if available"""
        import random
        config = self.config or {}
        variations = config.get('variations', [])
        if variations:
            return random.choice(variations)
        return config.get('text', '')

    class Meta:
        verbose_name = "Flow Node"
        verbose_name_plural = "Flow Nodes"
        ordering = ['flow', 'order']
        unique_together = ['flow', 'order']


class QuickReplyOption(models.Model):
    """A quick reply button option for a message_quick_reply node"""
    node = models.ForeignKey(
        FlowNode,
        on_delete=models.CASCADE,
        related_name='quick_reply_options'
    )

    # Button details (Instagram limits: max 20 chars title, max 13 options)
    title = models.CharField(max_length=20, help_text="Button text (max 20 chars)")
    payload = models.CharField(max_length=100, help_text="Identifier for this option")
    order = models.PositiveIntegerField(default=0)

    # Where to go when clicked
    target_node = models.ForeignKey(
        FlowNode,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='incoming_quick_replies',
        help_text="Node to execute when this button is clicked"
    )

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.node} - Button: {self.title}"

    class Meta:
        verbose_name = "Quick Reply Option"
        verbose_name_plural = "Quick Reply Options"
        ordering = ['node', 'order']


class FlowSession(models.Model):
    """Tracks a user's progress through a DM flow"""
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('waiting_reply', 'Waiting for Reply'),
        ('completed', 'Completed'),
        ('expired', 'Expired'),
        ('error', 'Error'),
    ]

    flow = models.ForeignKey(
        DMFlow,
        on_delete=models.CASCADE,
        related_name='sessions'
    )

    # Instagram user info
    instagram_scoped_id = models.CharField(
        max_length=255,
        help_text="Instagram-scoped ID (IGSID) for DMs"
    )
    instagram_username = models.CharField(max_length=255, blank=True)

    # Current position in flow
    current_node = models.ForeignKey(
        FlowNode,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='current_sessions'
    )

    # Session status
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='active'
    )

    # Context data collected during the flow
    # e.g., {"user_name": "John", "user_email": "...", "is_follower": true}
    context_data = models.JSONField(default=dict, blank=True)

    # Original trigger info
    trigger_comment_id = models.CharField(
        max_length=255,
        blank=True,
        help_text="Comment ID that triggered this flow"
    )
    trigger_post_id = models.CharField(max_length=255, blank=True)
    trigger_comment_text = models.TextField(blank=True)

    # Error tracking
    error_message = models.TextField(blank=True)
    retry_count = models.PositiveIntegerField(default=0)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Session {self.pk} - @{self.instagram_username} in {self.flow.title}"

    def set_waiting_for_reply(self):
        """Set status to waiting for reply"""
        self.status = 'waiting_reply'
        self.save(update_fields=['status', 'updated_at'])

    def complete(self):
        """Mark session as completed"""
        from django.utils import timezone
        self.status = 'completed'
        self.completed_at = timezone.now()
        self.save(update_fields=['status', 'completed_at', 'updated_at'])
        self.flow.increment_completed()

    def set_error(self, message):
        """Mark session as error"""
        self.status = 'error'
        self.error_message = message
        self.save(update_fields=['status', 'error_message', 'updated_at'])

    def update_context(self, key, value):
        """Update a value in context_data"""
        self.context_data[key] = value
        self.save(update_fields=['context_data', 'updated_at'])

    class Meta:
        verbose_name = "Flow Session"
        verbose_name_plural = "Flow Sessions"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['instagram_scoped_id']),
            models.Index(fields=['status']),
        ]


class FlowExecutionLog(models.Model):
    """Log of actions taken during flow execution"""
    ACTION_CHOICES = [
        ('flow_started', 'Flow Started'),
        ('node_executed', 'Node Executed'),
        ('message_sent', 'Message Sent'),
        ('comment_replied', 'Comment Replied'),
        ('quick_reply_received', 'Quick Reply Received'),
        ('text_reply_received', 'Text Reply Received'),
        ('condition_checked', 'Condition Checked'),
        ('data_collected', 'Data Collected'),
        ('flow_completed', 'Flow Completed'),
        ('error', 'Error'),
    ]

    session = models.ForeignKey(
        FlowSession,
        on_delete=models.CASCADE,
        related_name='execution_logs'
    )
    node = models.ForeignKey(
        FlowNode,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='execution_logs'
    )

    # Action details
    action = models.CharField(max_length=30, choices=ACTION_CHOICES)
    details = models.JSONField(default=dict, blank=True)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.session} - {self.action}"

    class Meta:
        verbose_name = "Flow Execution Log"
        verbose_name_plural = "Flow Execution Logs"
        ordering = ['-created_at']


class CollectedLead(models.Model):
    """Stores user data collected during flows for CRM/export"""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='collected_leads',
        help_text="Account owner who collected this lead"
    )
    flow = models.ForeignKey(
        DMFlow,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='collected_leads'
    )
    session = models.ForeignKey(
        FlowSession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='collected_leads'
    )

    # Instagram user info
    instagram_scoped_id = models.CharField(max_length=255)
    instagram_username = models.CharField(max_length=255, blank=True)

    # Collected data fields
    name = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)

    # Additional custom data
    custom_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Any extra fields collected"
    )

    # Status
    is_follower = models.BooleanField(default=False)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Lead: @{self.instagram_username or self.instagram_scoped_id}"

    def get_all_data(self):
        """Get all collected data as a dict"""
        data = {
            'instagram_username': self.instagram_username,
            'name': self.name,
            'email': self.email,
            'phone': self.phone,
            'is_follower': self.is_follower,
        }
        data.update(self.custom_data)
        return {k: v for k, v in data.items() if v}

    class Meta:
        verbose_name = "Collected Lead"
        verbose_name_plural = "Collected Leads"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['instagram_scoped_id']),
            models.Index(fields=['user', 'created_at']),
        ]


# =============================================================================
# Flow Templates
# =============================================================================

class FlowTemplate(models.Model):
    """Pre-built flow templates that users can use to create flows quickly"""
    CATEGORY_CHOICES = [
        ('follow_gate', 'Follow Gate'),
        ('quiz', 'Quiz / Survey'),
        ('giveaway', 'Giveaway'),
        ('link_delivery', 'Link Delivery'),
        ('other', 'Other'),
        ('lead_gen', 'Lead Generation'),
    ]

    title = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='other')

    # The flow structure as JSON
    # Format: [{"node_type": "...", "config": {...}, "quick_replies": [...], "order": 0}, ...]
    nodes_json = models.JSONField(
        help_text="JSON array of node configurations"
    )

    # Optional preview/icon
    icon = models.CharField(
        max_length=50,
        default='bi-lightning',
        help_text="Bootstrap icon class (e.g., bi-lightning, bi-person-check)"
    )

    # Control visibility and ordering
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0, help_text="Display order (lower = first)")

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title

    class Meta:
        verbose_name = "Flow Template"
        verbose_name_plural = "Flow Templates"
        ordering = ['order', 'title']


# =============================================================================
# AI Social Agent System
# =============================================================================

class SocialAgent(models.Model):
    """User-created AI agent with personality and knowledge base"""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='social_agents'
    )

    # Agent identity
    name = models.CharField(max_length=100, help_text="Agent name (e.g., 'Property Expert')")
    avatar_url = models.URLField(blank=True, help_text="S3 URL for agent avatar")

    # Personality configuration
    personality = models.TextField(
        help_text="Agent personality description"
    )
    tone = models.CharField(
        max_length=50,
        default='friendly',
        help_text="Communication tone (friendly, professional, casual, formal)"
    )
    language_style = models.TextField(
        blank=True,
        help_text="Language preferences (e.g., 'Use simple English, avoid jargon')"
    )

    # Behavior boundaries
    boundaries = models.TextField(
        blank=True,
        help_text="What the agent should NOT do"
    )

    # Custom system prompt (overrides auto-generated)
    custom_system_prompt = models.TextField(
        blank=True,
        help_text="Custom system prompt (leave empty to auto-generate)"
    )

    # Status
    is_active = models.BooleanField(default=True)

    # Statistics
    total_conversations = models.PositiveIntegerField(default=0)
    total_messages_sent = models.PositiveIntegerField(default=0)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.user.email})"

    def get_system_prompt(self):
        """Generate or return custom system prompt"""
        if self.custom_system_prompt:
            return self.custom_system_prompt

        prompt_parts = [
            f"You are {self.name}, a social media assistant.",
            f"\nPersonality: {self.personality}",
            f"\nTone: {self.tone}",
        ]
        if self.language_style:
            prompt_parts.append(f"\nLanguage style: {self.language_style}")
        if self.boundaries:
            prompt_parts.append(f"\nBoundaries (DO NOT): {self.boundaries}")
        prompt_parts.append("\n\nAlways stay in character and be helpful.")

        return "".join(prompt_parts)

    def increment_stats(self, conversations=0, messages=0):
        """Increment agent statistics"""
        if conversations:
            self.total_conversations += conversations
        if messages:
            self.total_messages_sent += messages
        self.save(update_fields=['total_conversations', 'total_messages_sent', 'updated_at'])

    class Meta:
        verbose_name = "Social Agent"
        verbose_name_plural = "Social Agents"
        ordering = ['-created_at']


class KnowledgeBase(models.Model):
    """Knowledge base that can be attached to agents"""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='knowledge_bases'
    )
    agent = models.ForeignKey(
        SocialAgent,
        on_delete=models.CASCADE,
        related_name='knowledge_bases',
        null=True,
        blank=True,
        help_text="Agent this KB belongs to (null = shared/reusable)"
    )

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    # Stats
    total_items = models.PositiveIntegerField(default=0)
    total_chunks = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)

    # Status
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.user.email})"

    def update_stats(self):
        """Recalculate stats from items"""
        from django.db.models import Sum
        items = self.items.all()
        self.total_items = items.count()
        self.total_chunks = items.aggregate(Sum('chunk_count'))['chunk_count__sum'] or 0
        self.total_tokens = items.aggregate(Sum('token_count'))['token_count__sum'] or 0
        self.save(update_fields=['total_items', 'total_chunks', 'total_tokens', 'updated_at'])

    class Meta:
        verbose_name = "Knowledge Base"
        verbose_name_plural = "Knowledge Bases"
        ordering = ['-created_at']


class KnowledgeItem(models.Model):
    """Individual knowledge item (text or document)"""
    ITEM_TYPE_CHOICES = [
        ('text', 'Text'),
        ('pdf', 'PDF Document'),
        ('docx', 'Word Document'),
        ('csv', 'CSV File'),
        ('excel', 'Excel File'),
    ]

    PROCESSING_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    knowledge_base = models.ForeignKey(
        KnowledgeBase,
        on_delete=models.CASCADE,
        related_name='items'
    )

    # Content type
    item_type = models.CharField(max_length=20, choices=ITEM_TYPE_CHOICES)

    # For text items
    title = models.CharField(max_length=200, blank=True)
    content = models.TextField(blank=True, help_text="Raw text content")

    # For file items (stored in S3)
    file_url = models.URLField(blank=True, help_text="S3 URL for uploaded file")
    file_s3_key = models.CharField(max_length=500, blank=True, help_text="S3 object key")
    file_name = models.CharField(max_length=255, blank=True)
    file_size = models.PositiveIntegerField(default=0)  # In bytes

    # Processing status
    processing_status = models.CharField(
        max_length=20,
        choices=PROCESSING_STATUS_CHOICES,
        default='pending'
    )
    processing_error = models.TextField(blank=True)

    # Embedding stats
    chunk_count = models.PositiveIntegerField(default=0)
    token_count = models.PositiveIntegerField(default=0)
    embedding_cost = models.FloatField(default=0.0)  # Credits spent on embedding

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.title or self.file_name} ({self.knowledge_base.name})"

    def mark_processing(self):
        """Mark item as processing"""
        self.processing_status = 'processing'
        self.save(update_fields=['processing_status', 'updated_at'])

    def mark_completed(self, chunk_count, token_count, embedding_cost=0.0):
        """Mark item as completed"""
        from django.utils import timezone
        self.processing_status = 'completed'
        self.chunk_count = chunk_count
        self.token_count = token_count
        self.embedding_cost = embedding_cost
        self.processed_at = timezone.now()
        self.save(update_fields=[
            'processing_status', 'chunk_count', 'token_count',
            'embedding_cost', 'processed_at', 'updated_at'
        ])
        # Update parent KB stats
        self.knowledge_base.update_stats()

    def mark_failed(self, error_message):
        """Mark item as failed"""
        self.processing_status = 'failed'
        self.processing_error = error_message
        self.save(update_fields=['processing_status', 'processing_error', 'updated_at'])

    class Meta:
        verbose_name = "Knowledge Item"
        verbose_name_plural = "Knowledge Items"
        ordering = ['-created_at']


class KnowledgeChunk(models.Model):
    """Chunked and embedded content for vector search"""
    knowledge_item = models.ForeignKey(
        KnowledgeItem,
        on_delete=models.CASCADE,
        related_name='chunks'
    )

    # Chunk content
    content = models.TextField()
    chunk_index = models.PositiveIntegerField()
    token_count = models.PositiveIntegerField(default=0)

    # Vector embedding stored as JSON array
    # For production with pgvector: embedding = VectorField(dimensions=1536)
    embedding = models.JSONField(default=list, help_text="Vector embedding array")

    # Metadata for source tracking
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Source info: page number, section, row number, etc."
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Chunk {self.chunk_index} of {self.knowledge_item}"

    class Meta:
        verbose_name = "Knowledge Chunk"
        verbose_name_plural = "Knowledge Chunks"
        ordering = ['knowledge_item', 'chunk_index']
        indexes = [
            models.Index(fields=['knowledge_item', 'chunk_index']),
        ]


class AINodeConfig(models.Model):
    """Configuration for AI conversational node in flow"""
    ON_COMPLETE_CHOICES = [
        ('next_node', 'Continue to Next Node'),
        ('end_flow', 'End Flow'),
        ('specific_node', 'Go to Specific Node'),
    ]

    ON_FAILURE_CHOICES = [
        ('end_flow', 'End Flow'),
        ('specific_node', 'Go to Specific Node'),
        ('notify_owner', 'Notify Owner & End'),
    ]

    flow_node = models.OneToOneField(
        FlowNode,
        on_delete=models.CASCADE,
        related_name='ai_config'
    )

    # Select which agent to use
    agent = models.ForeignKey(
        SocialAgent,
        on_delete=models.SET_NULL,
        null=True,
        related_name='ai_nodes'
    )

    # Node-specific goal
    goal = models.TextField(
        help_text="Specific goal for this node (e.g., 'Collect email and qualify lead')"
    )

    # Additional knowledge bases for this specific node
    additional_knowledge_bases = models.ManyToManyField(
        KnowledgeBase,
        blank=True,
        related_name='ai_nodes',
        help_text="Extra knowledge bases for this node"
    )

    # Data collection schema
    # Format: [{"field": "email", "type": "email", "required": true, "label": "Email"}]
    collection_schema = models.JSONField(
        default=list,
        blank=True,
        help_text="Schema for data collection"
    )

    # First message (optional - AI will generate if empty)
    first_message = models.TextField(
        blank=True,
        help_text="Custom first message (leave empty for AI to generate)"
    )

    # Behavior settings
    max_turns = models.PositiveIntegerField(
        default=10,
        help_text="Maximum conversation turns"
    )
    timeout_minutes = models.PositiveIntegerField(
        default=60,
        help_text="Session timeout in minutes"
    )

    # Goal completion handling
    on_goal_complete = models.CharField(
        max_length=20,
        choices=ON_COMPLETE_CHOICES,
        default='next_node'
    )
    goal_complete_node = models.ForeignKey(
        FlowNode,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ai_goal_complete_targets',
        help_text="Node to go to when goal is complete"
    )

    # Failure/timeout handling
    on_failure = models.CharField(
        max_length=20,
        choices=ON_FAILURE_CHOICES,
        default='end_flow'
    )
    failure_node = models.ForeignKey(
        FlowNode,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ai_failure_targets'
    )

    # Max turns handling
    on_max_turns = models.CharField(
        max_length=20,
        choices=ON_FAILURE_CHOICES,
        default='end_flow'
    )
    max_turns_node = models.ForeignKey(
        FlowNode,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ai_max_turns_targets'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"AI Config for {self.flow_node}"

    def get_all_knowledge_bases(self):
        """Get agent KB + additional KBs for this node"""
        kbs = list(self.additional_knowledge_bases.filter(is_active=True))
        if self.agent:
            agent_kbs = list(self.agent.knowledge_bases.filter(is_active=True))
            kbs = agent_kbs + kbs
        return kbs

    def get_required_fields(self):
        """Get list of required field names from schema"""
        return [f['field'] for f in self.collection_schema if f.get('required')]

    def validate_collected_data(self, data):
        """Check if all required fields are collected"""
        required = self.get_required_fields()
        for field in required:
            if not data.get(field):
                return False, field
        return True, None

    class Meta:
        verbose_name = "AI Node Config"
        verbose_name_plural = "AI Node Configs"


class AIConversationMessage(models.Model):
    """Individual message in AI conversation"""
    ROLE_CHOICES = [
        ('user', 'User'),
        ('assistant', 'Assistant'),
        ('system', 'System'),
    ]

    session = models.ForeignKey(
        FlowSession,
        on_delete=models.CASCADE,
        related_name='ai_messages'
    )
    ai_config = models.ForeignKey(
        AINodeConfig,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='messages'
    )

    # Message content
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    content = models.TextField()

    # Data collected from this specific message
    collected_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Data extracted from this message"
    )

    # RAG context used for this response
    knowledge_chunks_used = models.JSONField(
        default=list,
        blank=True,
        help_text="IDs of knowledge chunks retrieved for context"
    )

    # Token usage
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)

    # Instagram message ID (for deduplication)
    instagram_message_id = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.role}: {self.content[:50]}..."

    class Meta:
        verbose_name = "AI Conversation Message"
        verbose_name_plural = "AI Conversation Messages"
        ordering = ['session', 'created_at']
        indexes = [
            models.Index(fields=['session', 'created_at']),
            models.Index(fields=['instagram_message_id']),
        ]


class AIUsageLog(models.Model):
    """Tracks all AI usage for billing and analytics"""
    USAGE_TYPE_CHOICES = [
        ('chat_completion', 'Chat Completion'),
        ('embedding', 'Embedding'),
        ('rag_query', 'RAG Query'),
        ('data_extraction', 'Data Extraction'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='ai_usage_logs'
    )
    session = models.ForeignKey(
        FlowSession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ai_usage_logs'
    )
    agent = models.ForeignKey(
        SocialAgent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='usage_logs'
    )

    # Usage details
    usage_type = models.CharField(max_length=30, choices=USAGE_TYPE_CHOICES)
    model = models.CharField(max_length=50, help_text="Model used (e.g., gpt-4o-mini)")

    # Token counts
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)

    # Cost tracking
    cost_usd = models.FloatField(default=0.0, help_text="Actual API cost in USD")
    credits_charged = models.FloatField(default=0.0, help_text="Credits deducted from user")

    # Additional metadata
    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.email} - {self.usage_type} - {self.credits_charged} credits"

    @classmethod
    def log_usage(cls, user, usage_type, model, input_tokens, output_tokens,
                  cost_usd, credits_charged, session=None, agent=None, metadata=None):
        """Helper to create usage log"""
        return cls.objects.create(
            user=user,
            session=session,
            agent=agent,
            usage_type=usage_type,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cost_usd=cost_usd,
            credits_charged=credits_charged,
            metadata=metadata or {}
        )

    class Meta:
        verbose_name = "AI Usage Log"
        verbose_name_plural = "AI Usage Logs"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['usage_type']),
            models.Index(fields=['session']),
        ]


class QueuedFlowTrigger(models.Model):
    """Stores flow triggers that were rate-limited and need to be processed later."""
    TRIGGER_TYPE_CHOICES = [
        ('comment', 'Comment'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    account = models.ForeignKey(
        InstagramAccount,
        on_delete=models.CASCADE,
        related_name='queued_flow_triggers'
    )
    flow = models.ForeignKey(
        DMFlow,
        on_delete=models.CASCADE,
        related_name='queued_triggers'
    )
    trigger_type = models.CharField(max_length=20, choices=TRIGGER_TYPE_CHOICES, default='comment')

    # Deduplication - unique identifier from Instagram
    instagram_event_id = models.CharField(max_length=255)  # comment_id or message_id

    # Context needed to trigger flow later
    trigger_context = models.JSONField()
    # For comment: {comment_id, post_id, commenter_id, commenter_username, comment_text}

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    error_message = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Queued Flow Trigger"
        verbose_name_plural = "Queued Flow Triggers"
        ordering = ['created_at']
        unique_together = ['account', 'instagram_event_id']
        indexes = [
            models.Index(fields=['account', 'status', 'created_at']),
        ]

    def __str__(self):
        return f"Queued: {self.flow.title} - {self.instagram_event_id[:20]}"

    @classmethod
    def get_rate_limit(cls):
        """Get configured rate limit from Configuration, default 200"""
        from core.models import Configuration
        try:
            return int(Configuration.get_value('INSTAGRAM_RATE_LIMIT', '200'))
        except (ValueError, TypeError):
            return 200

    @classmethod
    def get_pending_for_account(cls, account):
        """Get all pending triggers for an account, ordered by created_at"""
        return cls.objects.filter(account=account, status='pending').order_by('created_at')


class AICollectedData(models.Model):
    """Structured data collected by AI during conversations"""
    session = models.OneToOneField(
        FlowSession,
        on_delete=models.CASCADE,
        related_name='ai_collected_data'
    )
    ai_config = models.ForeignKey(
        AINodeConfig,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='collected_data_records'
    )

    # The collected data (dynamic based on schema)
    data = models.JSONField(
        default=dict,
        help_text="Collected data matching the node's collection_schema"
    )

    # Schema snapshot at collection time
    schema_snapshot = models.JSONField(
        default=list,
        help_text="Copy of collection_schema used"
    )

    # Completion tracking
    is_complete = models.BooleanField(
        default=False,
        help_text="True if all required fields collected"
    )
    completion_percentage = models.FloatField(default=0.0)
    fields_collected = models.JSONField(
        default=list,
        help_text="List of field names that have been collected"
    )

    # AI conversation summary
    conversation_summary = models.TextField(
        blank=True,
        help_text="AI-generated summary of the conversation"
    )

    # Turn count
    turn_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"AI Data for Session {self.session_id}"

    def update_field(self, field_name, value):
        """Update a single field in collected data"""
        self.data[field_name] = value
        if field_name not in self.fields_collected:
            self.fields_collected.append(field_name)
        self._recalculate_completion()
        self.save(update_fields=['data', 'fields_collected', 'is_complete',
                                  'completion_percentage', 'updated_at'])

    def update_multiple_fields(self, field_dict):
        """Update multiple fields at once"""
        for field_name, value in field_dict.items():
            if value:  # Only update non-empty values
                self.data[field_name] = value
                if field_name not in self.fields_collected:
                    self.fields_collected.append(field_name)
        self._recalculate_completion()
        self.save(update_fields=['data', 'fields_collected', 'is_complete',
                                  'completion_percentage', 'updated_at'])

    def _recalculate_completion(self):
        """Recalculate completion percentage"""
        if not self.schema_snapshot:
            self.is_complete = True
            self.completion_percentage = 100.0
            return

        required_fields = [f for f in self.schema_snapshot if f.get('required')]
        if not required_fields:
            self.is_complete = True
            self.completion_percentage = 100.0
            return

        filled_required = sum(
            1 for f in required_fields
            if self.data.get(f['field'])
        )
        self.completion_percentage = round((filled_required / len(required_fields)) * 100, 1)
        self.is_complete = filled_required == len(required_fields)

    def increment_turn(self):
        """Increment turn count"""
        self.turn_count += 1
        self.save(update_fields=['turn_count', 'updated_at'])

    class Meta:
        verbose_name = "AI Collected Data"
        verbose_name_plural = "AI Collected Data"
        indexes = [
            models.Index(fields=['session']),
            models.Index(fields=['is_complete']),
        ]
