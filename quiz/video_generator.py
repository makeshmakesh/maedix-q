"""
Video generator for quiz export to Instagram Reels format.
Generates vertical videos (1080x1920) with questions, options, timer, and answer reveal.
"""
import os
import tempfile
import shutil
from PIL import Image, ImageDraw, ImageFont
from moviepy import ImageClip, concatenate_videoclips
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
    OUTRO_DURATION = 2

    # Modern Dark Theme Colors
    BG_COLOR = (18, 18, 18)  # Mat black
    TEXT_COLOR = (255, 255, 255)  # White
    ACCENT_COLOR = (138, 43, 226)  # Purple accent
    CORRECT_COLOR = (0, 200, 83)  # Vibrant green
    WRONG_COLOR = (239, 68, 68)  # Red for wrong (during reveal)
    OPTION_BG = (38, 38, 38)  # Dark grey for options
    OPTION_HOVER = (55, 55, 55)  # Slightly lighter grey
    OPTION_TEXT = (240, 240, 240)  # Light text on dark
    TIMER_BG = (75, 0, 130)  # Deep purple for timer
    TIMER_TEXT = (255, 255, 255)  # White timer text
    MUTED_TEXT = (156, 163, 175)  # Grey for secondary text
    CARD_BG = (28, 28, 30)  # Slightly lighter than bg for cards

    def __init__(self, handle_name="@maedix-q"):
        self.temp_dir = tempfile.mkdtemp()
        self._font_cache = {}
        self.handle_name = handle_name

    def _get_font(self, size):
        """Get a font with caching"""
        if size in self._font_cache:
            return self._font_cache[size]

        font_paths = [
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
                                timer_value=None, reveal_answer=False, correct_indices=None):
        """Create a single frame for a question with modern dark theme"""
        if correct_indices is None:
            correct_indices = []

        img = Image.new('RGB', (self.WIDTH, self.HEIGHT), self.BG_COLOR)
        draw = ImageDraw.Draw(img)

        # Fonts
        badge_font = self._get_font(36)
        question_font = self._get_font(48)
        option_font = self._get_font(38)
        timer_font = self._get_font(72)
        label_font = self._get_font(32)
        brand_font = self._get_font(28)

        y_offset = 120

        # Top accent bar
        draw.rectangle([0, 0, self.WIDTH, 8], fill=self.ACCENT_COLOR)

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

        y_offset = q_box_y + q_box_height + 50

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

            # Checkmark for correct answers during reveal
            if reveal_answer and is_correct:
                check_font = self._get_font(40)
                draw.text(
                    (option_x + option_width - 55, option_y + option_height // 2 - 18),
                    "✓",
                    font=check_font,
                    fill=self.TEXT_COLOR
                )

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
        clips = []
        total_questions = len(questions)

        def report_progress(percent, message):
            if progress_callback:
                progress_callback(percent, message)

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

            # Create question frames with countdown (1 frame per second for countdown)
            for timer in range(self.QUESTION_DURATION, 0, -1):
                frame = self._create_question_frame(
                    question_num=question_num,
                    total=total,
                    question_text=question['text'],
                    options=question['options'],
                    timer_value=timer,
                    reveal_answer=False,
                    correct_indices=correct_indices
                )
                clip = ImageClip(frame, duration=1)
                clips.append(clip)

            # Create answer reveal frame (only if show_answer is True)
            if show_answer:
                reveal_frame = self._create_question_frame(
                    question_num=question_num,
                    total=total,
                    question_text=question['text'],
                    options=question['options'],
                    timer_value=None,
                    reveal_answer=True,
                    correct_indices=correct_indices
                )
                reveal_clip = ImageClip(reveal_frame, duration=self.ANSWER_REVEAL_DURATION)
                clips.append(reveal_clip)

        # Add outro
        report_progress(15, "Creating outro...")
        outro_frame = self._create_outro_frame()
        outro_clip = ImageClip(outro_frame, duration=self.OUTRO_DURATION)
        clips.append(outro_clip)

        # Concatenate all clips
        report_progress(25, "Assembling clips...")
        final_video = concatenate_videoclips(clips, method="compose")

        report_progress(35, "Preparing encoder...")

        # Start a background thread to simulate smooth progress during encoding
        import threading
        import time

        encoding_done = threading.Event()
        encoding_error = [None]  # Use list to allow modification in nested function

        def simulate_encoding_progress():
            """Gradually increase progress while encoding runs"""
            current = 40
            messages = [
                (40, "Encoding frames..."),
                (50, "Processing video..."),
                (60, "Rendering frames..."),
                (70, "Compressing video..."),
                (80, "Optimizing output..."),
                (85, "Almost done..."),
            ]
            msg_index = 0

            while not encoding_done.is_set() and current < 90:
                # Update message at thresholds
                while msg_index < len(messages) and current >= messages[msg_index][0]:
                    report_progress(current, messages[msg_index][1])
                    msg_index += 1

                time.sleep(0.8)  # Update every 800ms
                if not encoding_done.is_set():
                    current += 2  # Increment by 2%
                    if msg_index > 0:
                        report_progress(min(current, 90), messages[min(msg_index, len(messages)-1)][1])

        # Start progress simulation thread
        progress_thread = threading.Thread(target=simulate_encoding_progress)
        progress_thread.daemon = True
        progress_thread.start()

        # Write video file
        try:
            final_video.write_videofile(
                output_path,
                fps=self.FPS,
                codec='libx264',
                audio=False,
                preset='ultrafast',
                threads=2,
                logger=None
            )
        finally:
            encoding_done.set()
            progress_thread.join(timeout=1)

        report_progress(95, "Finalizing...")

        # Cleanup clips
        final_video.close()
        for clip in clips:
            clip.close()

        return output_path

    def cleanup(self):
        """Remove temporary files"""
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)


def generate_quiz_video(questions, output_path, progress_callback=None, show_answer=True, handle_name="@maedix-q"):
    """
    Convenience function to generate quiz video.

    Args:
        questions: List of Question model instances or dicts
        output_path: Path to save video
        progress_callback: Optional callback function(percent, message) for progress updates
        show_answer: Whether to reveal the correct answer after the timer (default: True)
        handle_name: Custom handle name to display in video (default: "@maedix-q")

    Returns:
        Path to generated video
    """
    generator = QuizVideoGenerator(handle_name=handle_name)

    try:
        # Convert Question models to dicts if needed
        question_data = []
        for q in questions:
            if hasattr(q, 'text'):
                # It's a model instance
                question_data.append({
                    'text': q.text,
                    'options': [
                        {'text': opt.text, 'is_correct': opt.is_correct}
                        for opt in q.options.all()
                    ]
                })
            else:
                # Already a dict
                question_data.append(q)

        return generator.generate_video(question_data, output_path, progress_callback, show_answer=show_answer)
    finally:
        generator.cleanup()
