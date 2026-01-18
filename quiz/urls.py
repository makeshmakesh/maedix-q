from django.urls import path
from . import views

urlpatterns = [
    path('', views.QuizHomeView.as_view(), name='quiz_home'),
    path('categories/', views.CategoriesView.as_view(), name='categories'),
    path('category/<slug:slug>/', views.CategoryDetailView.as_view(), name='category_detail'),
    path('history/', views.QuizHistoryView.as_view(), name='quiz_history'),

    # Video export endpoints (must be before slug patterns)
    path('video/progress/<str:task_id>/', views.VideoProgressView.as_view(), name='video_progress'),
    path('video/download/<str:task_id>/', views.VideoDownloadView.as_view(), name='video_download'),
    path('video/url/<str:task_id>/', views.VideoUrlView.as_view(), name='video_url'),
    # New Video Job Management endpoints
    path('video/jobs/', views.VideoJobListView.as_view(), name='video_job_list'),
    path('video/jobs/<int:job_id>/', views.VideoJobDetailView.as_view(), name='video_job_detail'),
    path('video/jobs/<int:job_id>/status/', views.VideoJobStatusAPIView.as_view(), name='video_job_status'),
    path('video/bulk-group/<uuid:bulk_group_id>/status/', views.BulkGroupStatusAPIView.as_view(), name='bulk_group_status'),

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

    # User Topic Management (must be before slug patterns)
    path('my-topics/', views.UserTopicListView.as_view(), name='user_topic_list'),
    path('my-topics/create/', views.UserTopicCreateView.as_view(), name='user_topic_create'),
    path('my-topics/<int:pk>/edit/', views.UserTopicEditView.as_view(), name='user_topic_edit'),
    path('my-topics/<int:pk>/delete/', views.UserTopicDeleteView.as_view(), name='user_topic_delete'),
    path('my-topics/<int:pk>/cards/', views.UserTopicCardsView.as_view(), name='user_topic_cards'),
    path('my-topics/<int:topic_id>/cards/create/', views.UserCardCreateView.as_view(), name='user_card_create'),
    path('my-topics/<int:topic_id>/cards/<int:pk>/edit/', views.UserCardEditView.as_view(), name='user_card_edit'),
    path('my-topics/<int:topic_id>/cards/<int:pk>/delete/', views.UserCardDeleteView.as_view(), name='user_card_delete'),
    path('my-topics/<int:pk>/submit/', views.UserTopicSubmitApprovalView.as_view(), name='user_topic_submit'),

    # Quiz attempt result (must be before slug patterns)
    path('attempt/<int:attempt_id>/result/', views.QuizResultView.as_view(), name='quiz_result'),

    # Staff Admin Portal (must be before slug patterns)
    path('staff/dashboard/', views.StaffDashboardView.as_view(), name='staff_dashboard'),
    path('staff/upload-image/', views.StaffImageUploadView.as_view(), name='staff_image_upload'),

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

    # Topic Approval
    path('staff/approvals/topic/<int:pk>/preview/', views.StaffTopicPreviewView.as_view(), name='staff_topic_preview'),
    path('staff/approvals/topic/<int:pk>/approve/', views.StaffApproveTopicView.as_view(), name='staff_approve_topic'),
    path('staff/approvals/topic/<int:pk>/reject/', views.StaffRejectTopicView.as_view(), name='staff_reject_topic'),

    # Staff Topic Management
    path('staff/topics/', views.StaffTopicListView.as_view(), name='staff_topic_list'),
    path('staff/topics/import/', views.StaffTopicImportView.as_view(), name='staff_topic_import'),
    path('staff/topics/create/', views.StaffTopicCreateView.as_view(), name='staff_topic_create'),
    path('staff/topics/<int:pk>/edit/', views.StaffTopicEditView.as_view(), name='staff_topic_edit'),
    path('staff/topics/<int:pk>/delete/', views.StaffTopicDeleteView.as_view(), name='staff_topic_delete'),
    path('staff/topics/<int:topic_id>/cards/', views.StaffTopicCardsView.as_view(), name='staff_topic_cards'),
    path('staff/topics/<int:topic_id>/cards/create/', views.StaffCardCreateView.as_view(), name='staff_card_create'),
    path('staff/topics/<int:topic_id>/cards/<int:pk>/edit/', views.StaffCardEditView.as_view(), name='staff_card_edit'),
    path('staff/topics/<int:topic_id>/cards/<int:pk>/delete/', views.StaffCardDeleteView.as_view(), name='staff_card_delete'),

    # Public Topics (must be before quiz slug patterns)
    path('topics/', views.TopicsHomeView.as_view(), name='topics_home'),
    path('topics/my-progress/', views.TopicProgressView.as_view(), name='topic_my_progress'),
    path('topics/export/progress/<str:task_id>/', views.TopicExportProgressView.as_view(), name='topic_export_progress'),
    path('topics/category/<slug:slug>/', views.TopicCategoryView.as_view(), name='topic_category'),
    path('topics/<slug:slug>/', views.TopicDetailView.as_view(), name='topic_detail'),
    path('topics/<slug:slug>/card/<int:card_num>/', views.TopicCardView.as_view(), name='topic_card'),
    path('topics/<slug:slug>/complete/', views.TopicCompleteView.as_view(), name='topic_complete'),
    path('topics/<slug:slug>/quiz/', views.TopicMiniQuizView.as_view(), name='topic_mini_quiz'),
    path('topics/<slug:slug>/export/', views.TopicExportView.as_view(), name='topic_export'),
    path('topics/<slug:slug>/post-instagram/', views.TopicPostInstagramView.as_view(), name='topic_post_instagram'),

    # Quiz detail and related pages (slug patterns MUST be last)
    path('<slug:slug>/', views.QuizDetailView.as_view(), name='quiz_detail'),
    path('<slug:slug>/export-video/', views.QuizVideoExportView.as_view(), name='quiz_video_export'),
    path('<slug:slug>/bulk-export/', views.BulkVideoExportView.as_view(), name='quiz_bulk_video_export'),

    # New video export flow
    path('<slug:slug>/video/', views.VideoExportChoiceView.as_view(), name='video_export_choice'),
    path('<slug:slug>/video/single/', views.SingleVideoCreateView.as_view(), name='single_video_create'),
    path('<slug:slug>/video/bulk/', views.BulkVideoCreateView.as_view(), name='bulk_video_create'),

    path('<slug:slug>/start/', views.QuizStartView.as_view(), name='quiz_start'),
    path('<slug:slug>/question/<int:q_num>/', views.QuizQuestionView.as_view(), name='quiz_question'),
    path('<slug:slug>/submit/', views.QuizSubmitView.as_view(), name='quiz_submit'),
]
