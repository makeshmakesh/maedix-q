from django.urls import path
from . import views

urlpatterns = [
    # Games hub
    path('', views.GamesHomeView.as_view(), name='games_home'),

    # Code Word
    path('codeword/', views.CodeWordHomeView.as_view(), name='codeword_home'),
    path('codeword/play/', views.CodeWordPlayView.as_view(), name='codeword_play'),
    path('codeword/new/', views.CodeWordNewGameView.as_view(), name='codeword_new'),
    path('codeword/guess/', views.CodeWordGuessView.as_view(), name='codeword_guess'),
    path('codeword/results/<uuid:session_id>/', views.CodeWordResultsView.as_view(), name='codeword_results'),
    path('codeword/stats/', views.CodeWordStatsView.as_view(), name='codeword_stats'),

    # Staff Code Word Management
    path('staff/codeword/', views.StaffCodeWordDashboardView.as_view(), name='staff_codeword_dashboard'),

    # Staff Category Management
    path('staff/codeword/categories/', views.StaffCodeWordCategoryListView.as_view(), name='staff_codeword_category_list'),
    path('staff/codeword/categories/create/', views.StaffCodeWordCategoryCreateView.as_view(), name='staff_codeword_category_create'),
    path('staff/codeword/categories/<int:pk>/edit/', views.StaffCodeWordCategoryEditView.as_view(), name='staff_codeword_category_edit'),
    path('staff/codeword/categories/<int:pk>/delete/', views.StaffCodeWordCategoryDeleteView.as_view(), name='staff_codeword_category_delete'),

    # Staff Word Management
    path('staff/codeword/words/', views.StaffCodeWordWordListView.as_view(), name='staff_codeword_word_list'),
    path('staff/codeword/words/create/', views.StaffCodeWordWordCreateView.as_view(), name='staff_codeword_word_create'),
    path('staff/codeword/words/import/', views.StaffCodeWordImportView.as_view(), name='staff_codeword_import'),
    path('staff/codeword/words/<int:pk>/edit/', views.StaffCodeWordWordEditView.as_view(), name='staff_codeword_word_edit'),
    path('staff/codeword/words/<int:pk>/delete/', views.StaffCodeWordWordDeleteView.as_view(), name='staff_codeword_word_delete'),
]
