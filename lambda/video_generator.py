"""
Video generator for quiz export to Instagram Reels format.
Adapted for AWS Lambda execution with fonts from /opt/fonts layer.
Generates vertical videos (1080x1920) with questions, options, timer, and answer reveal.
"""
import os
import tempfile
import shutil
import requests
from PIL import Image, ImageDraw, ImageFont
from moviepy import ImageClip, AudioFileClip, concatenate_videoclips
from moviepy.audio.fx import AudioLoop, MultiplyVolume
import numpy as np


class QuizVideoGenerator:
    """Generates vertical quiz videos for social media"""

    # Video dimensions (9:16 aspect ratio for Instagram Reels)
    WIDTH = 1080
    HEIGHT = 1920
    FPS = 24

    # Timing (in seconds)
    QUESTION_DURATION = 10
    ANSWER_REVEAL_DURATION = 3
    INTRO_DURATION = 3
    PRE_OUTRO_DURATION = 3
    OUTRO_DURATION = 2

    # Default Colors (Dark Purple theme)
    DEFAULT_COLORS = {
        'bg_color': (18, 18, 18),  # Mat black
        'text_color': (255, 255, 255),  # White
        'accent_color': (138, 43, 226),  # Purple accent
        'correct_color': (0, 200, 83),  # Vibrant green
        'wrong_color': (239, 68, 68),  # Red for wrong (during reveal)
        'option_bg': (38, 38, 38),  # Dark grey for options
        'option_text': (240, 240, 240),  # Light text on dark
        'timer_bg': (75, 0, 130),  # Deep purple for timer
        'muted_text': (156, 163, 175),  # Grey for secondary text
        'card_bg': (28, 28, 30),  # Slightly lighter than bg for cards
    }

    def __init__(self, handle_name="@maedix-q", audio_url=None, audio_volume=0.3,
                 intro_text=None, intro_audio_url=None, intro_audio_volume=0.5,
                 pre_outro_text=None, template_config=None, quiz_heading=None,
                 answer_reveal_audio_url=None, answer_reveal_audio_volume=0.5):
        self.temp_dir = tempfile.mkdtemp()
        self._font_cache = {}
        self.handle_name = handle_name
        self.audio_url = audio_url
        self.audio_volume = audio_volume
        self._audio_path = None
        # Intro settings
        self.intro_text = intro_text  # Custom intro text (None = no intro)
        self.intro_audio_url = intro_audio_url
        self.intro_audio_volume = intro_audio_volume
        self._intro_audio_path = None
        # Pre-outro settings (call-to-action before outro)
        self.pre_outro_text = pre_outro_text
        # Quiz heading displayed above timer during questions
        self.quiz_heading = quiz_heading
        # Answer reveal audio settings
        self.answer_reveal_audio_url = answer_reveal_audio_url
        self.answer_reveal_audio_volume = answer_reveal_audio_volume
        self._answer_reveal_audio_path = None
        # Load template colors
        self._load_template_colors(template_config)

    def _load_template_colors(self, template_config):
        """Load colors from template config or use defaults"""
        colors = {}
        if template_config and 'colors' in template_config:
            colors = template_config['colors']

        # Set instance color variables from config or defaults
        self.BG_COLOR = tuple(colors.get('bg_color', self.DEFAULT_COLORS['bg_color']))
        self.TEXT_COLOR = tuple(colors.get('text_color', self.DEFAULT_COLORS['text_color']))
        self.ACCENT_COLOR = tuple(colors.get('accent_color', self.DEFAULT_COLORS['accent_color']))
        self.CORRECT_COLOR = tuple(colors.get('correct_color', self.DEFAULT_COLORS['correct_color']))
        self.WRONG_COLOR = tuple(colors.get('wrong_color', self.DEFAULT_COLORS['wrong_color']))
        self.OPTION_BG = tuple(colors.get('option_bg', self.DEFAULT_COLORS['option_bg']))
        self.OPTION_TEXT = tuple(colors.get('option_text', self.DEFAULT_COLORS['option_text']))
        self.TIMER_BG = tuple(colors.get('timer_bg', self.DEFAULT_COLORS['timer_bg']))
        self.TIMER_TEXT = self.TEXT_COLOR  # Timer text uses main text color
        self.MUTED_TEXT = tuple(colors.get('muted_text', self.DEFAULT_COLORS['muted_text']))
        self.CARD_BG = tuple(colors.get('card_bg', self.DEFAULT_COLORS['card_bg']))
        self.OPTION_HOVER = tuple(c + 17 for c in self.OPTION_BG)  # Slightly lighter than option bg

    def _get_font(self, size):
        """Get a font with caching - checks container and standard paths"""
        if size in self._font_cache:
            return self._font_cache[size]

        # Container fonts (dnf dejavu-sans-fonts), then standard Linux paths
        font_paths = [
            # Lambda container fonts (Amazon Linux 2023)
            "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
            # Standard Linux paths (Ubuntu/Debian for local testing)
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        ]

        for font_path in font_paths:
            if os.path.exists(font_path):
                try:
                    font = ImageFont.truetype(font_path, size)
                    self._font_cache[size] = font
                    return font
                except Exception:
                    continue

        # Fallback to default
        font = ImageFont.load_default()
        self._font_cache[size] = font
        return font

    def _download_audio(self):
        """Download audio file from URL and cache locally"""
        print(f"Audio URL configured: '{self.audio_url}'")

        if not self.audio_url:
            print("No audio URL configured")
            return None

        if self._audio_path and os.path.exists(self._audio_path):
            print(f"Using cached audio: {self._audio_path}")
            return self._audio_path

        try:
            # Determine file extension from URL
            ext = '.mp3'
            if '.wav' in self.audio_url.lower():
                ext = '.wav'
            elif '.ogg' in self.audio_url.lower():
                ext = '.ogg'

            audio_path = os.path.join(self.temp_dir, f'background_audio{ext}')

            # Download audio file
            print(f"Downloading audio from: {self.audio_url}")
            response = requests.get(self.audio_url, timeout=30)
            response.raise_for_status()
            print(f"Downloaded {len(response.content)} bytes")

            with open(audio_path, 'wb') as f:
                f.write(response.content)

            self._audio_path = audio_path
            print(f"Audio saved to: {audio_path}")
            return audio_path

        except Exception as e:
            print(f"Warning: Failed to download audio: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _download_intro_audio(self):
        """Download intro audio file from URL and cache locally"""
        print(f"Intro audio URL configured: '{self.intro_audio_url}'")

        if not self.intro_audio_url:
            print("No intro audio URL configured")
            return None

        if self._intro_audio_path and os.path.exists(self._intro_audio_path):
            print(f"Using cached intro audio: {self._intro_audio_path}")
            return self._intro_audio_path

        try:
            # Determine file extension from URL
            ext = '.mp3'
            if '.wav' in self.intro_audio_url.lower():
                ext = '.wav'
            elif '.ogg' in self.intro_audio_url.lower():
                ext = '.ogg'

            audio_path = os.path.join(self.temp_dir, f'intro_audio{ext}')

            # Download audio file
            print(f"Downloading intro audio from: {self.intro_audio_url}")
            response = requests.get(self.intro_audio_url, timeout=30)
            response.raise_for_status()
            print(f"Downloaded {len(response.content)} bytes for intro")

            with open(audio_path, 'wb') as f:
                f.write(response.content)

            self._intro_audio_path = audio_path
            print(f"Intro audio saved to: {audio_path}")
            return audio_path

        except Exception as e:
            print(f"Warning: Failed to download intro audio: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _add_intro_audio_to_clip(self, video_clip):
        """Add intro audio to intro clip"""
        audio_path = self._download_intro_audio()
        if not audio_path:
            print("No intro audio path available, skipping intro audio")
            return video_clip

        try:
            print(f"Loading intro audio from: {audio_path}")
            audio_clip = AudioFileClip(audio_path)

            # Get durations
            video_duration = video_clip.duration
            audio_duration = audio_clip.duration
            print(f"Intro video duration: {video_duration}s, Intro audio duration: {audio_duration}s")

            # Build effects list
            effects = []

            # Loop audio if shorter than video
            if audio_duration < video_duration:
                loops_needed = int(video_duration / audio_duration) + 1
                print(f"Looping intro audio {loops_needed} times")
                effects.append(AudioLoop(n_loops=loops_needed))

            # Adjust volume
            print(f"Setting intro volume to: {self.intro_audio_volume}")
            effects.append(MultiplyVolume(factor=self.intro_audio_volume))

            # Apply effects
            if effects:
                audio_clip = audio_clip.with_effects(effects)

            # Trim audio to match video duration
            audio_clip = audio_clip.with_duration(video_duration)

            # Set audio on video
            video_with_audio = video_clip.with_audio(audio_clip)
            print("Intro audio successfully added")

            return video_with_audio

        except Exception as e:
            print(f"Warning: Failed to add intro audio: {e}")
            import traceback
            traceback.print_exc()
            return video_clip

    def _download_answer_reveal_audio(self):
        """Download answer reveal audio file from URL and cache locally"""
        print(f"Answer reveal audio URL configured: '{self.answer_reveal_audio_url}'")

        if not self.answer_reveal_audio_url:
            print("No answer reveal audio URL configured")
            return None

        if self._answer_reveal_audio_path and os.path.exists(self._answer_reveal_audio_path):
            print(f"Using cached answer reveal audio: {self._answer_reveal_audio_path}")
            return self._answer_reveal_audio_path

        try:
            # Determine file extension from URL
            ext = '.mp3'
            if '.wav' in self.answer_reveal_audio_url.lower():
                ext = '.wav'
            elif '.ogg' in self.answer_reveal_audio_url.lower():
                ext = '.ogg'

            audio_path = os.path.join(self.temp_dir, f'answer_reveal_audio{ext}')

            # Download audio file
            print(f"Downloading answer reveal audio from: {self.answer_reveal_audio_url}")
            response = requests.get(self.answer_reveal_audio_url, timeout=30)
            response.raise_for_status()
            print(f"Downloaded {len(response.content)} bytes for answer reveal")

            with open(audio_path, 'wb') as f:
                f.write(response.content)

            self._answer_reveal_audio_path = audio_path
            print(f"Answer reveal audio saved to: {audio_path}")
            return audio_path

        except Exception as e:
            print(f"Warning: Failed to download answer reveal audio: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _add_answer_reveal_audio_to_clip(self, video_clip):
        """Add answer reveal audio to video clip (plays once, no loop)"""
        audio_path = self._download_answer_reveal_audio()
        if not audio_path:
            print("No answer reveal audio path available, skipping")
            return video_clip

        try:
            print(f"Loading answer reveal audio from: {audio_path}")
            audio_clip = AudioFileClip(audio_path)

            # Get durations
            video_duration = video_clip.duration
            audio_duration = audio_clip.duration
            print(f"Reveal video duration: {video_duration}s, Audio duration: {audio_duration}s")

            # Adjust volume (no looping - play once only)
            print(f"Setting answer reveal volume to: {self.answer_reveal_audio_volume}")
            audio_clip = audio_clip.with_effects([
                MultiplyVolume(factor=self.answer_reveal_audio_volume)
            ])

            # If audio is longer than video, trim it
            if audio_duration > video_duration:
                audio_clip = audio_clip.with_duration(video_duration)

            # Set audio on video (audio plays once from start, silence after it ends)
            video_with_audio = video_clip.with_audio(audio_clip)
            print("Answer reveal audio successfully added (no loop)")

            return video_with_audio

        except Exception as e:
            print(f"Warning: Failed to add answer reveal audio: {e}")
            import traceback
            traceback.print_exc()
            return video_clip

    def _add_audio_to_video(self, video_clip):
        """Add background audio to video clip"""
        audio_path = self._download_audio()
        if not audio_path:
            print("No audio path available, skipping audio")
            return video_clip

        try:
            print(f"Loading audio from: {audio_path}")
            # Load audio
            audio_clip = AudioFileClip(audio_path)

            # Get durations
            video_duration = video_clip.duration
            audio_duration = audio_clip.duration
            print(f"Video duration: {video_duration}s, Audio duration: {audio_duration}s")

            # Build effects list
            effects = []

            # Loop audio if shorter than video
            if audio_duration < video_duration:
                loops_needed = int(video_duration / audio_duration) + 1
                print(f"Looping audio {loops_needed} times")
                effects.append(AudioLoop(n_loops=loops_needed))

            # Adjust volume
            print(f"Setting volume to: {self.audio_volume}")
            effects.append(MultiplyVolume(factor=self.audio_volume))

            # Apply effects
            if effects:
                audio_clip = audio_clip.with_effects(effects)

            # Trim audio to match video duration
            audio_clip = audio_clip.with_duration(video_duration)

            # Set audio on video
            video_with_audio = video_clip.with_audio(audio_clip)
            print("Audio successfully added to video")

            return video_with_audio

        except Exception as e:
            print(f"Warning: Failed to add audio: {e}")
            import traceback
            traceback.print_exc()
            return video_clip

    def _wrap_text(self, text, font, max_width, draw):
        """Wrap text to fit within max_width"""
        words = text.split()
        lines = []
        current_line = []

        for word in words:
            test_line = ' '.join(current_line + [word])
            bbox = draw.textbbox((0, 0), test_line, font=font)
            width = bbox[2] - bbox[0]
            if width <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [word]

        if current_line:
            lines.append(' '.join(current_line))

        return lines if lines else [text]

    def _create_question_frame(self, question_num, total, question_text, options,
                                timer_value=None, reveal_answer=False, correct_indices=None,
                                code_snippet=None, explanation=None):
        """Create a single frame for a question with modern dark theme"""
        if correct_indices is None:
            correct_indices = []

        img = Image.new('RGB', (self.WIDTH, self.HEIGHT), self.BG_COLOR)
        draw = ImageDraw.Draw(img)

        # Fonts
        badge_font = self._get_font(36)
        question_font = self._get_font(44 if code_snippet else 48)  # Smaller if code present
        option_font = self._get_font(36 if code_snippet else 38)
        timer_font = self._get_font(72)
        label_font = self._get_font(32)
        brand_font = self._get_font(28)
        code_font = self._get_font(24)  # Monospace-like font for code

        y_offset = 120

        # Top accent bar
        draw.rectangle([0, 0, self.WIDTH, 8], fill=self.ACCENT_COLOR)

        # Quiz heading (displayed at top, above question index)
        if self.quiz_heading:
            heading_font = self._get_font(38)
            heading_text = self.quiz_heading[:40]  # Limit to 40 chars
            draw.text(
                (self.WIDTH // 2, y_offset),
                heading_text,
                font=heading_font,
                fill=self.ACCENT_COLOR,
                anchor="mm"
            )
            y_offset += 60

        # Question number badge with gradient-like effect
        badge_text = f"QUESTION {question_num}/{total}"
        bbox = draw.textbbox((0, 0), badge_text, font=badge_font)
        badge_width = bbox[2] - bbox[0]
        badge_x = (self.WIDTH - badge_width) // 2

        # Badge with border
        padding = 30
        draw.rounded_rectangle(
            [badge_x - padding, y_offset - 12,
             badge_x + badge_width + padding, y_offset + 48],
            radius=25,
            fill=self.CARD_BG,
            outline=self.ACCENT_COLOR,
            width=2
        )
        draw.text((badge_x, y_offset), badge_text, font=badge_font, fill=self.ACCENT_COLOR)

        y_offset += 100

        # Timer (if showing)
        if timer_value is not None:
            timer_center = (self.WIDTH // 2, y_offset + 55)

            # Outer ring
            outer_radius = 60
            draw.ellipse(
                [timer_center[0] - outer_radius, timer_center[1] - outer_radius,
                 timer_center[0] + outer_radius, timer_center[1] + outer_radius],
                fill=self.TIMER_BG,
                outline=self.ACCENT_COLOR,
                width=3
            )

            # Timer text - use anchor for true centering
            timer_text = str(timer_value)
            draw.text(
                timer_center,
                timer_text,
                font=timer_font,
                fill=self.TIMER_TEXT,
                anchor="mm"  # middle-middle anchor
            )

            y_offset += 160

        # Question card
        max_text_width = self.WIDTH - 160
        question_lines = self._wrap_text(question_text, question_font, max_text_width, draw)

        line_height = 60
        q_box_height = len(question_lines) * line_height + 60
        q_box_y = y_offset

        # Question card background
        draw.rounded_rectangle(
            [60, q_box_y, self.WIDTH - 60, q_box_y + q_box_height],
            radius=20,
            fill=self.CARD_BG
        )

        # Left accent stripe on question card
        draw.rounded_rectangle(
            [60, q_box_y, 68, q_box_y + q_box_height],
            radius=0,
            fill=self.ACCENT_COLOR
        )

        y_offset += 35
        for line in question_lines:
            bbox = draw.textbbox((0, 0), line, font=question_font)
            line_width = bbox[2] - bbox[0]
            draw.text(
                ((self.WIDTH - line_width) // 2, y_offset),
                line,
                font=question_font,
                fill=self.TEXT_COLOR
            )
            y_offset += line_height

        y_offset = q_box_y + q_box_height + 30

        # Code snippet (if present)
        if code_snippet and code_snippet.strip():
            code_lines = code_snippet.strip().split('\n')[:8]  # Max 8 lines
            code_line_height = 32
            code_padding = 20
            code_box_height = len(code_lines) * code_line_height + code_padding * 2

            # Code block background (darker)
            code_bg_color = (15, 15, 15)
            draw.rounded_rectangle(
                [60, y_offset, self.WIDTH - 60, y_offset + code_box_height],
                radius=12,
                fill=code_bg_color,
                outline=(50, 50, 50),
                width=1
            )

            # Code text
            code_y = y_offset + code_padding
            for code_line in code_lines:
                # Truncate long lines
                if len(code_line) > 45:
                    code_line = code_line[:42] + '...'
                draw.text(
                    (80, code_y),
                    code_line,
                    font=code_font,
                    fill=(0, 255, 136)  # Green code color
                )
                code_y += code_line_height

            y_offset += code_box_height + 20
        else:
            y_offset += 20

        # Options
        option_labels = ['A', 'B', 'C', 'D']
        option_height = 85
        option_margin = 18
        option_width = self.WIDTH - 120

        for i, option in enumerate(options[:4]):
            option_y = y_offset + (i * (option_height + option_margin))
            option_x = 60

            is_correct = i in correct_indices

            # Determine colors based on state
            if reveal_answer:
                if is_correct:
                    bg_color = self.CORRECT_COLOR
                    text_color = self.TEXT_COLOR
                    border_color = self.CORRECT_COLOR
                else:
                    bg_color = self.OPTION_BG
                    text_color = self.MUTED_TEXT
                    border_color = (60, 60, 60)
            else:
                bg_color = self.OPTION_BG
                text_color = self.OPTION_TEXT
                border_color = (70, 70, 70)

            # Option background with subtle border
            draw.rounded_rectangle(
                [option_x, option_y, option_x + option_width, option_y + option_height],
                radius=12,
                fill=bg_color,
                outline=border_color,
                width=2
            )

            # Option label (A, B, C, D)
            label_x = option_x + 45
            label_y = option_y + option_height // 2
            label_radius = 20

            if reveal_answer and is_correct:
                label_bg = self.TEXT_COLOR
                label_text_color = self.CORRECT_COLOR
            else:
                label_bg = self.ACCENT_COLOR
                label_text_color = self.TEXT_COLOR

            draw.ellipse(
                [label_x - label_radius, label_y - label_radius,
                 label_x + label_radius, label_y + label_radius],
                fill=label_bg
            )

            # Use anchor for proper centering
            draw.text(
                (label_x, label_y),
                option_labels[i],
                font=label_font,
                fill=label_text_color,
                anchor="mm"  # middle-middle anchor for true centering
            )

            # Option text
            opt_text = option.get('text', '')[:50]
            if len(option.get('text', '')) > 50:
                opt_text += '...'

            draw.text(
                (option_x + 85, option_y + option_height // 2 - 16),
                opt_text,
                font=option_font,
                fill=text_color
            )


        # Explanation (shown during answer reveal if exists)
        if reveal_answer and explanation and explanation.strip():
            explanation_font = self._get_font(28)
            explanation_y = y_offset + (len(options[:4]) * (option_height + option_margin)) + 20

            # Wrap explanation text
            max_explanation_width = self.WIDTH - 160
            explanation_lines = self._wrap_text(
                explanation.strip(), explanation_font, max_explanation_width, draw
            )[:3]  # Max 3 lines

            # Calculate explanation box height
            exp_line_height = 36
            exp_padding = 16
            exp_box_height = len(explanation_lines) * exp_line_height + exp_padding * 2

            # Draw explanation box
            draw.rounded_rectangle(
                [60, explanation_y, self.WIDTH - 60, explanation_y + exp_box_height],
                radius=12,
                fill=self.CARD_BG,
                outline=self.CORRECT_COLOR,
                width=2
            )

            # Draw explanation text
            exp_text_y = explanation_y + exp_padding
            for line in explanation_lines:
                bbox = draw.textbbox((0, 0), line, font=explanation_font)
                line_width = bbox[2] - bbox[0]
                draw.text(
                    ((self.WIDTH - line_width) // 2, exp_text_y),
                    line,
                    font=explanation_font,
                    fill=self.TEXT_COLOR
                )
                exp_text_y += exp_line_height

        # Bottom branding
        brand_text = self.handle_name
        bbox = draw.textbbox((0, 0), brand_text, font=brand_font)
        bw = bbox[2] - bbox[0]
        draw.text(
            ((self.WIDTH - bw) // 2, self.HEIGHT - 80),
            brand_text,
            font=brand_font,
            fill=self.MUTED_TEXT
        )

        # Bottom accent bar
        draw.rectangle([0, self.HEIGHT - 8, self.WIDTH, self.HEIGHT], fill=self.ACCENT_COLOR)

        return np.array(img)

    def _create_intro_frame(self, intro_text):
        """Create the intro frame with custom text - clean design without circles"""
        img = Image.new('RGB', (self.WIDTH, self.HEIGHT), self.BG_COLOR)
        draw = ImageDraw.Draw(img)

        # Top and bottom accent bars
        draw.rectangle([0, 0, self.WIDTH, 8], fill=self.ACCENT_COLOR)
        draw.rectangle([0, self.HEIGHT - 8, self.WIDTH, self.HEIGHT], fill=self.ACCENT_COLOR)

        # Fonts
        main_font = self._get_font(72)
        brand_font = self._get_font(28)

        center_x = self.WIDTH // 2
        center_y = self.HEIGHT // 2

        # Wrap text if needed
        max_text_width = self.WIDTH - 160
        lines = self._wrap_text(intro_text, main_font, max_text_width, draw)

        # Calculate total height of text block
        line_height = 90
        total_text_height = len(lines) * line_height
        start_y = center_y - total_text_height // 2

        # Draw each line centered
        for i, line in enumerate(lines):
            draw.text(
                (center_x, start_y + i * line_height),
                line,
                font=main_font,
                fill=self.TEXT_COLOR,
                anchor="mm"
            )

        # Brand name at bottom
        brand_text = self.handle_name
        draw.text(
            (center_x, self.HEIGHT - 80),
            brand_text,
            font=brand_font,
            fill=self.MUTED_TEXT,
            anchor="mm"
        )

        return np.array(img)

    def _create_pre_outro_frame(self, pre_outro_text):
        """Create the pre-outro frame (e.g., 'Comment your answer!')"""
        img = Image.new('RGB', (self.WIDTH, self.HEIGHT), self.BG_COLOR)
        draw = ImageDraw.Draw(img)

        # Top and bottom accent bars
        draw.rectangle([0, 0, self.WIDTH, 8], fill=self.ACCENT_COLOR)
        draw.rectangle([0, self.HEIGHT - 8, self.WIDTH, self.HEIGHT], fill=self.ACCENT_COLOR)

        # Fonts
        main_font = self._get_font(72)
        brand_font = self._get_font(28)

        center_x = self.WIDTH // 2
        center_y = self.HEIGHT // 2

        # Wrap text if needed
        max_text_width = self.WIDTH - 160
        lines = self._wrap_text(pre_outro_text, main_font, max_text_width, draw)

        # Calculate total height of text block
        line_height = 90
        total_text_height = len(lines) * line_height
        start_y = center_y - total_text_height // 2

        # Draw each line centered with accent color for emphasis
        for i, line in enumerate(lines):
            draw.text(
                (center_x, start_y + i * line_height),
                line,
                font=main_font,
                fill=self.ACCENT_COLOR,  # Purple accent for call-to-action
                anchor="mm"
            )

        # Brand name at bottom
        brand_text = self.handle_name
        draw.text(
            (center_x, self.HEIGHT - 80),
            brand_text,
            font=brand_font,
            fill=self.MUTED_TEXT,
            anchor="mm"
        )

        return np.array(img)

    def _create_outro_frame(self):
        """Create the outro frame with modern dark theme"""
        img = Image.new('RGB', (self.WIDTH, self.HEIGHT), self.BG_COLOR)
        draw = ImageDraw.Draw(img)

        # Top and bottom accent bars
        draw.rectangle([0, 0, self.WIDTH, 8], fill=self.ACCENT_COLOR)
        draw.rectangle([0, self.HEIGHT - 8, self.WIDTH, self.HEIGHT], fill=self.ACCENT_COLOR)

        title_font = self._get_font(48)
        brand_font = self._get_font(60)
        subtitle_font = self._get_font(36)

        center_x = self.WIDTH // 2
        center_y = self.HEIGHT // 2

        # Larger decorative circle to fit all text
        circle_radius = 280
        draw.ellipse(
            [center_x - circle_radius, center_y - circle_radius,
             center_x + circle_radius, center_y + circle_radius],
            fill=self.CARD_BG,
            outline=self.ACCENT_COLOR,
            width=4
        )

        # Inner accent ring
        inner_radius = 250
        draw.ellipse(
            [center_x - inner_radius, center_y - inner_radius,
             center_x + inner_radius, center_y + inner_radius],
            fill=None,
            outline=(75, 0, 130, 128),
            width=2
        )

        # Main text - centered using anchor
        main_text = "FOLLOW"
        draw.text(
            (center_x, center_y - 80),
            main_text,
            font=title_font,
            fill=self.MUTED_TEXT,
            anchor="mm"
        )

        # Brand name - centered using anchor
        brand_text = self.handle_name
        draw.text(
            (center_x, center_y),
            brand_text,
            font=brand_font,
            fill=self.ACCENT_COLOR,
            anchor="mm"
        )

        # Subtitle - centered using anchor
        sub_text = "for more quizzes!"
        draw.text(
            (center_x, center_y + 80),
            sub_text,
            font=subtitle_font,
            fill=self.TEXT_COLOR,
            anchor="mm"
        )

        return np.array(img)

    def generate_video(self, questions, output_path, progress_callback=None, show_answer=True):
        """
        Generate a quiz video from questions.

        Args:
            questions: List of dicts with 'text', 'options' (list of {'text', 'is_correct'})
            output_path: Path to save the output video
            progress_callback: Optional callback function(percent, message) for progress updates
            show_answer: Whether to reveal the correct answer after the timer (default: True)

        Returns:
            Path to the generated video
        """
        all_countdown_clips = []  # All countdown clips for cleanup
        all_reveal_clips = []     # All reveal clips for cleanup
        question_sections = []    # List of (countdown_video, reveal_video) per question
        total_questions = len(questions)

        def report_progress(percent, message):
            if progress_callback:
                progress_callback(percent, message)

        # Create question clips - separated by countdown and reveal for different audio
        for q_idx, question in enumerate(questions):
            question_num = q_idx + 1
            total = len(questions)

            # Report progress for this question (5-20% for frame generation)
            base_percent = 5 + int((q_idx / total_questions) * 15)
            report_progress(base_percent, f"Creating question {question_num} of {total_questions}...")

            # Find ALL correct answer indices (support multiple correct)
            correct_indices = []
            for i, opt in enumerate(question['options']):
                if opt.get('is_correct', False):
                    correct_indices.append(i)

            # Get code snippet and explanation if present
            code_snippet = question.get('code_snippet', '')
            explanation = question.get('explanation', '')

            # Create countdown clips for this question
            q_countdown_clips = []
            for timer in range(self.QUESTION_DURATION, 0, -1):
                frame = self._create_question_frame(
                    question_num=question_num,
                    total=total,
                    question_text=question['text'],
                    options=question['options'],
                    timer_value=timer,
                    reveal_answer=False,
                    correct_indices=correct_indices,
                    code_snippet=code_snippet
                )
                clip = ImageClip(frame, duration=1)
                q_countdown_clips.append(clip)
                all_countdown_clips.append(clip)

            # Create answer reveal clip (only if show_answer is True)
            q_reveal_clip = None
            if show_answer:
                reveal_frame = self._create_question_frame(
                    question_num=question_num,
                    total=total,
                    question_text=question['text'],
                    options=question['options'],
                    timer_value=None,
                    reveal_answer=True,
                    correct_indices=correct_indices,
                    code_snippet=code_snippet,
                    explanation=explanation
                )
                q_reveal_clip = ImageClip(reveal_frame, duration=self.ANSWER_REVEAL_DURATION)
                all_reveal_clips.append(q_reveal_clip)

            question_sections.append((q_countdown_clips, q_reveal_clip))

        # Create intro clip if configured
        report_progress(15, "Creating intro...")
        intro_clip = None
        if self.intro_text:
            intro_frame = self._create_intro_frame(self.intro_text)
            intro_clip = ImageClip(intro_frame, duration=self.INTRO_DURATION)

        # Create pre-outro clip (optional)
        pre_outro_clip = None
        if self.pre_outro_text:
            report_progress(18, "Creating pre-outro...")
            pre_outro_frame = self._create_pre_outro_frame(self.pre_outro_text)
            pre_outro_clip = ImageClip(pre_outro_frame, duration=self.PRE_OUTRO_DURATION)

        # Create outro clip
        report_progress(20, "Creating outro...")
        outro_frame = self._create_outro_frame()
        outro_clip = ImageClip(outro_frame, duration=self.OUTRO_DURATION)

        # Handle audio and concatenation
        report_progress(25, "Assembling clips...")

        # Build question videos with proper audio assignment
        # Each question: countdown (bg music) -> reveal (intro audio)
        question_videos = []
        for q_countdown_clips, q_reveal_clip in question_sections:
            # Concatenate countdown clips for this question
            q_countdown_video = concatenate_videoclips(q_countdown_clips, method="compose")
            if self.audio_url:
                q_countdown_video = self._add_audio_to_video(q_countdown_video)

            # Add reveal clip with answer reveal audio (if exists)
            if q_reveal_clip:
                if self.answer_reveal_audio_url:
                    q_reveal_clip = self._add_answer_reveal_audio_to_clip(q_reveal_clip)
                # Combine countdown + reveal for this question
                q_video = concatenate_videoclips(
                    [q_countdown_video, q_reveal_clip], method="compose"
                )
            else:
                q_video = q_countdown_video

            question_videos.append(q_video)

        report_progress(28, "Combining question sections...")

        # Concatenate all question videos
        questions_video = concatenate_videoclips(question_videos, method="compose")

        # Create ending section (pre-outro if exists + outro) with intro music
        ending_clips = []
        if pre_outro_clip:
            ending_clips.append(pre_outro_clip)
        ending_clips.append(outro_clip)
        ending_video = concatenate_videoclips(ending_clips, method="compose")

        # Add intro music to intro and ending (pre-outro + outro)
        if self.intro_audio_url:
            report_progress(30, "Adding intro music...")
            # Add intro audio to intro clip
            if intro_clip:
                intro_clip = self._add_intro_audio_to_clip(intro_clip)
            # Add intro audio to ending (pre-outro + outro)
            ending_video = self._add_intro_audio_to_clip(ending_video)

        # Final assembly: intro (optional) + questions + ending
        final_clips = []
        if intro_clip:
            final_clips.append(intro_clip)
        final_clips.append(questions_video)
        final_clips.append(ending_video)

        final_video = concatenate_videoclips(final_clips, method="compose")

        report_progress(35, "Preparing encoder...")

        # Write video file (no background thread in Lambda - just write directly)
        report_progress(40, "Encoding video...")
        has_audio = final_video.audio is not None

        final_video.write_videofile(
            output_path,
            fps=self.FPS,
            codec='libx264',
            audio=has_audio,
            audio_codec='aac' if has_audio else None,
            preset='ultrafast',
            threads=2,
            logger=None
        )

        report_progress(95, "Finalizing...")

        # Cleanup clips
        final_video.close()
        for clip in all_countdown_clips:
            clip.close()
        for clip in all_reveal_clips:
            clip.close()
        if intro_clip:
            intro_clip.close()
        if pre_outro_clip:
            pre_outro_clip.close()
        outro_clip.close()

        return output_path

    def cleanup(self):
        """Remove temporary files"""
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)


def generate_quiz_video(questions, output_path, progress_callback=None, show_answer=True,
                        handle_name="@maedix-q", audio_url=None, audio_volume=0.3,
                        intro_text=None, intro_audio_url=None, intro_audio_volume=0.5,
                        pre_outro_text=None, template_config=None, quiz_heading=None,
                        answer_reveal_audio_url=None, answer_reveal_audio_volume=0.5):
    """
    Convenience function to generate quiz video.

    Args:
        questions: List of question dicts with 'text', 'options', etc.
        output_path: Path to save video
        progress_callback: Optional callback function(percent, message) for progress updates
        show_answer: Whether to reveal the correct answer after the timer (default: True)
        handle_name: Custom handle name to display in video (default: "@maedix-q")
        audio_url: URL to background audio file (mp3/wav) - optional
        audio_volume: Volume level for background audio (0.0 to 1.0, default: 0.3)
        intro_text: Custom text to display in the intro (None = no intro)
        intro_audio_url: URL to intro audio file (mp3/wav) - optional, plays for intro/pre-outro/outro
        intro_audio_volume: Volume level for intro audio (0.0 to 1.0, default: 0.5)
        pre_outro_text: Text for pre-outro call-to-action (default: "Comment your answer!")
        template_config: Template configuration dict with 'colors' key (optional)
        quiz_heading: Text displayed above the timer during questions (max 40 chars)
        answer_reveal_audio_url: URL to answer reveal audio file (mp3/wav) - optional
        answer_reveal_audio_volume: Volume level for answer reveal audio (0.0 to 1.0, default: 0.5)

    Returns:
        Path to generated video
    """
    generator = QuizVideoGenerator(
        handle_name=handle_name,
        audio_url=audio_url,
        audio_volume=audio_volume,
        intro_text=intro_text,
        intro_audio_url=intro_audio_url,
        intro_audio_volume=intro_audio_volume,
        pre_outro_text=pre_outro_text,
        template_config=template_config,
        quiz_heading=quiz_heading,
        answer_reveal_audio_url=answer_reveal_audio_url,
        answer_reveal_audio_volume=answer_reveal_audio_volume
    )

    try:
        return generator.generate_video(questions, output_path, progress_callback, show_answer=show_answer)
    finally:
        generator.cleanup()
