#pylint: disable=all
"""
Flow Engine for Instagram DM Flow Builder

Handles the execution of multi-step DM flows including:
- Triggering flows from comments
- Executing different node types
- Processing quick reply clicks
- Data collection and validation
- Follower verification loops
"""

import re
import copy
import logging
from typing import Optional, Tuple, Dict, Any

from django.utils import timezone
from django.db import transaction

from .models import (
    DMFlow, FlowNode, QuickReplyOption, FlowSession,
    FlowExecutionLog, CollectedLead, InstagramAccount
)
from .instagram_api import InstagramAPIClient, InstagramAPIError, get_api_client_for_account
from core.subscription_utils import get_user_subscription

logger = logging.getLogger(__name__)


class FlowEngineError(Exception):
    """Custom exception for flow engine errors"""
    pass


class FlowEngine:
    """
    Engine for executing Instagram DM flows.

    The engine handles:
    - Creating sessions when comments trigger flows
    - Executing nodes based on their type
    - Advancing through the flow
    - Handling user responses (quick replies, text replies)
    """

    # Maximum number of node executions per session to prevent infinite loops
    MAX_NODE_EXECUTIONS = 30

    def __init__(self, instagram_account: InstagramAccount):
        """
        Initialize the flow engine.

        Args:
            instagram_account: The InstagramAccount model instance
        """
        self.instagram_account = instagram_account
        self.api_client = get_api_client_for_account(instagram_account)
        self._branch_targets = {}  # {flow_id: set of node_ids} — computed once per flow

    def _log_action(
        self,
        session: FlowSession,
        action: str,
        node: Optional[FlowNode] = None,
        details: Optional[dict] = None
    ):
        """Log an action to the flow execution log."""
        FlowExecutionLog.objects.create(
            session=session,
            node=node,
            action=action,
            details=details or {}
        )

    # =========================================================================
    # Flow Triggering
    # =========================================================================

    def trigger_flow_from_comment(
        self,
        flow: DMFlow,
        comment_id: str,
        post_id: str,
        commenter_id: str,
        commenter_username: str,
        comment_text: str
    ) -> Optional[FlowSession]:
        """
        Trigger a flow when a comment is received.

        Args:
            flow: The DMFlow to trigger
            comment_id: The triggering comment's ID
            post_id: The post ID where the comment was made
            commenter_id: The commenter's Instagram-scoped ID (IGSID)
            commenter_username: The commenter's username
            comment_text: The comment text

        Returns:
            The created FlowSession, or None if flow couldn't be started
        """
        logger.info(f"Triggering flow '{flow.title}' from comment {comment_id}")

        # Create session
        with transaction.atomic():
            session = FlowSession.objects.create(
                flow=flow,
                instagram_scoped_id=commenter_id,
                instagram_username=commenter_username,
                trigger_comment_id=comment_id,
                trigger_post_id=post_id,
                trigger_comment_text=comment_text,
                status='active',
                context_data={}
            )

            flow.increment_triggered()

            # Create or update lead record for every session
            existing_lead = CollectedLead.objects.filter(
                user=flow.user, instagram_scoped_id=commenter_id
            ).first()
            if existing_lead:
                existing_lead.flow = flow
                existing_lead.session = session
                if existing_lead.instagram_username != commenter_username:
                    existing_lead.instagram_username = commenter_username
                existing_lead.save(update_fields=['flow', 'session', 'instagram_username', 'updated_at'])
            elif self._can_create_lead(flow.user):
                CollectedLead.objects.create(
                    user=flow.user,
                    instagram_scoped_id=commenter_id,
                    flow=flow,
                    session=session,
                    instagram_username=commenter_username,
                )

            self._log_action(session, 'flow_started', details={
                'comment_id': comment_id,
                'post_id': post_id,
                'comment_text': comment_text
            })

        # Get first node and execute
        first_node = flow.get_first_node()
        if not first_node:
            logger.error(f"Flow '{flow.title}' has no nodes")
            session.set_error("Flow has no nodes configured")
            return session

        try:
            self.execute_node(session, first_node)
        except Exception as e:
            logger.error(f"Error executing first node: {str(e)}")
            session.set_error(str(e))
            self._log_action(session, 'error', first_node, {'error': str(e)})

        return session

    # =========================================================================
    # Node Execution
    # =========================================================================

    def execute_node(self, session: FlowSession, node: FlowNode):
        """
        Execute a node based on its type.

        Args:
            session: The current flow session
            node: The node to execute
        """
        logger.info(f"Executing node {node.id} (type: {node.node_type}) for session {session.id}")

        # Track node execution count to prevent infinite loops
        execution_count = session.context_data.get('_node_execution_count', 0) + 1
        session.context_data['_node_execution_count'] = execution_count

        # Track how many times each node has been executed to detect loops
        node_exec_key = f'_node_{node.id}_exec_count'
        node_exec_count = session.context_data.get(node_exec_key, 0) + 1
        session.context_data[node_exec_key] = node_exec_count

        # Check for infinite loop - too many total node executions
        if execution_count > self.MAX_NODE_EXECUTIONS:
            logger.error(
                f"Infinite loop detected in session {session.id}: "
                f"exceeded {self.MAX_NODE_EXECUTIONS} node executions"
            )
            session.set_error(f"Flow stopped: exceeded maximum of {self.MAX_NODE_EXECUTIONS} steps (possible loop in flow configuration)")
            self._log_action(session, 'error', node, {
                'error': 'infinite_loop_detected',
                'execution_count': execution_count,
                'max_allowed': self.MAX_NODE_EXECUTIONS
            })
            return

        # Check for same node being executed too many times (loop on specific node)
        MAX_SAME_NODE_EXECUTIONS = 5
        if node_exec_count > MAX_SAME_NODE_EXECUTIONS:
            logger.error(
                f"Loop detected in session {session.id}: "
                f"node {node.id} executed {node_exec_count} times"
            )
            session.set_error(f"Flow stopped: node executed {node_exec_count} times (loop detected in flow configuration)")
            self._log_action(session, 'error', node, {
                'error': 'node_loop_detected',
                'node_id': node.id,
                'node_exec_count': node_exec_count,
                'max_allowed': MAX_SAME_NODE_EXECUTIONS
            })
            return

        # Update session's current node
        session.current_node = node
        session.status = 'active'
        session.save(update_fields=['current_node', 'status', 'updated_at', 'context_data'])

        self._log_action(session, 'node_executed', node, {
            'node_type': node.node_type,
            'node_order': node.order
        })

        # Execute based on node type
        handlers = {
            'comment_reply': self._handle_comment_reply,
            'message_text': self._handle_message_text,
            'message_quick_reply': self._handle_message_quick_reply,
            'message_button_template': self._handle_message_button_template,
            'message_link': self._handle_message_link,
            'condition_follower': self._handle_condition_follower,
            'condition_user_interacted': self._handle_condition_user_interacted,
            'collect_data': self._handle_collect_data,
            'ai_conversation': self._handle_ai_conversation,  # AI Node
        }

        handler = handlers.get(node.node_type)
        if not handler:
            raise FlowEngineError(f"Unknown node type: {node.node_type}")

        handler(session, node)

    def _handle_comment_reply(self, session: FlowSession, node: FlowNode):
        """Handle comment_reply node - replies to the triggering comment."""
        if not session.trigger_comment_id:
            logger.warning("No trigger comment ID, skipping comment reply")
            self._advance_to_next_node(session, node)
            return

        text = node.get_text_with_variation()
        if not text:
            logger.warning("Comment reply node has no text")
            self._advance_to_next_node(session, node)
            return

        try:
            self.api_client.reply_to_comment(session.trigger_comment_id, text)
            self._log_action(session, 'comment_replied', node, {'text': text})
            logger.info(f"Replied to comment {session.trigger_comment_id}")
        except InstagramAPIError as e:
            logger.error(f"Failed to reply to comment: {e}")
            self._log_action(session, 'error', node, {'error': str(e)})
            # Continue flow even if comment reply fails

        self._advance_to_next_node(session, node)

    def _handle_message_text(self, session: FlowSession, node: FlowNode):
        """Handle message_text node - sends a plain text DM."""
        text = node.get_text_with_variation()
        if not text:
            logger.warning("Message text node has no text")
            self._advance_to_next_node(session, node)
            return

        # Substitute context variables in text
        text = self._substitute_variables(text, session.context_data)

        try:
            # For first message, use comment_id; for subsequent, use IGSID
            has_sent = self._has_sent_dm(session)
            logger.info(f"DM check: trigger_comment_id={session.trigger_comment_id}, has_sent_dm={has_sent}, igsid={session.instagram_scoped_id}")
            if session.trigger_comment_id and not has_sent:
                logger.info(f"Sending DM via comment_id: {session.trigger_comment_id}")
                self.api_client.send_dm_to_commenter(session.trigger_comment_id, text)
            else:
                logger.info(f"Sending DM via IGSID: {session.instagram_scoped_id}")
                self.api_client.send_text_dm(session.instagram_scoped_id, text)

            self._log_action(session, 'message_sent', node, {'text': text})
            logger.info(f"Sent text DM to {session.instagram_username}")
        except InstagramAPIError as e:
            logger.error(f"Failed to send text DM: {e}")
            if e.is_messaging_restricted_error():
                # User has privacy settings that prevent DMs - not a system error
                session.set_error("User doesn't allow message requests")
                self._log_action(session, 'dm_restricted', node, {
                    'error': str(e),
                    'reason': 'user_messaging_restricted'
                })
            else:
                session.set_error(str(e))
                self._log_action(session, 'error', node, {'error': str(e)})
            return

        self._advance_to_next_node(session, node)

    def _handle_message_quick_reply(self, session: FlowSession, node: FlowNode):
        """Handle message_quick_reply node - sends a message with clickable buttons."""
        # Prevent rapid duplicate execution (within 3 seconds) - allows legitimate re-clicks later
        from datetime import timedelta
        recent_cutoff = timezone.now() - timedelta(seconds=3)
        recent_send = FlowExecutionLog.objects.filter(
            session=session,
            node=node,
            action='message_sent',
            created_at__gte=recent_cutoff
        ).exclude(details__template_type='button').exists()
        if recent_send:
            logger.warning(f"Quick reply node {node.id} sent recently in session {session.id}, skipping duplicate")
            return

        # Get text with variation support
        text = node.get_text_with_variation()
        if not text:
            logger.warning("Quick reply node has no text")
            self._advance_to_next_node(session, node)
            return

        # Substitute context variables
        text = self._substitute_variables(text, session.context_data)

        # Get quick reply options
        options = node.quick_reply_options.all().order_by('order')
        if not options.exists():
            logger.warning("Quick reply node has no options, sending as plain text")
            try:
                # Use comment_id for first DM, IGSID for follow-ups
                if session.trigger_comment_id and not self._has_sent_dm(session):
                    self.api_client.send_dm_to_commenter(session.trigger_comment_id, text)
                else:
                    self.api_client.send_text_dm(session.instagram_scoped_id, text)
            except InstagramAPIError as e:
                logger.error(f"Failed to send DM: {e}")
                session.set_error(str(e))
            self._advance_to_next_node(session, node)
            return

        # Build quick replies payload with session-specific payloads
        quick_replies = []
        for opt in options:
            # Payload format: flow_{session_id}_node_{node_id}_opt_{option_payload}
            payload = f"flow_{session.id}_node_{node.id}_opt_{opt.payload}"
            quick_replies.append({
                'content_type': 'text',
                'title': opt.title[:20],  # Instagram limit
                'payload': payload
            })

        try:
            # Use comment_id for first DM to initiate conversation, IGSID for follow-ups
            if session.trigger_comment_id and not self._has_sent_dm(session):
                logger.info(f"Sending quick reply via comment_id (first DM)")
                self.api_client.send_dm_to_commenter(
                    session.trigger_comment_id,
                    text,
                    quick_replies
                )
            else:
                self.api_client.send_dm_with_quick_replies(
                    session.instagram_scoped_id,
                    text,
                    quick_replies
                )
            self._log_action(session, 'message_sent', node, {
                'text': text,
                'quick_replies': [qr['title'] for qr in quick_replies]
            })
            logger.info(f"Sent quick reply DM to {session.instagram_username}")
        except InstagramAPIError as e:
            logger.error(f"Failed to send quick reply DM: {e}")
            if e.is_messaging_restricted_error():
                session.set_error("User doesn't allow message requests")
                self._log_action(session, 'dm_restricted', node, {
                    'error': str(e),
                    'reason': 'user_messaging_restricted'
                })
            else:
                session.set_error(str(e))
                self._log_action(session, 'error', node, {'error': str(e)})
            return

        # Wait for user to click a button
        session.set_waiting_for_reply()

    def _handle_message_button_template(self, session: FlowSession, node: FlowNode):
        """
        Handle message_button_template node - sends a message with button template.

        Button template supports up to 3 buttons that can be:
        - web_url: Opens a URL in in-app browser
        - postback: Sends a webhook notification with payload
        """
        # Prevent rapid duplicate execution (within 3 seconds) - allows legitimate re-clicks later
        from datetime import timedelta
        recent_cutoff = timezone.now() - timedelta(seconds=3)
        recent_send = FlowExecutionLog.objects.filter(
            session=session,
            node=node,
            action='message_sent',
            details__template_type='button',
            created_at__gte=recent_cutoff
        ).exists()
        if recent_send:
            logger.warning(f"Button template node {node.id} sent recently in session {session.id}, skipping duplicate")
            return

        config = node.config or {}
        text = node.get_text_with_variation()
        buttons = config.get('buttons', [])

        if not text:
            logger.warning("Button template node has no text")
            self._advance_to_next_node(session, node)
            return

        if not buttons:
            logger.warning("Button template node has no buttons, sending as plain text")
            # Substitute context variables before sending
            text = self._substitute_variables(text, session.context_data)
            try:
                if session.trigger_comment_id and not self._has_sent_dm(session):
                    self.api_client.send_dm_to_commenter(session.trigger_comment_id, text)
                else:
                    self.api_client.send_text_dm(session.instagram_scoped_id, text)
            except InstagramAPIError as e:
                logger.error(f"Failed to send DM: {e}")
                session.set_error(str(e))
            self._advance_to_next_node(session, node)
            return

        # Substitute context variables in text
        text = self._substitute_variables(text, session.context_data)

        # Process buttons - add session info to postback payloads
        processed_buttons = []
        for btn in buttons[:3]:  # Max 3 buttons
            # Normalize type: empty string, None, or missing should be 'postback'
            btn_type = btn.get('type') or 'postback'
            btn_type = btn_type.lower().strip() if btn_type else 'postback'
            if btn_type not in ('web_url', 'postback'):
                btn_type = 'postback'  # Default to postback for unknown types

            processed_btn = {
                'type': btn_type,
                'title': btn.get('title', 'Button')
            }
            if btn_type == 'web_url':
                processed_btn['url'] = btn.get('url', '')
            else:
                # Add session/node info to postback payload
                original_payload = btn.get('payload', 'btn')
                processed_btn['payload'] = f"flow_{session.id}_node_{node.id}_btn_{original_payload}"
            processed_buttons.append(processed_btn)

        try:
            # Use comment_id for first DM to initiate conversation, IGSID for follow-ups
            if session.trigger_comment_id and not self._has_sent_dm(session):
                logger.info(f"Sending button template via comment_id (first DM)")
                self.api_client.send_button_template_to_commenter(
                    session.trigger_comment_id,
                    text,
                    processed_buttons
                )
            else:
                self.api_client.send_button_template_dm(
                    session.instagram_scoped_id,
                    text,
                    processed_buttons
                )
            self._log_action(session, 'message_sent', node, {
                'text': text,
                'buttons': [btn['title'] for btn in processed_buttons],
                'template_type': 'button'
            })
            logger.info(f"Sent button template DM to {session.instagram_username}")
        except InstagramAPIError as e:
            logger.error(f"Failed to send button template DM: {e}")
            if e.is_messaging_restricted_error():
                session.set_error("User doesn't allow message requests")
                self._log_action(session, 'dm_restricted', node, {
                    'error': str(e),
                    'reason': 'user_messaging_restricted'
                })
            else:
                session.set_error(str(e))
                self._log_action(session, 'error', node, {'error': str(e)})
            return

        # If any button is a postback type, wait for response
        has_postback = any(btn.get('type') == 'postback' for btn in processed_buttons)
        if has_postback:
            session.set_waiting_for_reply()
        else:
            # All URL buttons - advance immediately
            self._advance_to_next_node(session, node)

    def _handle_message_link(self, session: FlowSession, node: FlowNode):
        """Handle message_link node - sends a message containing a URL."""
        # Deep copy config to avoid any shared reference issues
        config = copy.deepcopy(node.config) if node.config else {}
        # Get text with variation support
        text = node.get_text_with_variation()
        url = config.get('url', '')

        if not text and not url:
            logger.warning("Link message node has no content")
            self._advance_to_next_node(session, node)
            return

        # Substitute context variables
        text = self._substitute_variables(text, session.context_data)
        full_text = f"{text}\n{url}" if url and url not in text else text

        try:
            # Use comment_id for first DM, IGSID for follow-ups
            if session.trigger_comment_id and not self._has_sent_dm(session):
                self.api_client.send_dm_to_commenter(session.trigger_comment_id, full_text)
            else:
                self.api_client.send_text_dm(session.instagram_scoped_id, full_text)
            self._log_action(session, 'message_sent', node, {'text': text, 'url': url})
            logger.info(f"Sent link DM to {session.instagram_username}")
        except InstagramAPIError as e:
            logger.error(f"Failed to send link DM: {e}")
            if e.is_messaging_restricted_error():
                session.set_error("User doesn't allow message requests")
                self._log_action(session, 'dm_restricted', node, {
                    'error': str(e),
                    'reason': 'user_messaging_restricted'
                })
            else:
                session.set_error(str(e))
                self._log_action(session, 'error', node, {'error': str(e)})
            return

        self._advance_to_next_node(session, node)

    def _handle_condition_follower(self, session: FlowSession, node: FlowNode):
        """
        Handle condition_follower node - checks if user is a follower.

        Uses Instagram's User Profile API with is_user_follow_business field.

        IMPORTANT: User consent is required - the user must have interacted
        (clicked a quick reply or button) before we can access their profile.
        This node should be placed AFTER a quick reply or button template node.
        """
        # Refresh from database to ensure fresh data
        config = node.config or {}
        true_node_id = config.get('true_node_id')
        false_node_id = config.get('false_node_id')

        # Check if user has interacted (clicked something) - required for profile API
        has_user_interacted = self._has_user_interacted(session)

        if not has_user_interacted:
            logger.warning(
                f"Follower check requires user interaction first. "
                f"User {session.instagram_username} hasn't clicked any button yet."
            )
            self._log_action(session, 'condition_checked', node, {
                'condition': 'follower_check',
                'error': 'user_consent_required',
                'message': 'User must click a quick reply or button before follower check'
            })
            # Can't check follower status without consent - treat as not follower
            # and route to false branch
            session.update_context('is_follower', None)
            session.update_context('follower_check_error', 'user_consent_required')

            if false_node_id:
                try:
                    next_node = FlowNode.objects.get(id=false_node_id, flow=session.flow)
                    self.execute_node(session, next_node)
                except FlowNode.DoesNotExist:
                    self._complete_flow(session)
            else:
                self._complete_flow(session)
            return

        # User has interacted - we can use the Profile API
        is_follower = False
        profile_data = {}

        try:
            is_follower, profile_data = self.api_client.check_is_follower(
                session.instagram_scoped_id
            )
            logger.info(
                f"Follower check for {session.instagram_username}: "
                f"is_follower={is_follower}, profile={profile_data}"
            )
        except InstagramAPIError as e:
            logger.error(f"Error during follower check API call: {e}")
            # API error - might be consent issue or other error
            self._log_action(session, 'error', node, {
                'error': str(e),
                'error_type': 'api_error'
            })
            is_follower = False

        # Update session context with profile data
        session.update_context('is_follower', is_follower)
        if profile_data:
            session.update_context('user_profile', {
                'name': profile_data.get('name'),
                'username': profile_data.get('username'),
                'follower_count': profile_data.get('follower_count'),
                'is_verified': profile_data.get('is_verified_user', False),
                'is_business_follow_user': profile_data.get('is_business_follow_user', False)
            })

        # Update lead with profile data
        lead = CollectedLead.objects.filter(
            user=session.flow.user,
            instagram_scoped_id=session.instagram_scoped_id,
        ).first()
        if lead:
            lead.is_follower = is_follower
            if profile_data:
                profile_name = profile_data.get('name', '')
                if profile_name and not lead.name:
                    lead.name = profile_name
                lead.custom_data['follower_count'] = profile_data.get('follower_count')
                lead.custom_data['is_verified'] = profile_data.get('is_verified_user', False)
                lead.custom_data['is_business_follow_user'] = profile_data.get('is_business_follow_user', False)
            lead.save()

        self._log_action(session, 'condition_checked', node, {
            'condition': 'follower_check',
            'result': 'is_follower' if is_follower else 'not_follower',
            'username': profile_data.get('username'),
            'next_node_id': true_node_id if is_follower else false_node_id
        })

        # Route based on follower status
        if is_follower:
            logger.info(f"User {session.instagram_username} IS a follower")
            if true_node_id:
                try:
                    next_node = FlowNode.objects.get(id=true_node_id, flow=session.flow)
                    self.execute_node(session, next_node)
                except FlowNode.DoesNotExist:
                    logger.error(f"True node {true_node_id} not found")
                    self._complete_flow(session)
            else:
                self._complete_flow(session)
        else:
            logger.info(f"User {session.instagram_username} is NOT a follower")
            if false_node_id:
                try:
                    next_node = FlowNode.objects.get(id=false_node_id, flow=session.flow)
                    self.execute_node(session, next_node)
                except FlowNode.DoesNotExist:
                    logger.error(f"False node {false_node_id} not found")
                    self._complete_flow(session)
            else:
                self._complete_flow(session)

    def _handle_condition_user_interacted(self, session: FlowSession, node: FlowNode):
        """
        Handle condition_user_interacted node - checks if user has previously completed this flow.

        This enables detecting returning users (e.g., for quiz flows where the same user
        comments on multiple posts). The node branches based on whether the user has
        completed this flow before within the specified time period.

        Config:
            - true_node_id: Node to execute if user has previously completed flow (returning user)
            - false_node_id: Node to execute if user hasn't completed flow before (new user)
            - time_period: 'ever', '24h', '7d', or '30d'
        """
        from datetime import timedelta

        config = node.config or {}
        true_node_id = config.get('true_node_id')
        false_node_id = config.get('false_node_id')
        time_period = config.get('time_period', 'ever')

        # Build query for completed sessions by same user in same flow
        filters = {
            'flow': session.flow,
            'instagram_scoped_id': session.instagram_scoped_id,
            'status': 'completed'
        }

        # Add time filter based on time_period
        if time_period == '24h':
            filters['completed_at__gte'] = timezone.now() - timedelta(hours=24)
        elif time_period == '7d':
            filters['completed_at__gte'] = timezone.now() - timedelta(days=7)
        elif time_period == '30d':
            filters['completed_at__gte'] = timezone.now() - timedelta(days=30)
        # 'ever' doesn't need a time filter

        # Check if user has completed this flow before (exclude current session)
        has_interacted = FlowSession.objects.filter(**filters).exclude(pk=session.pk).exists()

        # Store result in context
        session.update_context('has_previously_interacted', has_interacted)
        session.update_context('interaction_check_time_period', time_period)

        self._log_action(session, 'condition_checked', node, {
            'condition': 'user_interacted_check',
            'result': 'returning_user' if has_interacted else 'new_user',
            'time_period': time_period,
            'next_node_id': true_node_id if has_interacted else false_node_id
        })

        # Route based on interaction status
        if has_interacted:
            logger.info(f"User {session.instagram_username} IS a returning user (completed flow before)")
            if true_node_id:
                try:
                    next_node = FlowNode.objects.get(id=true_node_id, flow=session.flow)
                    self.execute_node(session, next_node)
                except FlowNode.DoesNotExist:
                    logger.error(f"True node {true_node_id} not found")
                    self._complete_flow(session)
            else:
                self._complete_flow(session)
        else:
            logger.info(f"User {session.instagram_username} is a NEW user (hasn't completed flow before)")
            if false_node_id:
                try:
                    next_node = FlowNode.objects.get(id=false_node_id, flow=session.flow)
                    self.execute_node(session, next_node)
                except FlowNode.DoesNotExist:
                    logger.error(f"False node {false_node_id} not found")
                    self._complete_flow(session)
            else:
                self._complete_flow(session)

    def _handle_collect_data(self, session: FlowSession, node: FlowNode):
        """
        Handle collect_data node - prompts user for information.

        Sends a prompt message and waits for free-text reply.
        """
        # Deep copy config to avoid any shared reference issues
        config = copy.deepcopy(node.config) if node.config else {}
        field_type = config.get('field_type', 'custom')
        prompt_text = config.get('prompt_text', '')
        variable_name = config.get('variable_name', f'collected_{field_type}')
        field_label = config.get('field_label', '')  # For custom fields

        if not prompt_text:
            logger.warning("Collect data node has no prompt text")
            self._advance_to_next_node(session, node)
            return

        # Store which variable we're collecting
        session.context_data['_collecting_variable'] = variable_name
        session.context_data['_collecting_field_type'] = field_type
        session.context_data['_collecting_field_label'] = field_label
        session.context_data['_collecting_node_id'] = node.id
        session.save(update_fields=['context_data', 'updated_at'])

        try:
            self.api_client.send_text_dm(session.instagram_scoped_id, prompt_text)
            self._log_action(session, 'message_sent', node, {
                'prompt': prompt_text,
                'field_type': field_type,
                'variable_name': variable_name
            })
            logger.info(f"Sent data collection prompt to {session.instagram_username}")
        except InstagramAPIError as e:
            logger.error(f"Failed to send data collection prompt: {e}")
            if e.is_messaging_restricted_error():
                session.set_error("User doesn't allow message requests")
                self._log_action(session, 'dm_restricted', node, {
                    'error': str(e),
                    'reason': 'user_messaging_restricted'
                })
            else:
                session.set_error(str(e))
                self._log_action(session, 'error', node, {'error': str(e)})
            return

        # Wait for user's text reply
        session.set_waiting_for_reply()

    def _handle_ai_conversation(self, session: FlowSession, node: FlowNode):
        """
        Handle ai_conversation node - delegates to AI engine.

        This node hands off control to the AI conversation handler which:
        - Generates AI responses using the configured agent
        - Collects data according to the schema
        - Manages the conversation until goal is complete
        """
        from .ai_engine import AINodeExecutor
        from core.subscription_utils import check_feature_access

        logger.info(f"Starting AI conversation for session {session.id}")

        # Check if user has AI feature access
        user = session.flow.user
        can_access, message, _ = check_feature_access(user, 'ai_social_agent')
        if not can_access:
            logger.warning(f"User {user.id} does not have AI feature access, skipping AI node")
            session.set_error("AI feature not available on current plan")
            self._log_action(session, 'feature_blocked', node, {'feature': 'ai_social_agent'})
            # Try to advance to next node instead of blocking the flow
            if node.next_node:
                self.execute_node(session, node.next_node)
            else:
                self._complete_flow(session)
            return

        # Execute AI node (sends first message)
        result = AINodeExecutor.execute_ai_node(session, node)

        if not result['success']:
            logger.error(f"AI node failed: {result['message']}")
            session.set_error(result['message'])
            self._log_action(session, 'error', node, {'error': result['message']})
            return

        # Send the AI-generated first message via Instagram
        try:
            if session.trigger_comment_id and not self._has_sent_dm(session):
                self.api_client.send_dm_to_commenter(
                    session.trigger_comment_id,
                    result['message']
                )
            else:
                self.api_client.send_text_dm(
                    session.instagram_scoped_id,
                    result['message']
                )

            self._log_action(session, 'message_sent', node, {
                'text': result['message'],
                'ai_generated': True
            })
            logger.info(f"Sent AI first message to {session.instagram_username}")

        except InstagramAPIError as e:
            logger.error(f"Failed to send AI message: {e}")
            if e.is_messaging_restricted_error():
                session.set_error("User doesn't allow message requests")
                self._log_action(session, 'dm_restricted', node, {
                    'error': str(e),
                    'reason': 'user_messaging_restricted'
                })
            else:
                session.set_error(str(e))
                self._log_action(session, 'error', node, {'error': str(e)})
            return

        # Mark session as waiting for AI conversation reply
        session.status = 'waiting_reply'
        session.context_data['_ai_conversation'] = True
        session.context_data['_ai_node_id'] = node.id
        session.save(update_fields=['status', 'context_data', 'updated_at'])

    def handle_ai_text_reply(
        self,
        session: FlowSession,
        text: str,
        message_id: Optional[str] = None
    ):
        """
        Handle text reply during AI conversation.

        Args:
            session: The flow session
            text: The user's text message
            message_id: Optional message ID for deduplication
        """
        from .ai_engine import AINodeExecutor
        from core.subscription_utils import check_feature_access

        logger.info(f"Handling AI text reply for session {session.id}: {text[:50]}...")

        # Check if user still has AI feature access
        user = session.flow.user
        can_access, _, _ = check_feature_access(user, 'ai_social_agent')
        if not can_access:
            logger.warning(f"User {user.id} lost AI feature access during conversation")
            # Clear AI state and complete the flow gracefully
            session.context_data.pop('_ai_conversation', None)
            session.context_data.pop('_ai_node_id', None)
            session.save(update_fields=['context_data', 'updated_at'])
            self._complete_flow(session)
            return

        # Process through AI engine
        result = AINodeExecutor.handle_ai_message(session, text, message_id or '')

        if not result['success']:
            logger.error(f"AI response failed: {result.get('error', 'Unknown error')}")
            return

        # Send AI response via Instagram
        if result['response']:
            try:
                self.api_client.send_text_dm(session.instagram_scoped_id, result['response'])
                self._log_action(session, 'message_sent', session.current_node, {
                    'text': result['response'],
                    'ai_generated': True
                })
            except InstagramAPIError as e:
                logger.error(f"Failed to send AI response: {e}")
                self._log_action(session, 'error', session.current_node, {'error': str(e)})
                return

        # Check if AI conversation is complete
        if not result['should_continue_ai']:
            # Merge collected data into session context for use by subsequent nodes
            if result.get('collected_data'):
                session.context_data.update(result['collected_data'])
                logger.info(f"Merged AI collected data into context: {list(result['collected_data'].keys())}")

            # Clear AI conversation state flags
            session.context_data.pop('_ai_conversation', None)
            session.context_data.pop('_ai_node_id', None)
            session.save(update_fields=['context_data', 'updated_at'])

            if result['should_complete_flow']:
                self._complete_flow(session)
            elif result['next_node_id']:
                try:
                    next_node = FlowNode.objects.get(id=result['next_node_id'])
                    session.status = 'active'
                    session.save(update_fields=['status', 'updated_at'])
                    self.execute_node(session, next_node)
                except FlowNode.DoesNotExist:
                    logger.error(f"Next node {result['next_node_id']} not found")
                    self._complete_flow(session)
            else:
                # No next node specified, try to advance normally
                if session.current_node and session.current_node.next_node:
                    session.status = 'active'
                    session.save(update_fields=['status', 'updated_at'])
                    self.execute_node(session, session.current_node.next_node)
                else:
                    self._complete_flow(session)

    # =========================================================================
    # User Response Handling
    # =========================================================================

    def handle_quick_reply_click(
        self,
        session: FlowSession,
        payload: str,
        message_id: Optional[str] = None
    ):
        """
        Handle when a user clicks a quick reply button.

        Args:
            session: The flow session
            payload: The quick reply payload (format: flow_{id}_node_{id}_opt_{payload})
            message_id: Optional message ID for deduplication
        """
        logger.info(f"Handling quick reply click for session {session.id}: {payload}")

        # Parse payload to find the option
        # Format: flow_{session_id}_node_{node_id}_opt_{option_payload}
        parts = payload.split('_opt_')
        if len(parts) != 2:
            logger.error(f"Invalid payload format: {payload}")
            return

        option_payload = parts[1]
        node_info = parts[0]  # flow_{session_id}_node_{node_id}

        # Extract node_id from node_info
        # Format: flow_{session_id}_node_{node_id}
        try:
            node_parts = node_info.split('_node_')
            if len(node_parts) == 2:
                node_id = int(node_parts[1])
                qr_node = FlowNode.objects.get(id=node_id, flow=session.flow)
            else:
                qr_node = FlowNode.objects.get(id=session.current_node_id, flow=session.flow) if session.current_node_id else session.current_node
        except (ValueError, FlowNode.DoesNotExist):
            logger.warning(f"Could not extract node_id from payload, using current_node")
            qr_node = FlowNode.objects.get(id=session.current_node_id, flow=session.flow) if session.current_node_id else session.current_node

        # Find the QuickReplyOption using the correct node
        try:
            option = QuickReplyOption.objects.get(
                node=qr_node,
                payload=option_payload
            )
        except QuickReplyOption.DoesNotExist:
            logger.error(f"QuickReplyOption not found for node {qr_node.id if qr_node else 'None'}, payload: {option_payload}")
            return

        # Log with the title included
        self._log_action(session, 'quick_reply_received', session.current_node, {
            'payload': payload,
            'title': option.title,
            'message_id': message_id
        })

        # User interacted — check and store follower status on the lead
        self._check_and_store_follower_status(session)

        # If option has a target node, execute it
        if option.target_node:
            session.status = 'active'
            session.save(update_fields=['status', 'updated_at'])
            self.execute_node(session, option.target_node)
        else:
            # No target node, advance to next sequential node from the QR node
            self._advance_to_next_node(session, qr_node)

    def handle_button_postback(
        self,
        session: FlowSession,
        payload: str,
        message_id: Optional[str] = None
    ):
        """
        Handle when a user clicks a button template postback button.

        Args:
            session: The flow session
            payload: The postback payload (format: flow_{id}_node_{id}_btn_{payload})
            message_id: Optional message ID for deduplication
        """
        logger.info(f"Handling button postback for session {session.id}: {payload}")

        # Parse payload to extract node info
        # Format: flow_{session_id}_node_{node_id}_btn_{button_payload}
        parts = payload.split('_btn_')
        if len(parts) != 2:
            logger.error(f"Invalid button postback payload format: {payload}")
            return

        button_payload = parts[1]
        node_info = parts[0]  # flow_{session_id}_node_{node_id}

        # Extract node_id from node_info
        try:
            node_parts = node_info.split('_node_')
            if len(node_parts) == 2:
                node_id = int(node_parts[1])
                btn_node = FlowNode.objects.get(id=node_id, flow=session.flow)
            else:
                btn_node = FlowNode.objects.get(id=session.current_node_id, flow=session.flow) if session.current_node_id else session.current_node
        except (ValueError, FlowNode.DoesNotExist):
            logger.warning(f"Could not extract node_id from payload, using current_node")
            btn_node = FlowNode.objects.get(id=session.current_node_id, flow=session.flow) if session.current_node_id else session.current_node

        # Store the clicked button payload in context for potential use
        session.context_data['_last_button_clicked'] = button_payload
        session.status = 'active'
        session.save(update_fields=['context_data', 'status', 'updated_at'])

        # Find the button config to check for branching (target_node_id)
        target_node = None
        button_title = None
        if btn_node and btn_node.config:
            buttons = btn_node.config.get('buttons', [])
            for button in buttons:
                btn_type = button.get('type', 'postback')
                if button.get('payload') == button_payload and btn_type == 'postback':
                    button_title = button.get('title')
                    target_node_id = button.get('target_node_id')
                    if target_node_id:
                        try:
                            target_node = FlowNode.objects.get(id=target_node_id, flow=session.flow)
                        except FlowNode.DoesNotExist:
                            logger.warning(f"Target node {target_node_id} not found, advancing to next")
                    break

        # Log with the title included
        self._log_action(session, 'quick_reply_received', session.current_node, {
            'payload': payload,
            'title': button_title,
            'type': 'button_postback',
            'message_id': message_id
        })

        # User interacted — check and store follower status on the lead
        self._check_and_store_follower_status(session)

        # If button has a target node, execute it (branching)
        if target_node:
            self.execute_node(session, target_node)
        else:
            # No target node, advance to next sequential node
            self._advance_to_next_node(session, btn_node)

    def handle_text_reply(
        self,
        session: FlowSession,
        text: str,
        message_id: Optional[str] = None
    ):
        """
        Handle when a user sends a text message (for data collection or AI conversation).

        Args:
            session: The flow session
            text: The user's text message
            message_id: Optional message ID for deduplication
        """
        logger.info(f"Handling text reply for session {session.id}: {text[:50]}...")

        # Check if this is an AI conversation - delegate to AI handler
        if session.context_data.get('_ai_conversation'):
            self.handle_ai_text_reply(session, text, message_id)
            return

        # Check if we're collecting data (existing flow)
        variable_name = session.context_data.get('_collecting_variable')
        field_type = session.context_data.get('_collecting_field_type')
        field_label = session.context_data.get('_collecting_field_label', '')
        node_id = session.context_data.get('_collecting_node_id')

        if not variable_name or not node_id:
            logger.warning("Received text reply but not collecting data")
            return

        try:
            node = FlowNode.objects.get(id=node_id)
        except FlowNode.DoesNotExist:
            logger.error(f"Collecting node {node_id} not found")
            return

        # Validate the response
        is_valid, cleaned_value = self._validate_collected_data(text, field_type, node.config)

        if not is_valid:
            # Send error message and wait again
            error_prompt = self._get_validation_error_message(field_type, node.config)
            try:
                self.api_client.send_text_dm(session.instagram_scoped_id, error_prompt)
            except InstagramAPIError:
                pass
            return

        # Store the collected value
        session.context_data[variable_name] = cleaned_value

        # Clean up collection state
        session.context_data.pop('_collecting_variable', None)
        session.context_data.pop('_collecting_field_type', None)
        session.context_data.pop('_collecting_field_label', None)
        session.context_data.pop('_collecting_node_id', None)
        session.save(update_fields=['context_data', 'updated_at'])

        self._log_action(session, 'data_collected', node, {
            'field_type': field_type,
            'variable_name': variable_name,
            'field_label': field_label,
            'value': cleaned_value if field_type != 'phone' else '***',
            'message_id': message_id
        })

        # Also log text_reply_received for deduplication
        self._log_action(session, 'text_reply_received', node, {
            'message_id': message_id
        })

        # Update or create lead record
        self._update_lead_record(session, field_type, cleaned_value, variable_name, field_label)

        # Continue to next node
        session.status = 'active'
        session.save(update_fields=['status', 'updated_at'])
        self._advance_to_next_node(session, node)

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _can_create_lead(self, user) -> bool:
        """Check if user is within their lead_capture feature limit."""
        if user.is_staff:
            return True
        subscription = get_user_subscription(user)
        if not subscription or not subscription.plan.has_feature('lead_capture'):
            return False
        limit = subscription.plan.get_feature_limit('lead_capture', default=None)
        if limit is None:
            return True  # No limit set = unlimited
        current_count = CollectedLead.objects.filter(user=user).count()
        return current_count < limit

    def _check_and_store_follower_status(self, session: FlowSession):
        """Check follower status via Profile API and store on session + lead.

        Should be called after user interaction (quick reply click or button
        postback) which grants consent for the Profile API.
        """
        if session.context_data.get('is_follower') is not None:
            return  # Already checked

        try:
            is_follower, profile_data = self.api_client.check_is_follower(
                session.instagram_scoped_id
            )
            session.update_context('is_follower', is_follower)
            if profile_data:
                session.update_context('user_profile', {
                    'name': profile_data.get('name'),
                    'username': profile_data.get('username'),
                    'follower_count': profile_data.get('follower_count'),
                    'is_verified': profile_data.get('is_verified_user', False),
                    'is_business_follow_user': profile_data.get('is_business_follow_user', False)
                })

            # Update lead with profile data
            lead = CollectedLead.objects.filter(
                user=session.flow.user,
                instagram_scoped_id=session.instagram_scoped_id,
            ).first()
            if lead:
                lead.is_follower = is_follower
                if profile_data:
                    profile_name = profile_data.get('name', '')
                    if profile_name and not lead.name:
                        lead.name = profile_name
                    lead.custom_data['follower_count'] = profile_data.get('follower_count')
                    lead.custom_data['is_verified'] = profile_data.get('is_verified_user', False)
                    lead.custom_data['is_business_follow_user'] = profile_data.get('is_business_follow_user', False)
                lead.save()

        except InstagramAPIError as e:
            logger.warning(f"Could not check follower status for {session.instagram_username}: {e}")

    def _advance_to_next_node(self, session: FlowSession, current_node: FlowNode):
        """Advance to the next node in the flow."""
        # First check if current node has explicit next_node
        next_node = current_node.next_node

        # If not, check if this node is a branch target
        # Branch targets should NOT auto-advance by order (they're endpoints of branches)
        if not next_node:
            is_branch_target = self._is_branch_target(current_node)

            if is_branch_target:
                # This node is a branch target - don't find next by order
                # Complete the flow (this branch is done)
                logger.info(f"Node {current_node.id} is a branch target with no next_node, completing flow")
                self._complete_flow(session)
                return
            else:
                # Not a branch target - find next by order (linear flow)
                next_nodes = FlowNode.objects.filter(
                    flow=session.flow,
                    order__gt=current_node.order
                ).order_by('order')
                next_node = next_nodes.first()

        if next_node:
            self.execute_node(session, next_node)
        else:
            self._complete_flow(session)

    def _get_branch_targets(self, flow) -> set:
        """Compute and cache the set of all branch-target node IDs for a flow.
        Replaces 4 separate queries per call with 2 queries total, cached for reuse."""
        if flow.id in self._branch_targets:
            return self._branch_targets[flow.id]

        targets = set()

        # 1 query: get all nodes for this flow (covers next_node, conditions, buttons)
        all_nodes = FlowNode.objects.filter(flow=flow)
        for n in all_nodes:
            # Nodes connected via next_node
            if n.next_node_id:
                targets.add(n.next_node_id)

            # Condition node targets (true/false branches)
            if n.node_type in ('condition_follower', 'condition_user_interacted'):
                config = n.config or {}
                if config.get('true_node_id'):
                    targets.add(config['true_node_id'])
                if config.get('false_node_id'):
                    targets.add(config['false_node_id'])

            # Button template targets
            if n.node_type == 'message_button_template':
                config = n.config or {}
                for button in config.get('buttons', []):
                    if button.get('target_node_id'):
                        targets.add(button['target_node_id'])

        # 1 query: quick reply option targets
        qr_target_ids = QuickReplyOption.objects.filter(
            node__flow=flow,
            target_node__isnull=False
        ).values_list('target_node_id', flat=True)
        targets.update(qr_target_ids)

        self._branch_targets[flow.id] = targets
        return targets

    def _is_branch_target(self, node: FlowNode) -> bool:
        """
        Check if a node is explicitly connected from another node (cached).
        Uses precomputed branch target set instead of 4 separate queries per call.
        """
        return node.id in self._get_branch_targets(node.flow)

    def _complete_flow(self, session: FlowSession):
        """Mark the flow as completed."""
        logger.info(f"Completing flow for session {session.id}")
        session.complete()
        self._log_action(session, 'flow_completed')

    def _has_sent_dm(self, session: FlowSession) -> bool:
        """Check if we've already sent a DM in this session."""
        return FlowExecutionLog.objects.filter(
            session=session,
            action='message_sent'
        ).exists()

    def _has_user_interacted(self, session: FlowSession) -> bool:
        """
        Check if the user has interacted with the flow (clicked a button).

        User interaction (clicking quick reply or button template) grants
        consent to access their profile via the User Profile API.

        Returns:
            True if user has clicked a quick reply or button, False otherwise
        """
        return FlowExecutionLog.objects.filter(
            session=session,
            action='quick_reply_received'
        ).exists()

    def _substitute_variables(self, text: str, context: dict) -> str:
        """Substitute {variable_name} placeholders in text."""
        for key, value in context.items():
            if not key.startswith('_'):  # Skip internal variables
                text = text.replace(f'{{{key}}}', str(value))
        return text

    def _validate_collected_data(
        self,
        value: str,
        field_type: str,
        config: dict
    ) -> Tuple[bool, str]:
        """
        Validate collected data based on field type.

        Returns:
            Tuple of (is_valid, cleaned_value)
        """
        value = value.strip()

        if field_type == 'email':
            email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
            if re.match(email_regex, value):
                return True, value.lower()
            return False, value

        elif field_type == 'phone':
            # Remove common formatting, keep digits and +
            cleaned = re.sub(r'[^\d+]', '', value)
            if len(cleaned) >= 7:
                return True, cleaned
            return False, value

        elif field_type == 'name':
            # Accept most text for names
            if len(value) >= 1 and len(value) <= 100:
                return True, value.title()
            return False, value

        else:
            # Custom field - check validation regex if provided
            validation_regex = config.get('validation')
            if validation_regex:
                if re.match(validation_regex, value):
                    return True, value
                return False, value
            # No validation, accept any non-empty value
            return bool(value), value

    def _get_validation_error_message(self, field_type: str, config: dict) -> str:
        """Get error message for invalid data."""
        error_messages = {
            'email': "That doesn't look like a valid email. Please enter a valid email address.",
            'phone': "Please enter a valid phone number.",
            'name': "Please enter your name.",
        }
        return config.get('error_message') or error_messages.get(field_type, "Please try again.")

    def _update_lead_record(
        self,
        session: FlowSession,
        field_type: str,
        value: str,
        variable_name: str = None,
        field_label: str = None
    ):
        """Update or create lead record with collected data."""
        # Find existing lead or create if within limit
        lead = CollectedLead.objects.filter(
            user=session.flow.user,
            instagram_scoped_id=session.instagram_scoped_id,
        ).first()

        if not lead:
            if not self._can_create_lead(session.flow.user):
                logger.info(f"Lead capture limit reached for user {session.flow.user.id}, skipping lead creation")
                return
            lead = CollectedLead.objects.create(
                user=session.flow.user,
                instagram_scoped_id=session.instagram_scoped_id,
                flow=session.flow,
                session=session,
                instagram_username=session.instagram_username,
                is_follower=session.context_data.get('is_follower', False),
            )

        # Always keep lead fresh with latest flow, session, and username
        lead.flow = session.flow
        lead.session = session
        if lead.instagram_username != session.instagram_username:
            lead.instagram_username = session.instagram_username

        # Update the appropriate field
        if field_type == 'name':
            lead.name = value
        elif field_type == 'email':
            lead.email = value
        elif field_type == 'phone':
            lead.phone = value
        else:
            # Custom field - store with label for display
            key = variable_name or field_type
            lead.custom_data[key] = {
                'value': value,
                'label': field_label or key
            }

        lead.is_follower = session.context_data.get('is_follower', lead.is_follower)
        lead.save()


def find_matching_flow(
    user,
    post_id: str,
    comment_text: str
) -> Optional[DMFlow]:
    """
    Find the first matching active flow for a comment.

    Args:
        user: The user who owns the Instagram account
        post_id: The Instagram post ID
        comment_text: The comment text

    Returns:
        The matching DMFlow or None
    """
    # Get all active flows for this user
    flows = DMFlow.objects.filter(
        user=user,
        is_active=True
    ).order_by('-created_at')

    for flow in flows:
        # Check post ID match if specified
        if flow.instagram_post_id and flow.instagram_post_id != post_id:
            continue

        # Check if comment matches flow's trigger
        if flow.matches_comment(comment_text):
            return flow

    return None


def find_session_for_message(
    igsid: str,
    user
) -> Optional[FlowSession]:
    """
    Find an active/waiting session for a user based on their IGSID.

    Args:
        igsid: The Instagram-scoped ID
        user: The user who owns the Instagram account

    Returns:
        The active FlowSession or None
    """
    return FlowSession.objects.filter(
        instagram_scoped_id=igsid,
        flow__user=user,
        status__in=['active', 'waiting_reply']
    ).order_by('-updated_at').first()


def parse_quick_reply_payload(payload: str) -> Optional[Dict[str, Any]]:
    """
    Parse a quick reply or button postback payload to extract session, node, and option info.

    Args:
        payload: The payload string
            Quick reply format: flow_{session_id}_node_{node_id}_opt_{payload}
            Button postback format: flow_{session_id}_node_{node_id}_btn_{payload}

    Returns:
        Dict with session_id, node_id, option_payload, and payload_type or None if invalid
    """
    try:
        if not payload.startswith('flow_'):
            return None

        # Determine payload type and split accordingly
        if '_opt_' in payload:
            delimiter = '_opt_'
            payload_type = 'quick_reply'
        elif '_btn_' in payload:
            delimiter = '_btn_'
            payload_type = 'button_postback'
        else:
            return None

        parts = payload.split(delimiter)
        if len(parts) != 2:
            return None

        prefix = parts[0]  # flow_{session_id}_node_{node_id}
        option_payload = parts[1]

        # Parse prefix: flow_{session_id}_node_{node_id}
        prefix_parts = prefix.split('_')
        if len(prefix_parts) < 4:
            return None

        session_id = int(prefix_parts[1])
        node_id = int(prefix_parts[3])

        return {
            'session_id': session_id,
            'node_id': node_id,
            'option_payload': option_payload,
            'payload_type': payload_type
        }
    except (ValueError, IndexError):
        return None
