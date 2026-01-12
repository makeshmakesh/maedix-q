"""
Image generator for topic cards - Instagram carousel format.
Generates static images (1080x1350) for each card that can be uploaded as carousel posts.
"""
import os
import tempfile
import requests
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO


class TopicCardImageGenerator:
    """Generates static images for topic cards (Instagram carousel format)"""

    # Image dimensions (4:5 aspect ratio for Instagram carousel)
    WIDTH = 1080
    HEIGHT = 1350

    # Default Colors (Dark Purple theme - same as video generator)
    DEFAULT_COLORS = {
        'bg_color': (18, 18, 18),  # Mat black
        'text_color': (255, 255, 255),  # White
        'accent_color': (138, 43, 226),  # Purple accent
        'code_color': (0, 255, 136),  # Green for code
        'muted_text': (156, 163, 175),  # Grey for secondary text
        'card_bg': (28, 28, 30),  # Slightly lighter than bg for cards
        'code_bg': (30, 30, 30),  # Dark background for code blocks
    }

    def __init__(self, handle_name="@maedix", template_config=None):
        self.temp_dir = tempfile.mkdtemp()
        self._font_cache = {}
        self.handle_name = handle_name
        self._load_template_colors(template_config)

    def _load_template_colors(self, template_config):
        """Load colors from template config or use defaults"""
        colors = {}
        if template_config and 'colors' in template_config:
            colors = template_config['colors']

        self.BG_COLOR = tuple(colors.get('bg_color', self.DEFAULT_COLORS['bg_color']))
        self.TEXT_COLOR = tuple(colors.get('text_color', self.DEFAULT_COLORS['text_color']))
        self.ACCENT_COLOR = tuple(colors.get('accent_color', self.DEFAULT_COLORS['accent_color']))
        self.CODE_COLOR = tuple(colors.get('code_color', self.DEFAULT_COLORS['code_color']))
        self.MUTED_TEXT = tuple(colors.get('muted_text', self.DEFAULT_COLORS['muted_text']))
        self.CARD_BG = tuple(colors.get('card_bg', self.DEFAULT_COLORS['card_bg']))
        self.CODE_BG = tuple(colors.get('code_bg', self.DEFAULT_COLORS['code_bg']))

    def _get_font(self, size, bold=False):
        """Get a font with caching"""
        cache_key = f"{size}_{bold}"
        if cache_key in self._font_cache:
            return self._font_cache[cache_key]

        if bold:
            font_paths = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
            ]
        else:
            font_paths = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            ]

        for font_path in font_paths:
            if os.path.exists(font_path):
                try:
                    font = ImageFont.truetype(font_path, size)
                    self._font_cache[cache_key] = font
                    return font
                except Exception:
                    continue

        font = ImageFont.load_default()
        self._font_cache[cache_key] = font
        return font

    def _get_mono_font(self, size):
        """Get a monospace font for code"""
        cache_key = f"mono_{size}"
        if cache_key in self._font_cache:
            return self._font_cache[cache_key]

        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeMono.ttf",
        ]

        for font_path in font_paths:
            if os.path.exists(font_path):
                try:
                    font = ImageFont.truetype(font_path, size)
                    self._font_cache[cache_key] = font
                    return font
                except Exception:
                    continue

        return self._get_font(size)

    def _wrap_text(self, text, font, max_width, draw):
        """Wrap text to fit within max_width, preserving line breaks and bullet points"""
        # First, split by newlines to preserve intentional line breaks
        paragraphs = text.split('\n')
        all_lines = []

        for para in paragraphs:
            para = para.strip()
            if not para:
                # Preserve empty lines as spacing
                all_lines.append('')
                continue

            # Check if this is a bullet point line
            is_bullet = False
            bullet_char = ''
            bullet_indent = '    '  # Indent for wrapped bullet lines

            # Detect various bullet formats
            if para.startswith('• '):
                is_bullet = True
                bullet_char = '• '
                para = para[2:]
            elif para.startswith('- '):
                is_bullet = True
                bullet_char = '• '  # Convert dash to bullet
                para = para[2:]
            elif para.startswith('* '):
                is_bullet = True
                bullet_char = '• '  # Convert asterisk to bullet
                para = para[2:]
            elif len(para) > 2 and para[0].isdigit() and para[1] in '.):' and para[2] == ' ':
                # Numbered list like "1. " or "1) "
                is_bullet = True
                bullet_char = para[:3]
                para = para[3:]

            # Calculate available width for text (less for bullets due to indent)
            effective_width = max_width - (40 if is_bullet else 0)

            # Wrap this paragraph
            words = para.split()
            current_line = []
            first_line = True

            for word in words:
                test_line = ' '.join(current_line + [word])
                bbox = draw.textbbox((0, 0), test_line, font=font)
                width = bbox[2] - bbox[0]

                if width <= effective_width:
                    current_line.append(word)
                else:
                    if current_line:
                        line_text = ' '.join(current_line)
                        if is_bullet and first_line:
                            all_lines.append(bullet_char + line_text)
                            first_line = False
                        elif is_bullet:
                            all_lines.append(bullet_indent + line_text)
                        else:
                            all_lines.append(line_text)
                    current_line = [word]

            # Add remaining text
            if current_line:
                line_text = ' '.join(current_line)
                if is_bullet and first_line:
                    all_lines.append(bullet_char + line_text)
                elif is_bullet:
                    all_lines.append(bullet_indent + line_text)
                else:
                    all_lines.append(line_text)

        return all_lines if all_lines else [text]

    def _draw_swipe_dots(self, draw, current_index, total, y_position):
        """Draw swipe indicator dots at the bottom"""
        dot_radius = 5
        dot_spacing = 20
        total_width = (total - 1) * dot_spacing + (dot_radius * 2 * total)
        start_x = (self.WIDTH - total_width) // 2

        for i in range(total):
            x = start_x + i * (dot_radius * 2 + dot_spacing) + dot_radius
            if i == current_index:
                # Active dot - filled with accent color
                draw.ellipse(
                    [x - dot_radius, y_position - dot_radius,
                     x + dot_radius, y_position + dot_radius],
                    fill=self.ACCENT_COLOR
                )
            else:
                # Inactive dot - grey outline
                draw.ellipse(
                    [x - dot_radius, y_position - dot_radius,
                     x + dot_radius, y_position + dot_radius],
                    fill=self.MUTED_TEXT
                )

    def _create_intro_card(self, topic_title, card_count, category_name=None):
        """Create intro card for the topic"""
        img = Image.new('RGB', (self.WIDTH, self.HEIGHT), self.BG_COLOR)
        draw = ImageDraw.Draw(img)

        # Top accent bar
        draw.rectangle([0, 0, self.WIDTH, 8], fill=self.ACCENT_COLOR)

        # Fonts
        category_font = self._get_font(32)
        title_font = self._get_font(56, bold=True)
        subtitle_font = self._get_font(36)
        brand_font = self._get_font(28)

        center_y = self.HEIGHT // 2 - 100

        # Category badge
        if category_name:
            bbox = draw.textbbox((0, 0), category_name.upper(), font=category_font)
            cat_width = bbox[2] - bbox[0]
            cat_x = (self.WIDTH - cat_width) // 2
            draw.rounded_rectangle(
                [cat_x - 20, center_y - 15, cat_x + cat_width + 20, center_y + 45],
                radius=20,
                fill=self.CARD_BG,
                outline=self.ACCENT_COLOR,
                width=2
            )
            draw.text((cat_x, center_y), category_name.upper(), font=category_font, fill=self.ACCENT_COLOR)
            center_y += 100

        # Title
        max_width = self.WIDTH - 120
        title_lines = self._wrap_text(topic_title, title_font, max_width, draw)
        line_height = 70

        for i, line in enumerate(title_lines):
            bbox = draw.textbbox((0, 0), line, font=title_font)
            line_width = bbox[2] - bbox[0]
            x = (self.WIDTH - line_width) // 2
            draw.text((x, center_y + i * line_height), line, font=title_font, fill=self.TEXT_COLOR)

        center_y += len(title_lines) * line_height + 40

        # Card count
        cards_text = f"{card_count} cards"
        bbox = draw.textbbox((0, 0), cards_text, font=subtitle_font)
        cards_width = bbox[2] - bbox[0]
        draw.text(
            ((self.WIDTH - cards_width) // 2, center_y),
            cards_text,
            font=subtitle_font,
            fill=self.MUTED_TEXT
        )

        center_y += 60

        # Swipe hint
        hint_text = "Swipe to learn"
        bbox = draw.textbbox((0, 0), hint_text, font=subtitle_font)
        hint_width = bbox[2] - bbox[0]
        draw.text(
            ((self.WIDTH - hint_width) // 2, center_y),
            hint_text,
            font=subtitle_font,
            fill=self.ACCENT_COLOR
        )

        # Brand name at bottom
        bbox = draw.textbbox((0, 0), self.handle_name, font=brand_font)
        brand_width = bbox[2] - bbox[0]
        draw.text(
            ((self.WIDTH - brand_width) // 2, self.HEIGHT - 80),
            self.handle_name,
            font=brand_font,
            fill=self.MUTED_TEXT
        )

        # Bottom accent bar
        draw.rectangle([0, self.HEIGHT - 8, self.WIDTH, self.HEIGHT], fill=self.ACCENT_COLOR)

        return img

    def _create_text_card(self, card_index, total_cards, title, content):
        """Create a text-only card"""
        img = Image.new('RGB', (self.WIDTH, self.HEIGHT), self.BG_COLOR)
        draw = ImageDraw.Draw(img)

        # Top accent bar
        draw.rectangle([0, 0, self.WIDTH, 8], fill=self.ACCENT_COLOR)

        # Fonts
        title_font = self._get_font(44, bold=True)
        content_font = self._get_font(38)
        brand_font = self._get_font(28)

        y_offset = 80

        # Card number badge
        card_num_text = f"{card_index + 1}/{total_cards}"
        badge_font = self._get_font(28)
        bbox = draw.textbbox((0, 0), card_num_text, font=badge_font)
        badge_width = bbox[2] - bbox[0]
        draw.rounded_rectangle(
            [self.WIDTH - badge_width - 60, y_offset - 5,
             self.WIDTH - 40, y_offset + 35],
            radius=15,
            fill=self.CARD_BG
        )
        draw.text(
            (self.WIDTH - badge_width - 50, y_offset),
            card_num_text,
            font=badge_font,
            fill=self.ACCENT_COLOR
        )

        y_offset += 60

        # Title (if provided)
        if title:
            max_width = self.WIDTH - 120
            title_lines = self._wrap_text(title, title_font, max_width, draw)
            line_height = 55

            for line in title_lines:
                draw.text((60, y_offset), line, font=title_font, fill=self.ACCENT_COLOR)
                y_offset += line_height

            y_offset += 30

        # Content
        max_width = self.WIDTH - 120
        content_lines = self._wrap_text(content, content_font, max_width, draw)
        line_height = 52
        empty_line_height = 26  # Half height for empty lines (paragraph spacing)

        for line in content_lines:
            if line == '':
                # Empty line for paragraph spacing
                y_offset += empty_line_height
            else:
                draw.text((60, y_offset), line, font=content_font, fill=self.TEXT_COLOR)
                y_offset += line_height

        # Swipe dots
        self._draw_swipe_dots(draw, card_index, total_cards, self.HEIGHT - 120)

        # Brand name
        bbox = draw.textbbox((0, 0), self.handle_name, font=brand_font)
        brand_width = bbox[2] - bbox[0]
        draw.text(
            ((self.WIDTH - brand_width) // 2, self.HEIGHT - 60),
            self.handle_name,
            font=brand_font,
            fill=self.MUTED_TEXT
        )

        # Bottom accent bar
        draw.rectangle([0, self.HEIGHT - 8, self.WIDTH, self.HEIGHT], fill=self.ACCENT_COLOR)

        return img

    def _create_code_card(self, card_index, total_cards, title, content, code_snippet, code_language):
        """Create a text + code card"""
        img = Image.new('RGB', (self.WIDTH, self.HEIGHT), self.BG_COLOR)
        draw = ImageDraw.Draw(img)

        # Top accent bar
        draw.rectangle([0, 0, self.WIDTH, 8], fill=self.ACCENT_COLOR)

        # Fonts
        title_font = self._get_font(40, bold=True)
        content_font = self._get_font(32)
        code_font = self._get_mono_font(24)
        lang_font = self._get_font(20)
        brand_font = self._get_font(28)

        y_offset = 80

        # Card number badge
        card_num_text = f"{card_index + 1}/{total_cards}"
        badge_font = self._get_font(28)
        bbox = draw.textbbox((0, 0), card_num_text, font=badge_font)
        badge_width = bbox[2] - bbox[0]
        draw.rounded_rectangle(
            [self.WIDTH - badge_width - 60, y_offset - 5,
             self.WIDTH - 40, y_offset + 35],
            radius=15,
            fill=self.CARD_BG
        )
        draw.text(
            (self.WIDTH - badge_width - 50, y_offset),
            card_num_text,
            font=badge_font,
            fill=self.ACCENT_COLOR
        )

        y_offset += 60

        # Title (if provided)
        if title:
            max_width = self.WIDTH - 120
            title_lines = self._wrap_text(title, title_font, max_width, draw)
            line_height = 50

            for line in title_lines:
                draw.text((60, y_offset), line, font=title_font, fill=self.ACCENT_COLOR)
                y_offset += line_height

            y_offset += 20

        # Content (shorter for code cards)
        max_width = self.WIDTH - 120
        content_lines = self._wrap_text(content, content_font, max_width, draw)
        line_height = 42
        empty_line_height = 20

        lines_drawn = 0
        for line in content_lines:
            if lines_drawn >= 4:  # Limit to 4 lines for code cards
                break
            if line == '':
                y_offset += empty_line_height
            else:
                draw.text((60, y_offset), line, font=content_font, fill=self.TEXT_COLOR)
                y_offset += line_height
                lines_drawn += 1

        y_offset += 30

        # Code block
        code_lines = code_snippet.strip().split('\n')[:10]  # Max 10 lines

        # Calculate code block height
        code_line_height = 30
        code_block_height = len(code_lines) * code_line_height + 60

        # Draw code background
        draw.rounded_rectangle(
            [40, y_offset, self.WIDTH - 40, y_offset + code_block_height],
            radius=15,
            fill=self.CODE_BG
        )

        # Language badge
        if code_language:
            lang_text = code_language.upper()
            bbox = draw.textbbox((0, 0), lang_text, font=lang_font)
            lang_width = bbox[2] - bbox[0]
            draw.rounded_rectangle(
                [60, y_offset + 10, 80 + lang_width, y_offset + 35],
                radius=8,
                fill=self.ACCENT_COLOR
            )
            draw.text((70, y_offset + 12), lang_text, font=lang_font, fill=self.TEXT_COLOR)

        y_offset += 50

        # Code lines
        for code_line in code_lines:
            # Truncate long lines
            if len(code_line) > 45:
                code_line = code_line[:42] + '...'
            draw.text((60, y_offset), code_line, font=code_font, fill=self.CODE_COLOR)
            y_offset += code_line_height

        # Swipe dots
        self._draw_swipe_dots(draw, card_index, total_cards, self.HEIGHT - 120)

        # Brand name
        bbox = draw.textbbox((0, 0), self.handle_name, font=brand_font)
        brand_width = bbox[2] - bbox[0]
        draw.text(
            ((self.WIDTH - brand_width) // 2, self.HEIGHT - 60),
            self.handle_name,
            font=brand_font,
            fill=self.MUTED_TEXT
        )

        # Bottom accent bar
        draw.rectangle([0, self.HEIGHT - 8, self.WIDTH, self.HEIGHT], fill=self.ACCENT_COLOR)

        return img

    def _create_image_card(self, card_index, total_cards, title, content, image_url, image_caption):
        """Create a text + image card"""
        img = Image.new('RGB', (self.WIDTH, self.HEIGHT), self.BG_COLOR)
        draw = ImageDraw.Draw(img)

        # Top accent bar
        draw.rectangle([0, 0, self.WIDTH, 8], fill=self.ACCENT_COLOR)

        # Fonts
        title_font = self._get_font(40, bold=True)
        content_font = self._get_font(32)
        caption_font = self._get_font(24)
        brand_font = self._get_font(28)

        y_offset = 80

        # Card number badge
        card_num_text = f"{card_index + 1}/{total_cards}"
        badge_font = self._get_font(28)
        bbox = draw.textbbox((0, 0), card_num_text, font=badge_font)
        badge_width = bbox[2] - bbox[0]
        draw.rounded_rectangle(
            [self.WIDTH - badge_width - 60, y_offset - 5,
             self.WIDTH - 40, y_offset + 35],
            radius=15,
            fill=self.CARD_BG
        )
        draw.text(
            (self.WIDTH - badge_width - 50, y_offset),
            card_num_text,
            font=badge_font,
            fill=self.ACCENT_COLOR
        )

        y_offset += 60

        # Title (if provided)
        if title:
            max_width = self.WIDTH - 120
            title_lines = self._wrap_text(title, title_font, max_width, draw)
            line_height = 50

            for line in title_lines:
                draw.text((60, y_offset), line, font=title_font, fill=self.ACCENT_COLOR)
                y_offset += line_height

            y_offset += 20

        # Content (shorter for image cards)
        max_width = self.WIDTH - 120
        content_lines = self._wrap_text(content, content_font, max_width, draw)
        line_height = 42
        empty_line_height = 20

        lines_drawn = 0
        for line in content_lines:
            if lines_drawn >= 3:  # Limit to 3 lines for image cards
                break
            if line == '':
                y_offset += empty_line_height
            else:
                draw.text((60, y_offset), line, font=content_font, fill=self.TEXT_COLOR)
                y_offset += line_height
                lines_drawn += 1

        y_offset += 30

        # Load and place image
        try:
            if image_url:
                response = requests.get(image_url, timeout=10)
                response.raise_for_status()
                card_image = Image.open(BytesIO(response.content))

                # Calculate image size (max width: WIDTH - 80, max height: 400)
                max_img_width = self.WIDTH - 80
                max_img_height = 400

                # Resize maintaining aspect ratio
                img_ratio = card_image.width / card_image.height
                if card_image.width > max_img_width:
                    new_width = max_img_width
                    new_height = int(new_width / img_ratio)
                else:
                    new_width = card_image.width
                    new_height = card_image.height

                if new_height > max_img_height:
                    new_height = max_img_height
                    new_width = int(new_height * img_ratio)

                card_image = card_image.resize((new_width, new_height), Image.Resampling.LANCZOS)

                # Center image horizontally
                img_x = (self.WIDTH - new_width) // 2
                img.paste(card_image, (img_x, y_offset))

                y_offset += new_height + 15

                # Caption
                if image_caption:
                    bbox = draw.textbbox((0, 0), image_caption, font=caption_font)
                    caption_width = bbox[2] - bbox[0]
                    draw.text(
                        ((self.WIDTH - caption_width) // 2, y_offset),
                        image_caption,
                        font=caption_font,
                        fill=self.MUTED_TEXT
                    )

        except Exception as e:
            # Show placeholder if image fails to load
            draw.rounded_rectangle(
                [40, y_offset, self.WIDTH - 40, y_offset + 200],
                radius=15,
                fill=self.CARD_BG
            )
            error_text = "Image unavailable"
            bbox = draw.textbbox((0, 0), error_text, font=content_font)
            error_width = bbox[2] - bbox[0]
            draw.text(
                ((self.WIDTH - error_width) // 2, y_offset + 80),
                error_text,
                font=content_font,
                fill=self.MUTED_TEXT
            )

        # Swipe dots
        self._draw_swipe_dots(draw, card_index, total_cards, self.HEIGHT - 120)

        # Brand name
        bbox = draw.textbbox((0, 0), self.handle_name, font=brand_font)
        brand_width = bbox[2] - bbox[0]
        draw.text(
            ((self.WIDTH - brand_width) // 2, self.HEIGHT - 60),
            self.handle_name,
            font=brand_font,
            fill=self.MUTED_TEXT
        )

        # Bottom accent bar
        draw.rectangle([0, self.HEIGHT - 8, self.WIDTH, self.HEIGHT], fill=self.ACCENT_COLOR)

        return img

    def _create_outro_card(self, topic_title, has_quiz=False):
        """Create outro card with call-to-action"""
        img = Image.new('RGB', (self.WIDTH, self.HEIGHT), self.BG_COLOR)
        draw = ImageDraw.Draw(img)

        # Top accent bar
        draw.rectangle([0, 0, self.WIDTH, 8], fill=self.ACCENT_COLOR)

        # Fonts
        title_font = self._get_font(48, bold=True)
        subtitle_font = self._get_font(36)
        brand_font = self._get_font(32, bold=True)
        handle_font = self._get_font(28)

        center_y = self.HEIGHT // 2 - 150

        # Decorative circle
        circle_radius = 80
        circle_center = (self.WIDTH // 2, center_y)
        draw.ellipse(
            [circle_center[0] - circle_radius, circle_center[1] - circle_radius,
             circle_center[0] + circle_radius, circle_center[1] + circle_radius],
            fill=self.CARD_BG,
            outline=self.ACCENT_COLOR,
            width=4
        )

        # Checkmark
        check_font = self._get_font(72, bold=True)
        draw.text(circle_center, "✓", font=check_font, fill=self.ACCENT_COLOR, anchor="mm")

        center_y += circle_radius + 60

        # "Topic Complete!" text
        complete_text = "Topic Complete!"
        bbox = draw.textbbox((0, 0), complete_text, font=title_font)
        text_width = bbox[2] - bbox[0]
        draw.text(
            ((self.WIDTH - text_width) // 2, center_y),
            complete_text,
            font=title_font,
            fill=self.TEXT_COLOR
        )

        center_y += 70

        # Topic title
        max_width = self.WIDTH - 120
        title_lines = self._wrap_text(topic_title, subtitle_font, max_width, draw)

        for line in title_lines:
            bbox = draw.textbbox((0, 0), line, font=subtitle_font)
            line_width = bbox[2] - bbox[0]
            draw.text(
                ((self.WIDTH - line_width) // 2, center_y),
                line,
                font=subtitle_font,
                fill=self.MUTED_TEXT
            )
            center_y += 50

        center_y += 40

        # Call to action
        cta_text = "Follow for more!"
        bbox = draw.textbbox((0, 0), cta_text, font=subtitle_font)
        cta_width = bbox[2] - bbox[0]
        draw.text(
            ((self.WIDTH - cta_width) // 2, center_y),
            cta_text,
            font=subtitle_font,
            fill=self.ACCENT_COLOR
        )

        # Brand name at bottom
        bbox = draw.textbbox((0, 0), self.handle_name, font=brand_font)
        brand_width = bbox[2] - bbox[0]
        draw.text(
            ((self.WIDTH - brand_width) // 2, self.HEIGHT - 80),
            self.handle_name,
            font=brand_font,
            fill=self.ACCENT_COLOR
        )

        # Bottom accent bar
        draw.rectangle([0, self.HEIGHT - 8, self.WIDTH, self.HEIGHT], fill=self.ACCENT_COLOR)

        return img

    def generate_carousel_images(self, topic, cards, include_intro=True, include_outro=True, progress_callback=None):
        """
        Generate all carousel images for a topic.

        Args:
            topic: Topic model instance
            cards: List of TopicCard instances
            include_intro: Whether to include intro card
            include_outro: Whether to include outro card
            progress_callback: Optional callback function(current, total, message)

        Returns:
            List of PIL Image objects
        """
        images = []
        total_cards = len(cards)
        total_images = total_cards + (1 if include_intro else 0) + (1 if include_outro else 0)
        current = 0

        # Intro card
        if include_intro:
            if progress_callback:
                progress_callback(current, total_images, "Creating intro card...")
            intro = self._create_intro_card(
                topic.title,
                total_cards,
                topic.category.name if topic.category else None
            )
            images.append(intro)
            current += 1

        # Content cards
        for i, card in enumerate(cards):
            if progress_callback:
                progress_callback(current, total_images, f"Creating card {i + 1}/{total_cards}...")

            if card.card_type == 'text':
                img = self._create_text_card(i, total_cards, card.title, card.content)
            elif card.card_type == 'text_code':
                img = self._create_code_card(
                    i, total_cards, card.title, card.content,
                    card.code_snippet, card.code_language
                )
            elif card.card_type == 'text_image':
                img = self._create_image_card(
                    i, total_cards, card.title, card.content,
                    card.image_url, card.image_caption
                )
            else:
                img = self._create_text_card(i, total_cards, card.title, card.content)

            images.append(img)
            current += 1

        # Outro card
        if include_outro:
            if progress_callback:
                progress_callback(current, total_images, "Creating outro card...")
            outro = self._create_outro_card(topic.title, topic.has_mini_quiz)
            images.append(outro)
            current += 1

        if progress_callback:
            progress_callback(total_images, total_images, "Complete!")

        return images

    def save_images(self, images, output_dir=None):
        """
        Save images to files.

        Args:
            images: List of PIL Image objects
            output_dir: Directory to save to (defaults to temp_dir)

        Returns:
            List of file paths
        """
        if output_dir is None:
            output_dir = self.temp_dir

        os.makedirs(output_dir, exist_ok=True)
        paths = []

        for i, img in enumerate(images):
            filename = f"card_{i:03d}.jpg"
            filepath = os.path.join(output_dir, filename)
            img.save(filepath, "JPEG", quality=95)
            paths.append(filepath)

        return paths

    def cleanup(self):
        """Clean up temporary files"""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)


def generate_topic_carousel(topic, cards, handle_name="@maedix", template_config=None,
                            include_intro=True, include_outro=True, progress_callback=None):
    """
    Convenience function to generate topic carousel images.

    Returns:
        tuple: (list of PIL Images, generator instance for cleanup)
    """
    generator = TopicCardImageGenerator(handle_name=handle_name, template_config=template_config)
    images = generator.generate_carousel_images(
        topic, cards,
        include_intro=include_intro,
        include_outro=include_outro,
        progress_callback=progress_callback
    )
    return images, generator
