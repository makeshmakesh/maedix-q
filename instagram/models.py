from django.db import models
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

    class Meta:
        verbose_name = "Instagram Account"
        verbose_name_plural = "Instagram Accounts"


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
        """Increment the triggered counter"""
        self.total_triggered += 1
        self.save(update_fields=['total_triggered', 'updated_at'])

    def increment_completed(self):
        """Increment the completed counter"""
        self.total_completed += 1
        self.save(update_fields=['total_completed', 'updated_at'])

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
        ('lead_gen', 'Lead Generation'),
        ('follow_gate', 'Follow Gate'),
        ('quiz', 'Quiz / Survey'),
        ('giveaway', 'Giveaway'),
        ('link_delivery', 'Link Delivery'),
        ('other', 'Other'),
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
