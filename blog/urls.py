from django.urls import path
from . import views

app_name = 'blog'

urlpatterns = [
    path('', views.BlogListView.as_view(), name='post_list'),
    path('category/<slug:category_slug>/', views.BlogListView.as_view(), name='category'),
    path('<slug:slug>/', views.BlogDetailView.as_view(), name='post_detail'),
]
