import json
import logging
import asyncio
import base64
import websockets
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone

logger = logging.getLogger(__name__)

OPENAI_REALTIME_URL = "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview"


class RoleplayConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for voice roleplay sessions using OpenAI Realtime API"""

    async def connect(self):
        """Handle WebSocket connection"""
        self.session_id = self.scope['url_route']['kwargs']['session_id']
        self.user = self.scope['user']
        self.openai_ws = None
        self.openai_task = None

        # Check if user is authenticated
        if not self.user.is_authenticated:
            await self.close()
            return

        # Validate session
        session = await self.get_session()
        if not session or session.user_id != self.user.id:
            await self.close()
            return

        if session.status != 'in_progress':
            await self.close()
            return

        self.session = session
        self.bot = await self.get_bot()
        self.credits_per_minute = self.bot.required_credits
        self.start_time = timezone.now()
        self.total_credits_used = 0
        self.transcript = []
        self.openai_ready = False

        # Check if user has enough credits before accepting
        credits = await self.get_user_credits()
        if credits < self.credits_per_minute:
            await self.accept()
            await self.send_error(
                "Insufficient credits. Please buy more credits to start.",
                redirect="/roleplay/credits/"
            )
            await self.close()
            return

        # Deduct first minute's credits upfront
        await self.deduct_credits(self.credits_per_minute)
        self.total_credits_used = self.credits_per_minute
        new_balance = credits - self.credits_per_minute

        # Accept connection
        await self.accept()

        # Send initial balance update
        await self.send(text_data=json.dumps({
            'type': 'credits_update',
            'credits': new_balance
        }))

        # Connect to OpenAI Realtime API
        connected = await self.connect_to_openai()
        if not connected:
            await self.send_error("Failed to connect to AI service. Please try again.")
            await self.close()
            return

        # Start credit deduction timer (for subsequent minutes)
        self.credit_task = asyncio.create_task(self.credit_deduction_loop())

        # Start listening to OpenAI responses
        self.openai_task = asyncio.create_task(self.listen_to_openai())

        # Send ready message
        await self.send_text("Connected! Start speaking to begin the conversation.")

    async def connect_to_openai(self):
        """Connect to OpenAI Realtime API"""
        try:
            from core.models import Configuration

            api_key = await database_sync_to_async(Configuration.get_value)('openai_api_key')
            if not api_key:
                logger.error("OpenAI API key not configured")
                return False

            headers = [
                ("Authorization", f"Bearer {api_key}"),
                ("OpenAI-Beta", "realtime=v1")
            ]

            self.openai_ws = await websockets.connect(
                OPENAI_REALTIME_URL,
                additional_headers=headers
            )

            logger.info(f"Connected to OpenAI Realtime API for session {self.session_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to OpenAI Realtime: {e}")
            return False

    async def configure_openai_session(self):
        """Configure the OpenAI Realtime session after connection"""
        try:
            session_config = {
                "type": "session.update",
                "session": {
                    "modalities": ["text", "audio"],
                    "instructions": self.bot.system_prompt,
                    "voice": self.bot.voice,
                    "input_audio_format": "pcm16",
                    "output_audio_format": "pcm16",
                    "input_audio_transcription": {
                        "model": "whisper-1"
                    },
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.5,
                        "prefix_padding_ms": 300,
                        "silence_duration_ms": 500
                    }
                }
            }

            # Apply custom configuration if any
            if self.bot.custom_configuration:
                if 'temperature' in self.bot.custom_configuration:
                    session_config['session']['temperature'] = self.bot.custom_configuration['temperature']

            await self.openai_ws.send(json.dumps(session_config))
            logger.info(f"Sent session configuration: {session_config}")

        except Exception as e:
            logger.error(f"Error configuring OpenAI session: {e}")

    async def listen_to_openai(self):
        """Listen for messages from OpenAI Realtime API"""
        try:
            async for message in self.openai_ws:
                try:
                    data = json.loads(message)
                    await self.handle_openai_message(data)
                except json.JSONDecodeError:
                    logger.error("Invalid JSON from OpenAI")
                except Exception as e:
                    logger.error(f"Error handling OpenAI message: {e}")

        except websockets.exceptions.ConnectionClosed:
            logger.info("OpenAI WebSocket closed")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in OpenAI listener: {e}")

    async def handle_openai_message(self, data):
        """Handle messages from OpenAI Realtime API"""
        event_type = data.get('type', '')

        # Log all events for debugging
        logger.info(f"OpenAI event: {event_type}")

        if event_type == 'session.created':
            logger.info(f"OpenAI session created: {data}")
            # Send session update after creation
            await self.configure_openai_session()

        elif event_type == 'session.updated':
            logger.info("OpenAI session updated - ready to receive audio")
            self.openai_ready = True
            await self.send(text_data=json.dumps({'type': 'session_ready'}))

        elif event_type == 'response.audio.delta':
            # Forward audio to client
            audio_delta = data.get('delta', '')
            if audio_delta:
                await self.send(text_data=json.dumps({
                    'type': 'audio_delta',
                    'delta': audio_delta
                }))

        elif event_type == 'response.audio.done':
            # Audio response complete
            await self.send(text_data=json.dumps({
                'type': 'audio_done'
            }))

        elif event_type == 'response.audio_transcript.delta':
            # AI is speaking - send transcript
            transcript = data.get('delta', '')
            if transcript:
                await self.send(text_data=json.dumps({
                    'type': 'assistant_transcript_delta',
                    'delta': transcript
                }))

        elif event_type == 'response.audio_transcript.done':
            # Full AI transcript
            transcript = data.get('transcript', '')
            if transcript:
                self.transcript.append({'role': 'assistant', 'content': transcript})
                await self.send(text_data=json.dumps({
                    'type': 'assistant_transcript',
                    'text': transcript
                }))

        elif event_type == 'conversation.item.input_audio_transcription.completed':
            # User speech transcribed
            transcript = data.get('transcript', '')
            if transcript:
                self.transcript.append({'role': 'user', 'content': transcript})
                await self.send(text_data=json.dumps({
                    'type': 'user_transcript',
                    'text': transcript
                }))

        elif event_type == 'input_audio_buffer.speech_started':
            # User started speaking
            await self.send(text_data=json.dumps({
                'type': 'speech_started'
            }))

        elif event_type == 'input_audio_buffer.speech_stopped':
            # User stopped speaking
            await self.send(text_data=json.dumps({
                'type': 'speech_stopped'
            }))

        elif event_type == 'response.created':
            logger.info("Response creation started")

        elif event_type == 'response.output_item.added':
            logger.info(f"Output item added: {data}")

        elif event_type == 'response.content_part.added':
            logger.info(f"Content part added: {data}")

        elif event_type == 'response.done':
            response = data.get('response', {})
            status = response.get('status')
            output = response.get('output', [])
            logger.info(f"Response completed - status: {status}, output items: {len(output)}")
            if response.get('status_details'):
                logger.info(f"Status details: {response.get('status_details')}")
            voiceIndicator_update = {'type': 'response_done'}
            await self.send(text_data=json.dumps(voiceIndicator_update))

        elif event_type == 'error':
            error = data.get('error', {})
            logger.error(f"OpenAI Realtime error: {error}")
            logger.error(f"Full error data: {data}")
            await self.send_error(f"AI error: {error.get('message', 'Unknown error')}")

        else:
            # Log unhandled events
            logger.info(f"Unhandled event type: {event_type}")

    async def disconnect(self, close_code):
        """Handle WebSocket disconnection"""
        # Cancel tasks
        if hasattr(self, 'credit_task') and self.credit_task:
            self.credit_task.cancel()

        if hasattr(self, 'openai_task') and self.openai_task:
            self.openai_task.cancel()

        # Close OpenAI connection
        if hasattr(self, 'openai_ws') and self.openai_ws:
            await self.openai_ws.close()

        # Save transcript and update session
        if hasattr(self, 'session'):
            duration = (timezone.now() - self.start_time).total_seconds()
            transcript_text = "\n".join([
                f"{'User' if t['role'] == 'user' else 'Bot'}: {t['content']}"
                for t in self.transcript
            ])
            await self.update_session(
                duration_seconds=int(duration),
                credits_used=self.total_credits_used,
                transcript=transcript_text,
                status='completed',
                completed_at=timezone.now()
            )

    async def receive(self, text_data):
        """Handle incoming WebSocket messages from client"""
        try:
            data = json.loads(text_data)
            msg_type = data.get('type')

            if msg_type == 'audio':
                # Forward audio to OpenAI
                await self.forward_audio_to_openai(data.get('audio', ''))

            elif msg_type == 'audio_commit':
                # Commit the audio buffer (user finished speaking)
                if self.openai_ws:
                    await self.openai_ws.send(json.dumps({
                        "type": "input_audio_buffer.commit"
                    }))

            elif msg_type == 'audio_clear':
                # Clear audio buffer
                if self.openai_ws:
                    await self.openai_ws.send(json.dumps({
                        "type": "input_audio_buffer.clear"
                    }))

            elif msg_type == 'interrupt':
                # Interrupt current response
                if self.openai_ws:
                    await self.openai_ws.send(json.dumps({
                        "type": "response.cancel"
                    }))

        except json.JSONDecodeError:
            logger.error("Invalid JSON received from client")
        except Exception as e:
            logger.error(f"Error processing client message: {e}")

    async def forward_audio_to_openai(self, audio_base64):
        """Forward audio chunk to OpenAI Realtime API"""
        if not self.openai_ws or not audio_base64:
            return

        if not self.openai_ready:
            logger.debug("OpenAI session not ready yet, skipping audio chunk")
            return

        try:
            await self.openai_ws.send(json.dumps({
                "type": "input_audio_buffer.append",
                "audio": audio_base64
            }))
            # Log occasionally (every ~100 chunks) to avoid spam
            if not hasattr(self, '_audio_chunk_count'):
                self._audio_chunk_count = 0
            self._audio_chunk_count += 1
            if self._audio_chunk_count % 100 == 1:
                logger.info(f"Sending audio chunk #{self._audio_chunk_count}, size: {len(audio_base64)}")
        except Exception as e:
            logger.error(f"Error forwarding audio to OpenAI: {e}")

    async def credit_deduction_loop(self):
        """Deduct credits every minute"""
        while True:
            await asyncio.sleep(60)

            try:
                credits = await self.get_user_credits()

                if credits < self.credits_per_minute:
                    await self.send_error(
                        "Your credits have run out. Session ending.",
                        redirect="/roleplay/credits/"
                    )
                    await self.close()
                    return

                await self.deduct_credits(self.credits_per_minute)
                self.total_credits_used += self.credits_per_minute

                new_balance = credits - self.credits_per_minute
                await self.send(text_data=json.dumps({
                    'type': 'credits_update',
                    'credits': new_balance
                }))

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in credit deduction: {e}")

    async def send_text(self, text):
        """Send text message to client"""
        await self.send(text_data=json.dumps({
            'type': 'text',
            'text': text
        }))

    async def send_error(self, message, redirect=None):
        """Send error message to client"""
        data = {
            'type': 'error',
            'message': message
        }
        if redirect:
            data['redirect'] = redirect
        await self.send(text_data=json.dumps(data))

    @database_sync_to_async
    def get_session(self):
        """Get session from database"""
        from .models import RoleplaySession
        try:
            return RoleplaySession.objects.select_related('bot').get(id=self.session_id)
        except RoleplaySession.DoesNotExist:
            return None

    @database_sync_to_async
    def get_bot(self):
        """Get bot from session"""
        return self.session.bot

    @database_sync_to_async
    def get_user_credits(self):
        """Get user's credit balance"""
        if hasattr(self.user, 'profile'):
            self.user.profile.refresh_from_db()
            return self.user.profile.credits
        return 0

    @database_sync_to_async
    def deduct_credits(self, amount):
        """Deduct credits from user"""
        if hasattr(self.user, 'profile'):
            self.user.profile.deduct_credits(amount)

    @database_sync_to_async
    def update_session(self, **kwargs):
        """Update session in database"""
        from .models import RoleplaySession
        RoleplaySession.objects.filter(id=self.session_id).update(**kwargs)
