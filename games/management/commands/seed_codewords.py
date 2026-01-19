from django.core.management.base import BaseCommand
from games.models import Category, WordBank

# Categories to create
CATEGORIES = [
    ('web', 'Web Development', 'bi-globe', 'text-primary', 1),
    ('database', 'Database', 'bi-database', 'text-success', 2),
    ('programming', 'Programming', 'bi-code-slash', 'text-info', 3),
    ('devops', 'DevOps', 'bi-gear', 'text-warning', 4),
    ('security', 'Security', 'bi-shield-lock', 'text-danger', 5),
    ('data', 'Data Structures', 'bi-diagram-3', 'text-purple', 6),
    ('mobile', 'Mobile', 'bi-phone', 'text-teal', 7),
    ('systems', 'Systems', 'bi-cpu', 'text-secondary', 8),
    ('tools', 'Tools', 'bi-tools', 'text-orange', 9),
    ('general', 'General Tech', 'bi-puzzle', 'text-muted', 10),
]

# Words: (word, category_slug, difficulty, hint)
TECH_WORDS = [
    # Web Development (5 letters)
    ('REACT', 'web', 'easy', 'JavaScript library for UI'),
    ('FLASK', 'web', 'medium', 'Python web framework'),
    ('NGINX', 'web', 'medium', 'Web server'),
    ('FETCH', 'web', 'easy', 'HTTP request API'),
    ('ROUTE', 'web', 'easy', 'URL path'),
    ('PATCH', 'web', 'medium', 'HTTP method'),
    ('FORMS', 'web', 'easy', 'Input collection'),
    ('CLICK', 'web', 'easy', 'Mouse action'),
    ('HOVER', 'web', 'easy', 'Mouse over'),
    ('FOCUS', 'web', 'easy', 'Input active'),
    ('STYLE', 'web', 'easy', 'CSS property'),
    ('FONTS', 'web', 'easy', 'Text typeface'),
    ('COLOR', 'web', 'easy', 'Visual hue'),
    ('WIDTH', 'web', 'easy', 'Horizontal size'),
    ('MODAL', 'web', 'easy', 'Popup dialog'),
    ('ALERT', 'web', 'easy', 'Warning message'),
    ('TOAST', 'web', 'medium', 'Notification popup'),
    ('CARDS', 'web', 'easy', 'UI component'),
    ('PANEL', 'web', 'easy', 'UI section'),
    ('ADMIN', 'web', 'easy', 'Administrator'),
    ('USERS', 'web', 'easy', 'System accounts'),
    ('PROPS', 'web', 'easy', 'React properties'),
    ('STATE', 'web', 'easy', 'Component data'),
    ('HOOKS', 'web', 'medium', 'React functions'),
    ('STORE', 'web', 'medium', 'State container'),
    ('MODEL', 'web', 'easy', 'Data representation'),
    ('VIEWS', 'web', 'easy', 'UI layer'),
    ('FRAME', 'web', 'easy', 'Window container'),

    # Database (5 letters)
    ('MYSQL', 'database', 'easy', 'Popular database'),
    ('REDIS', 'database', 'medium', 'In-memory data store'),
    ('MONGO', 'database', 'medium', 'NoSQL database'),
    ('QUERY', 'database', 'easy', 'Database request'),
    ('INDEX', 'database', 'easy', 'Database optimization'),
    ('TABLE', 'database', 'easy', 'Database structure'),

    # Programming (5 letters)
    ('SWIFT', 'programming', 'medium', 'Apple programming language'),
    ('SCALA', 'programming', 'hard', 'JVM functional language'),
    ('JULIA', 'programming', 'hard', 'Scientific computing language'),
    ('CLANG', 'programming', 'hard', 'C language compiler'),
    ('ASYNC', 'programming', 'medium', 'Asynchronous programming'),
    ('AWAIT', 'programming', 'medium', 'Async keyword'),
    ('PARSE', 'programming', 'easy', 'Analyze syntax'),
    ('YIELD', 'programming', 'hard', 'Generator keyword'),
    ('PRINT', 'programming', 'easy', 'Output function'),
    ('INPUT', 'programming', 'easy', 'User input'),
    ('WHILE', 'programming', 'easy', 'Loop keyword'),
    ('BREAK', 'programming', 'easy', 'Loop exit'),
    ('CATCH', 'programming', 'easy', 'Exception handling'),
    ('THROW', 'programming', 'medium', 'Raise exception'),
    ('FINAL', 'programming', 'medium', 'Java keyword'),
    ('SUPER', 'programming', 'easy', 'Parent class reference'),
    ('TRAIT', 'programming', 'hard', 'Interface-like feature'),
    ('MIXIN', 'programming', 'hard', 'Multiple inheritance'),
    ('CONST', 'programming', 'easy', 'Constant declaration'),
    ('REGEX', 'programming', 'hard', 'Pattern matching'),
    ('DEBUG', 'programming', 'easy', 'Find bugs'),
    ('ARROW', 'programming', 'easy', 'Function syntax'),
    ('CHAIN', 'programming', 'easy', 'Method linking'),
    ('BLOCK', 'programming', 'easy', 'Code segment'),
    ('SCOPE', 'programming', 'medium', 'Variable visibility'),
    ('LAYER', 'programming', 'easy', 'System level'),
    ('LOOPS', 'programming', 'easy', 'Iteration'),
    ('LOGIC', 'programming', 'easy', 'Boolean operations'),
    ('DRAFT', 'programming', 'easy', 'Preliminary version'),
    ('DEPTH', 'programming', 'medium', 'Nested level'),
    ('FLAGS', 'programming', 'easy', 'Boolean indicators'),
    ('ENUMS', 'programming', 'medium', 'Named constants'),
    ('TYPES', 'programming', 'easy', 'Data categories'),
    ('TYPED', 'programming', 'easy', 'With type info'),
    ('EVENT', 'programming', 'easy', 'Action occurrence'),
    ('TIMER', 'programming', 'easy', 'Time tracking'),
    ('DATES', 'programming', 'easy', 'Calendar values'),
    ('EPOCH', 'programming', 'hard', 'Time reference point'),
    ('CLASS', 'programming', 'easy', 'OOP blueprint'),
    ('ERROR', 'programming', 'easy', 'Program mistake'),
    ('FAULT', 'programming', 'medium', 'System error'),
    ('VALID', 'programming', 'easy', 'Correctly formed'),
    ('BLANK', 'programming', 'easy', 'Empty value'),
    ('EMPTY', 'programming', 'easy', 'No content'),
    ('COUNT', 'programming', 'easy', 'Number of items'),
    ('TOTAL', 'programming', 'easy', 'Sum value'),
    ('MATCH', 'programming', 'easy', 'Pattern found'),
    ('SPLIT', 'programming', 'easy', 'Divide string'),
    ('STRIP', 'programming', 'easy', 'Remove whitespace'),
    ('SLICE', 'programming', 'easy', 'Array portion'),
    ('SHIFT', 'programming', 'easy', 'Array operation'),
    ('DELTA', 'programming', 'medium', 'Change/difference'),

    # Data Structures (5 letters)
    ('GRAPH', 'data', 'easy', 'Data structure'),
    ('STACK', 'data', 'easy', 'LIFO data structure'),
    ('QUEUE', 'data', 'easy', 'FIFO data structure'),
    ('ARRAY', 'data', 'easy', 'Data structure'),
    ('TUPLE', 'data', 'medium', 'Immutable sequence'),
    ('FLOAT', 'data', 'easy', 'Decimal number type'),
    ('NODES', 'data', 'medium', 'Graph vertices'),
    ('EDGES', 'data', 'medium', 'Graph connections'),
    ('TREES', 'data', 'easy', 'Hierarchical structure'),
    ('HEAPS', 'data', 'hard', 'Priority structure'),
    ('SORTS', 'data', 'easy', 'Ordering algorithms'),
    ('BYTES', 'data', 'easy', '8 bits'),
    ('SPARK', 'data', 'medium', 'Big data processing'),

    # DevOps (5 letters)
    ('BUILD', 'devops', 'easy', 'Compile project'),
    ('MERGE', 'devops', 'easy', 'Combine branches'),
    ('CLONE', 'devops', 'easy', 'Copy repository'),
    ('STASH', 'devops', 'medium', 'Save changes temporarily'),
    ('TRUNK', 'devops', 'medium', 'Main branch'),
    ('KAFKA', 'devops', 'hard', 'Message streaming'),
    ('CACHE', 'devops', 'medium', 'Temporary storage'),

    # Security (5 letters)
    ('TOKEN', 'security', 'medium', 'Authentication piece'),
    ('OAUTH', 'security', 'hard', 'Auth protocol'),
    ('HTTPS', 'security', 'easy', 'Secure HTTP'),
    ('ROLES', 'security', 'easy', 'Permission groups'),
    ('PERMS', 'security', 'medium', 'Permissions'),
    ('CRYPT', 'security', 'hard', 'Encryption'),
    ('SALTS', 'security', 'hard', 'Password addition'),
    ('HASHS', 'security', 'hard', 'One-way function'),
    ('PROXY', 'security', 'medium', 'Network intermediary'),

    # Mobile (5 letters)
    ('PIXEL', 'mobile', 'easy', 'Screen unit'),

    # Systems (5 letters)
    ('SHELL', 'systems', 'easy', 'Command interpreter'),
    ('LINUX', 'systems', 'easy', 'Operating system'),
    ('CHMOD', 'systems', 'hard', 'Change permissions'),
    ('CHOWN', 'systems', 'hard', 'Change ownership'),
    ('PORTS', 'systems', 'easy', 'Network endpoints'),
    ('SOCKS', 'systems', 'hard', 'Proxy protocol'),
    ('HOSTS', 'systems', 'easy', 'Server names'),
    ('PIPES', 'systems', 'medium', 'Data streams'),

    # Tools (5 letters)
    ('SLACK', 'tools', 'easy', 'Team communication'),
    ('AGILE', 'tools', 'easy', 'Development approach'),
    ('SCRUM', 'tools', 'medium', 'Agile framework'),
    ('PIVOT', 'tools', 'medium', 'Direction change'),
    ('SPECS', 'tools', 'medium', 'Test specifications'),
    ('TESTS', 'tools', 'easy', 'Code validation'),
    ('MOCKS', 'tools', 'medium', 'Fake objects'),
    ('STUBS', 'tools', 'hard', 'Partial implementations'),
    ('COVER', 'tools', 'medium', 'Code coverage'),
    ('BENCH', 'tools', 'medium', 'Performance test'),

    # General Tech (5 letters)
    ('ALPHA', 'general', 'easy', 'Early version'),
    ('GAMMA', 'general', 'medium', 'Third release'),
]


class Command(BaseCommand):
    help = 'Seed categories and words for Code Word game'

    def handle(self, *args, **options):
        # Step 1: Create categories
        self.stdout.write('Creating categories...')
        category_map = {}
        for slug, name, icon, color, order in CATEGORIES:
            cat, created = Category.objects.get_or_create(
                slug=slug,
                defaults={
                    'name': name,
                    'icon': icon,
                    'color': color,
                    'order': order,
                }
            )
            category_map[slug] = cat
            if created:
                self.stdout.write(self.style.SUCCESS(f'  Created category: {name}'))
            else:
                self.stdout.write(f'  Category exists: {name}')

        # Step 2: Create words
        self.stdout.write('')
        self.stdout.write('Creating words...')
        added = 0
        skipped = 0
        updated = 0

        for word_data in TECH_WORDS:
            word, category_slug, difficulty, hint = word_data

            # Only add 5-letter words
            if len(word) != 5:
                self.stdout.write(f'  Skipping {word} (not 5 letters)')
                skipped += 1
                continue

            category = category_map.get(category_slug)
            if not category:
                self.stdout.write(self.style.WARNING(f'  Skipping {word} (invalid category: {category_slug})'))
                skipped += 1
                continue

            word_obj, created = WordBank.objects.get_or_create(
                word=word.upper(),
                defaults={
                    'category': category,
                    'difficulty': difficulty,
                    'hint': hint,
                }
            )

            if created:
                added += 1
                self.stdout.write(self.style.SUCCESS(f'  Added: {word} ({category.name})'))
            else:
                # Update category if word exists but has no category
                if word_obj.category is None:
                    word_obj.category = category
                    word_obj.save()
                    updated += 1
                    self.stdout.write(f'  Updated category for: {word}')
                else:
                    skipped += 1

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'Done! Added {added} words, updated {updated}, skipped {skipped}'))
        self.stdout.write(f'Total words in bank: {WordBank.objects.count()}')

        # Show category breakdown
        self.stdout.write('')
        self.stdout.write('Category breakdown:')
        for cat in Category.objects.all().order_by('order'):
            count = cat.words.filter(is_active=True).count()
            self.stdout.write(f'  {cat.name}: {count} words')
