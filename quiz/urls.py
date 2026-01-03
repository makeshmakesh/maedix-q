from django.urls import path
from . import views

urlpatterns = [
    path('', views.QuizHomeView.as_view(), name='quiz_home'),
    path('categories/', views.CategoriesView.as_view(), name='categories'),
    path('category/<slug:slug>/', views.CategoryDetailView.as_view(), name='category_detail'),
    path('leaderboard/', views.LeaderboardView.as_view(), name='leaderboard'),
    path('leaderboard/<slug:slug>/', views.CategoryLeaderboardView.as_view(), name='category_leaderboard'),
    path('history/', views.QuizHistoryView.as_view(), name='quiz_history'),

    # Video export endpoints (must be before slug patterns)
    path('video/progress/<str:task_id>/', views.VideoProgressView.as_view(), name='video_progress'),
    path('video/download/<str:task_id>/', views.VideoDownloadView.as_view(), name='video_download'),

    # User Quiz Management (must be before slug patterns)
    path('my-quizzes/', views.UserQuizListView.as_view(), name='user_quiz_list'),
    path('my-quizzes/create/', views.UserQuizCreateView.as_view(), name='user_quiz_create'),
    path('my-quizzes/<int:pk>/edit/', views.UserQuizEditView.as_view(), name='user_quiz_edit'),
    path('my-quizzes/<int:pk>/delete/', views.UserQuizDeleteView.as_view(), name='user_quiz_delete'),
    path('my-quizzes/<int:pk>/questions/', views.UserQuizQuestionsView.as_view(), name='user_quiz_questions'),
    path('my-quizzes/<int:quiz_id>/questions/create/', views.UserQuestionCreateView.as_view(), name='user_question_create'),
    path('my-quizzes/<int:quiz_id>/questions/<int:pk>/edit/', views.UserQuestionEditView.as_view(), name='user_question_edit'),
    path('my-quizzes/<int:quiz_id>/questions/<int:pk>/delete/', views.UserQuestionDeleteView.as_view(), name='user_question_delete'),
    path('my-quizzes/<int:pk>/submit/', views.UserQuizSubmitApprovalView.as_view(), name='user_quiz_submit'),

    # Quiz attempt result (must be before slug patterns)
    path('attempt/<int:attempt_id>/result/', views.QuizResultView.as_view(), name='quiz_result'),

    # Staff Admin Portal (must be before slug patterns)
    path('staff/dashboard/', views.StaffDashboardView.as_view(), name='staff_dashboard'),

    # Category Management
    path('staff/categories/', views.StaffCategoryListView.as_view(), name='staff_category_list'),
    path('staff/categories/create/', views.StaffCategoryCreateView.as_view(), name='staff_category_create'),
    path('staff/categories/<int:pk>/edit/', views.StaffCategoryEditView.as_view(), name='staff_category_edit'),
    path('staff/categories/<int:pk>/delete/', views.StaffCategoryDeleteView.as_view(), name='staff_category_delete'),

    # Quiz Management
    path('staff/quizzes/', views.StaffQuizListView.as_view(), name='staff_quiz_list'),
    path('staff/quizzes/create/', views.StaffQuizCreateView.as_view(), name='staff_quiz_create'),
    path('staff/quizzes/import/', views.StaffQuizImportView.as_view(), name='staff_quiz_import'),
    path('staff/quizzes/<int:pk>/edit/', views.StaffQuizEditView.as_view(), name='staff_quiz_edit'),
    path('staff/quizzes/<int:pk>/delete/', views.StaffQuizDeleteView.as_view(), name='staff_quiz_delete'),

    # Question Management
    path('staff/quizzes/<int:quiz_id>/questions/', views.StaffQuestionListView.as_view(), name='staff_question_list'),
    path('staff/quizzes/<int:quiz_id>/questions/create/', views.StaffQuestionCreateView.as_view(), name='staff_question_create'),
    path('staff/quizzes/<int:quiz_id>/questions/<int:pk>/edit/', views.StaffQuestionEditView.as_view(), name='staff_question_edit'),
    path('staff/quizzes/<int:quiz_id>/questions/<int:pk>/delete/', views.StaffQuestionDeleteView.as_view(), name='staff_question_delete'),

    # Quiz Approval
    path('staff/approvals/', views.StaffPendingApprovalsView.as_view(), name='staff_pending_approvals'),
    path('staff/approvals/<int:pk>/preview/', views.StaffQuizPreviewView.as_view(), name='staff_quiz_preview'),
    path('staff/approvals/<int:pk>/approve/', views.StaffApproveQuizView.as_view(), name='staff_approve_quiz'),
    path('staff/approvals/<int:pk>/reject/', views.StaffRejectQuizView.as_view(), name='staff_reject_quiz'),

    # Quiz detail and related pages (slug patterns MUST be last)
    path('<slug:slug>/', views.QuizDetailView.as_view(), name='quiz_detail'),
    path('<slug:slug>/export-video/', views.QuizVideoExportView.as_view(), name='quiz_video_export'),
    path('<slug:slug>/start/', views.QuizStartView.as_view(), name='quiz_start'),
    path('<slug:slug>/question/<int:q_num>/', views.QuizQuestionView.as_view(), name='quiz_question'),
    path('<slug:slug>/submit/', views.QuizSubmitView.as_view(), name='quiz_submit'),
]
