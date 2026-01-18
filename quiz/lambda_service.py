"""
Lambda service for video generation.
Handles Lambda invocation and DynamoDB polling for job status.
"""
import json
import uuid
import logging
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

from core.models import Configuration

logger = logging.getLogger(__name__)


def get_instagram_credentials(user):
    """
    Get Instagram credentials for a user if they have a connected account.

    Returns:
        dict with credentials or None if not connected
    """
    try:
        ig_account = user.instagram_account
        if not ig_account or not ig_account.is_active:
            return None

        return {
            'access_token': ig_account.access_token,
            'instagram_user_id': ig_account.instagram_user_id,
        }
    except Exception:
        return None


def get_youtube_credentials(user):
    """
    Get YouTube credentials for a user if they have a connected account.

    Returns:
        dict with credentials or None if not connected
    """
    try:
        yt_account = user.youtube_account
        if not yt_account or not yt_account.is_active:
            return None

        return {
            'access_token': yt_account.access_token,
            'refresh_token': yt_account.refresh_token,
            'client_id': Configuration.get_value('youtube_client_id', ''),
            'client_secret': Configuration.get_value('youtube_client_secret', ''),
        }
    except Exception:
        return None

# AWS region for Lambda and DynamoDB
AWS_REGION = 'us-east-1'


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that handles Decimal types from DynamoDB"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def get_lambda_client():
    """Get boto3 Lambda client"""
    return boto3.client('lambda', region_name=AWS_REGION)


def get_dynamodb_resource():
    """Get boto3 DynamoDB resource"""
    return boto3.resource('dynamodb', region_name=AWS_REGION)


def is_lambda_enabled():
    """Check if Lambda video generation is enabled via Configuration"""
    return Configuration.get_value('use_lambda_video_gen', 'false').lower() == 'true'


def get_lambda_function_name():
    """Get Lambda function name from Configuration"""
    return Configuration.get_value('lambda_video_function', 'maedix-video-generator-production')


def get_dynamodb_table_name():
    """Get DynamoDB table name from Configuration"""
    return Configuration.get_value('dynamodb_video_jobs_table', 'video_generation_jobs')


def get_s3_bucket_name():
    """Get S3 bucket name from Configuration"""
    return Configuration.get_value('video_s3_bucket', 'maedix-q')


def serialize_questions(questions):
    """
    Serialize questions for Lambda payload.

    Args:
        questions: List of Question model instances or dicts

    Returns:
        List of question dicts suitable for Lambda
    """
    question_data = []
    for q in questions:
        if hasattr(q, 'text'):
            # It's a model instance
            question_data.append({
                'text': q.text,
                'code_snippet': getattr(q, 'code_snippet', '') or '',
                'code_language': getattr(q, 'code_language', 'python') or 'python',
                'explanation': getattr(q, 'explanation', '') or '',
                'options': [
                    {'text': opt.text, 'is_correct': opt.is_correct}
                    for opt in q.options.all()
                ]
            })
        else:
            # Already a dict
            question_data.append(q)
    return question_data


def invoke_video_generation(user, quiz, questions, config, social_posting=None):
    """
    Invoke Lambda function to generate video asynchronously.

    Args:
        user: Django User instance
        quiz: Quiz model instance
        questions: List of Question instances or question dicts
        config: Dict with video generation config options:
            - show_answer: bool
            - handle_name: str
            - audio_url: str or None
            - audio_volume: float
            - intro_text: str or None
            - intro_audio_url: str or None
            - intro_audio_volume: float
            - pre_outro_text: str or None
            - quiz_heading: str or None
            - template_config: dict or None
            - answer_reveal_audio_url: str or None
            - answer_reveal_audio_volume: float
        social_posting: Optional dict with social media posting options:
            - post_to_instagram: bool
            - post_to_youtube: bool
            - caption: str (for Instagram)
            - title: str (for YouTube)
            - description: str (for YouTube)

    Returns:
        task_id: str - UUID for tracking the job

    Raises:
        Exception if Lambda invocation fails
    """
    task_id = str(uuid.uuid4())

    # Build Lambda payload
    payload = {
        'task_id': task_id,
        'quiz_slug': quiz.slug,
        'quiz_title': quiz.title,
        'questions': serialize_questions(questions),
        'config': {
            'show_answer': config.get('show_answer', True),
            'handle_name': config.get('handle_name', '@maedix-q'),
            'audio_url': config.get('audio_url'),
            'audio_volume': config.get('audio_volume', 0.3),
            'intro_text': config.get('intro_text'),
            'intro_audio_url': config.get('intro_audio_url'),
            'intro_audio_volume': config.get('intro_audio_volume', 0.5),
            'pre_outro_text': config.get('pre_outro_text', 'Comment your answer!'),
            'quiz_heading': config.get('quiz_heading'),
            'template_config': config.get('template_config'),
            'answer_reveal_audio_url': config.get('answer_reveal_audio_url'),
            'answer_reveal_audio_volume': config.get('answer_reveal_audio_volume', 0.5)
        },
        's3_output_key': f'videos/{task_id}/{quiz.slug}_reel.mp4',
        'user_id': user.id,
        'quiz_id': quiz.id
    }

    # Add social media posting configuration if provided
    if social_posting:
        posting_config = {
            'post_to_instagram': social_posting.get('post_to_instagram', False),
            'post_to_youtube': social_posting.get('post_to_youtube', False),
            'caption': social_posting.get('caption', ''),
            'title': social_posting.get('title', quiz.title),
            'description': social_posting.get('description', ''),
        }

        # Add Instagram credentials if posting to Instagram
        if posting_config['post_to_instagram']:
            ig_creds = get_instagram_credentials(user)
            if ig_creds:
                posting_config['instagram_credentials'] = ig_creds
            else:
                logger.warning(f"User {user.id} requested Instagram posting but has no connected account")
                posting_config['post_to_instagram'] = False

        # Add YouTube credentials if posting to YouTube
        if posting_config['post_to_youtube']:
            yt_creds = get_youtube_credentials(user)
            if yt_creds:
                posting_config['youtube_credentials'] = yt_creds
            else:
                logger.warning(f"User {user.id} requested YouTube posting but has no connected account")
                posting_config['post_to_youtube'] = False

        payload['social_posting'] = posting_config

    try:
        client = get_lambda_client()
        function_name = get_lambda_function_name()

        logger.info(f"Invoking Lambda function {function_name} for task {task_id}")

        response = client.invoke(
            FunctionName=function_name,
            InvocationType='Event',  # Async invocation
            Payload=json.dumps(payload)
        )

        status_code = response.get('StatusCode')
        if status_code not in [200, 202]:
            logger.error(f"Lambda invocation failed with status {status_code}")
            raise Exception(f"Lambda invocation failed with status {status_code}")

        logger.info(f"Lambda invoked successfully for task {task_id}")
        return task_id

    except ClientError as e:
        logger.error(f"AWS error invoking Lambda: {e}")
        raise Exception(f"Failed to start video generation: {str(e)}")


def get_job_status(task_id):
    """
    Get job status from DynamoDB.

    Args:
        task_id: str - UUID of the job

    Returns:
        dict with job status:
            - status: 'pending', 'processing', 'completed', 'failed'
            - progress_percent: int (0-100)
            - progress_message: str
            - s3_url: str (when completed)
            - s3_key: str (when completed)
            - instagram_posted: bool
            - youtube_posted: bool
            - instagram_error: str or None
            - youtube_error: str or None

        Returns empty dict if job not found
    """
    try:
        dynamodb = get_dynamodb_resource()
        table_name = get_dynamodb_table_name()
        table = dynamodb.Table(table_name)

        response = table.get_item(Key={'task_id': task_id})
        item = response.get('Item', {})

        if not item:
            return {}

        # Convert Decimal types to Python native types
        return {
            'status': item.get('status', 'pending'),
            'progress_percent': int(item.get('progress_percent', 0)),
            'progress_message': item.get('progress_message', ''),
            's3_url': item.get('s3_url'),
            's3_key': item.get('s3_key'),
            'user_id': item.get('user_id'),
            'quiz_id': item.get('quiz_id'),
            'created_at': item.get('created_at'),
            'updated_at': item.get('updated_at'),
            # Social posting results
            'post_to_instagram': item.get('post_to_instagram', False),
            'post_to_youtube': item.get('post_to_youtube', False),
            'instagram_posted': item.get('instagram_posted', False),
            'youtube_posted': item.get('youtube_posted', False),
            'instagram_error': item.get('instagram_error'),
            'youtube_error': item.get('youtube_error'),
        }

    except ClientError as e:
        logger.error(f"Error getting job status from DynamoDB: {e}")
        return {
            'status': 'error',
            'progress_percent': 0,
            'progress_message': f'Error checking status: {str(e)}'
        }


def get_job_status_for_view(task_id):
    """
    Get job status formatted for the VideoProgressView API response.

    Args:
        task_id: str - UUID of the job

    Returns:
        dict compatible with existing VideoProgressView response format:
            - percent: int (0-100)
            - message: str
            - status: 'processing', 'completed', 'error'
            - social_posting: dict with posting results (when completed)
    """
    job = get_job_status(task_id)

    if not job:
        return {
            'percent': 0,
            'message': 'Task not found',
            'status': 'error'
        }

    # Map DynamoDB status to view format
    status_mapping = {
        'pending': 'processing',
        'processing': 'processing',
        'completed': 'completed',
        'failed': 'error'
    }

    result = {
        'percent': job.get('progress_percent', 0),
        'message': job.get('progress_message', ''),
        'status': status_mapping.get(job.get('status'), 'error')
    }

    # Include social posting results if job is completed
    if job.get('status') == 'completed':
        result['social_posting'] = {
            'instagram_posted': job.get('instagram_posted', False),
            'youtube_posted': job.get('youtube_posted', False),
            'instagram_error': job.get('instagram_error'),
            'youtube_error': job.get('youtube_error'),
        }

    return result


def get_video_data_for_download(task_id):
    """
    Get video data for download, compatible with existing VideoDownloadView.

    Args:
        task_id: str - UUID of the job

    Returns:
        dict with video data:
            - s3_url: str
            - s3_key: str
            - filename: str

        Returns None if video not ready or not found
    """
    job = get_job_status(task_id)

    if not job or job.get('status') != 'completed':
        return None

    s3_url = job.get('s3_url')
    s3_key = job.get('s3_key')

    if not s3_url:
        return None

    # Extract filename from s3_key
    filename = s3_key.split('/')[-1] if s3_key else 'video.mp4'

    return {
        's3_url': s3_url,
        's3_key': s3_key,
        'filename': filename
    }


def check_lambda_health():
    """
    Check if Lambda service is healthy and accessible.

    Returns:
        tuple: (is_healthy: bool, message: str)
    """
    try:
        client = get_lambda_client()
        function_name = get_lambda_function_name()

        # Try to get function configuration
        response = client.get_function(FunctionName=function_name)

        state = response.get('Configuration', {}).get('State', 'Unknown')
        if state == 'Active':
            return True, f"Lambda function '{function_name}' is active"
        else:
            return False, f"Lambda function state: {state}"

    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        if error_code == 'ResourceNotFoundException':
            return False, f"Lambda function not found"
        return False, f"AWS error: {str(e)}"
    except Exception as e:
        return False, f"Error: {str(e)}"
