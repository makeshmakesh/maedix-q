from django.views.generic import ListView, DetailView
from django.shortcuts import get_object_or_404
from .models import BlogPost, Category


class BlogListView(ListView):
    """List all published blog posts"""
    model = BlogPost
    template_name = 'blog/blog_list.html'
    context_object_name = 'posts'
    paginate_by = 12

    def get_queryset(self):
        queryset = BlogPost.objects.filter(is_published=True)

        # Filter by category if provided
        category_slug = self.kwargs.get('category_slug')
        if category_slug:
            queryset = queryset.filter(category__slug=category_slug)

        return queryset.select_related('category')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['categories'] = Category.objects.all()

        # Current category if filtering
        category_slug = self.kwargs.get('category_slug')
        if category_slug:
            context['current_category'] = get_object_or_404(Category, slug=category_slug)

        return context


class BlogDetailView(DetailView):
    """Single blog post detail"""
    model = BlogPost
    template_name = 'blog/blog_detail.html'
    context_object_name = 'post'

    def get_queryset(self):
        # Show unpublished to staff, published to everyone else
        if self.request.user.is_staff:
            return BlogPost.objects.all()
        return BlogPost.objects.filter(is_published=True)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Related posts (same category, excluding current)
        if self.object.category:
            context['related_posts'] = BlogPost.objects.filter(
                is_published=True,
                category=self.object.category
            ).exclude(pk=self.object.pk)[:3]
        else:
            context['related_posts'] = BlogPost.objects.filter(
                is_published=True
            ).exclude(pk=self.object.pk)[:3]

        return context
