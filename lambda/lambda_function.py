"""
AWS Lambda handler for video generation with optional social media posting.
Processes video generation requests asynchronously with progress updates via DynamoDB.
"""
import os
import json
import tempfile
import shutil
import time
import requests
from datetime import datetime, timezone
from decimal import Decimal

# Set FFmpeg path before importing moviepy (installed via Dockerfile to /usr/local/bin)
os.environ['IMAGEIO_FFMPEG_EXE'] = '/usr/local/bin/ffmpeg'

# Set temp directory for MoviePy (Lambda only allows writes to /tmp)
os.environ['TMPDIR'] = '/tmp'
os.environ['TEMP'] = '/tmp'
os.environ['TMP'] = '/tmp'

# Change working directory to /tmp (MoviePy writes temp files to cwd)
os.chdir('/tmp')

import boto3
from botocore.exceptions import ClientError

# Import video generator
from video_generator import generate_quiz_video


# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')
s3 = boto3.client('s3')

# Environment variables
DYNAMODB_TABLE = os.environ.get('DYNAMODB_TABLE', 'video_generation_jobs')
S3_BUCKET = os.environ.get('S3_BUCKET', 'maedix-q')


def get_table():
    """Get DynamoDB table resource"""
    return dynamodb.Table(DYNAMODB_TABLE)


def update_progress(task_id, status, percent, message, extra_data=None):
    """Update job progress in DynamoDB"""
    table = get_table()

    update_expr = 'SET #s = :status, progress_percent = :percent, progress_message = :message, updated_at = :updated'
    expr_values = {
        ':status': status,
        ':percent': Decimal(str(percent)),
        ':message': message,
        ':updated': datetime.now(timezone.utc).isoformat()
    }
    expr_names = {'#s': 'status'}

    if extra_data:
        for key, value in extra_data.items():
            update_expr += f', {key} = :{key}'
            if isinstance(value, float):
                expr_values[f':{key}'] = Decimal(str(value))
            else:
                expr_values[f':{key}'] = value

    try:
        table.update_item(
            Key={'task_id': task_id},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values
        )
    except ClientError as e:
        print(f"Error updating progress: {e}")


def create_job_record(task_id, event):
    """Create initial job record in DynamoDB"""
    table = get_table()

    now = datetime.now(timezone.utc)
    # TTL: 7 days from now
    ttl = int(now.timestamp()) + (7 * 24 * 60 * 60)

    # Check if social posting is requested
    social_posting = event.get('social_posting', {})

    item = {
        'task_id': task_id,
        'status': 'processing',
        'progress_percent': Decimal('0'),
        'progress_message': 'Initializing...',
        'user_id': event.get('user_id'),
        'quiz_id': event.get('quiz_id'),
        'quiz_slug': event.get('quiz_slug'),
        's3_output_key': event.get('s3_output_key'),
        'post_to_instagram': social_posting.get('post_to_instagram', False),
        'post_to_youtube': social_posting.get('post_to_youtube', False),
        'instagram_posted': False,
        'youtube_posted': False,
        'created_at': now.isoformat(),
        'updated_at': now.isoformat(),
        'ttl': ttl
    }

    try:
        table.put_item(Item=item)
    except ClientError as e:
        print(f"Error creating job record: {e}")
        raise


def upload_to_s3(file_path, s3_key):
    """Upload file to S3 and return public URL"""
    try:
        s3.upload_file(
            file_path,
            S3_BUCKET,
            s3_key,
            ExtraArgs={
                'ContentType': 'video/mp4',
                'CacheControl': 'max-age=31536000'  # 1 year cache
            }
        )

        # Generate URL (assumes bucket is configured for public access or CloudFront)
        s3_url = f"https://{S3_BUCKET}.s3.amazonaws.com/{s3_key}"
        return s3_url

    except ClientError as e:
        print(f"Error uploading to S3: {e}")
        raise


def post_to_instagram(s3_url, credentials, caption):
    """
    Post video to Instagram as a Reel.

    Args:
        s3_url: Public URL of the video
        credentials: Dict with 'access_token' and 'instagram_user_id'
        caption: Caption for the post

    Returns:
        dict with 'success' and optionally 'media_id' or 'error'
    """
    try:
        access_token = credentials['access_token']
        ig_user_id = credentials['instagram_user_id']

        print(f"Posting to Instagram user {ig_user_id}")

        # Step 1: Create media container for Reel
        container_response = requests.post(
            f"https://graph.instagram.com/v21.0/{ig_user_id}/media",
            data={
                "media_type": "REELS",
                "video_url": s3_url,
                "caption": caption,
                "access_token": access_token,
            },
            timeout=30,
        )
        container_data = container_response.json()

        if "id" not in container_data:
            error_msg = container_data.get("error", {}).get("message", "Failed to create media")
            print(f"Instagram container creation failed: {error_msg}")
            return {'success': False, 'error': error_msg}

        container_id = container_data["id"]
        print(f"Instagram container created: {container_id}")

        # Step 2: Wait for video processing to complete
        for attempt in range(30):
            status_response = requests.get(
                f"https://graph.instagram.com/{container_id}",
                params={
                    "fields": "status_code",
                    "access_token": access_token,
                },
                timeout=30,
            )
            status_data = status_response.json()
            status_code = status_data.get("status_code")

            if status_code == "FINISHED":
                break
            elif status_code == "ERROR":
                return {'success': False, 'error': 'Video processing failed'}

            time.sleep(10)
        else:
            return {'success': False, 'error': 'Video processing timed out'}

        # Step 3: Publish the media
        publish_response = requests.post(
            f"https://graph.instagram.com/v21.0/{ig_user_id}/media_publish",
            data={
                "creation_id": container_id,
                "access_token": access_token,
            },
            timeout=30,
        )
        publish_data = publish_response.json()

        if "id" not in publish_data:
            error_msg = publish_data.get("error", {}).get("message", "Failed to publish")
            return {'success': False, 'error': error_msg}

        media_id = publish_data["id"]
        print(f"Instagram post published: {media_id}")
        return {'success': True, 'media_id': media_id}

    except Exception as e:
        print(f"Instagram posting error: {e}")
        return {'success': False, 'error': str(e)}


def post_to_youtube(s3_url, credentials, title, description, tags=None):
    """
    Post video to YouTube as a Short.

    Args:
        s3_url: Public URL of the video
        credentials: Dict with 'access_token', 'refresh_token', 'client_id', 'client_secret'
        title: Video title
        description: Video description
        tags: Comma-separated string or list of tags

    Returns:
        dict with 'success' and optionally 'video_id' or 'error'
    """
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload

        print(f"Posting to YouTube: {title}")

        # Create credentials object
        creds = Credentials(
            token=credentials['access_token'],
            refresh_token=credentials['refresh_token'],
            token_uri='https://oauth2.googleapis.com/token',
            client_id=credentials['client_id'],
            client_secret=credentials['client_secret'],
        )

        # Build YouTube API client
        youtube = build('youtube', 'v3', credentials=creds)

        # Download video to temp file
        temp_video_path = '/tmp/youtube_upload.mp4'
        response = requests.get(s3_url, stream=True, timeout=120)
        response.raise_for_status()

        with open(temp_video_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        print(f"Video downloaded for YouTube upload: {os.path.getsize(temp_video_path)} bytes")

        try:
            # Add #Shorts to description for YouTube Shorts algorithm
            full_description = f"{description}\n\n#Shorts" if description else "#Shorts"

            # Parse tags - can be comma-separated string or list
            if tags:
                if isinstance(tags, str):
                    video_tags = [t.strip() for t in tags.split(',') if t.strip()]
                else:
                    video_tags = list(tags)
            else:
                video_tags = ['quiz', 'education', 'shorts']

            body = {
                'snippet': {
                    'title': title[:100],  # YouTube title limit
                    'description': full_description,
                    'tags': video_tags,
                    'categoryId': '27',  # Education
                },
                'status': {
                    'privacyStatus': 'public',
                    'selfDeclaredMadeForKids': False,
                },
            }

            media = MediaFileUpload(temp_video_path, mimetype='video/mp4', resumable=True)
            insert_request = youtube.videos().insert(
                part='snippet,status',
                body=body,
                media_body=media
            )

            response = None
            while response is None:
                status, response = insert_request.next_chunk()
                if status:
                    print(f"YouTube upload progress: {int(status.progress() * 100)}%")

            video_id = response.get('id')
            print(f"YouTube video uploaded: {video_id}")
            return {'success': True, 'video_id': video_id}

        finally:
            # Clean up temp file
            if os.path.exists(temp_video_path):
                os.unlink(temp_video_path)

    except Exception as e:
        print(f"YouTube posting error: {e}")
        return {'success': False, 'error': str(e)}


def handler(event, context):
    """
    Lambda handler for video generation with optional social media posting.

    Expected event payload:
    {
        "task_id": "uuid",
        "quiz_slug": "my-quiz",
        "quiz_title": "My Quiz",
        "questions": [...],
        "config": {...},
        "s3_output_key": "videos/uuid/quiz_reel.mp4",
        "user_id": 123,
        "quiz_id": 456,
        "social_posting": {
            "post_to_instagram": true,
            "post_to_youtube": false,
            "caption": "Check out this quiz!",
            "title": "Quiz Title",
            "description": "Quiz description",
            "instagram_credentials": {
                "access_token": "...",
                "instagram_user_id": "..."
            },
            "youtube_credentials": {
                "access_token": "...",
                "refresh_token": "...",
                "client_id": "...",
                "client_secret": "..."
            }
        }
    }
    """
    print(f"Received event: {json.dumps({k: v for k, v in event.items() if k != 'social_posting'})}")

    task_id = event.get('task_id')
    if not task_id:
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'task_id is required'})
        }

    questions = event.get('questions', [])
    if not questions:
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'questions are required'})
        }

    config = event.get('config', {})
    s3_output_key = event.get('s3_output_key', f'videos/{task_id}/video.mp4')
    social_posting = event.get('social_posting', {})
    quiz_title = event.get('quiz_title', 'Quiz')

    # Create temp directory for video output
    temp_dir = tempfile.mkdtemp()
    output_path = os.path.join(temp_dir, 'video.mp4')

    try:
        # Create initial job record
        create_job_record(task_id, event)

        # Progress callback for DynamoDB updates
        def progress_callback(percent, message):
            # Scale video generation to 0-85%
            scaled_percent = int(percent * 0.85)
            update_progress(task_id, 'processing', scaled_percent, message)

        # Start video generation
        update_progress(task_id, 'processing', 5, 'Starting video generation...')

        generate_quiz_video(
            questions=questions,
            output_path=output_path,
            progress_callback=progress_callback,
            show_answer=config.get('show_answer', True),
            handle_name=config.get('handle_name', '@maedix-q'),
            audio_url=config.get('audio_url'),
            audio_volume=config.get('audio_volume', 0.3),
            intro_text=config.get('intro_text'),
            intro_audio_url=config.get('intro_audio_url'),
            intro_audio_volume=config.get('intro_audio_volume', 0.5),
            pre_outro_text=config.get('pre_outro_text', 'Comment your answer!'),
            template_config=config.get('template_config'),
            quiz_heading=config.get('quiz_heading'),
            answer_reveal_audio_url=config.get('answer_reveal_audio_url'),
            answer_reveal_audio_volume=config.get('answer_reveal_audio_volume', 0.5)
        )

        # Upload to S3
        update_progress(task_id, 'processing', 88, 'Uploading to cloud...')
        s3_url = upload_to_s3(output_path, s3_output_key)
        print(f"Video uploaded to S3: {s3_url}")

        # Track social posting results
        social_results = {
            'instagram_posted': False,
            'youtube_posted': False,
            'instagram_error': None,
            'youtube_error': None,
        }

        # Post to Instagram if requested
        if social_posting.get('post_to_instagram') and social_posting.get('instagram_credentials'):
            update_progress(task_id, 'processing', 92, 'Posting to Instagram...')
            caption = social_posting.get('caption', f'{quiz_title}\n\n#quiz #education #shorts')
            ig_result = post_to_instagram(
                s3_url,
                social_posting['instagram_credentials'],
                caption
            )
            social_results['instagram_posted'] = ig_result['success']
            if not ig_result['success']:
                social_results['instagram_error'] = ig_result.get('error')
                print(f"Instagram posting failed: {ig_result.get('error')}")

        # Post to YouTube if requested
        if social_posting.get('post_to_youtube') and social_posting.get('youtube_credentials'):
            update_progress(task_id, 'processing', 96, 'Posting to YouTube...')
            title = social_posting.get('title', f'{quiz_title} - Quiz')
            description = social_posting.get('description', '')
            tags = social_posting.get('tags', '')
            yt_result = post_to_youtube(
                s3_url,
                social_posting['youtube_credentials'],
                title,
                description,
                tags
            )
            social_results['youtube_posted'] = yt_result['success']
            if not yt_result['success']:
                social_results['youtube_error'] = yt_result.get('error')
                print(f"YouTube posting failed: {yt_result.get('error')}")

        # Build completion message
        completion_message = 'Video ready!'
        if social_posting.get('post_to_instagram') or social_posting.get('post_to_youtube'):
            parts = []
            if social_results['instagram_posted']:
                parts.append('Instagram posted')
            elif social_posting.get('post_to_instagram'):
                parts.append('Instagram failed')
            if social_results['youtube_posted']:
                parts.append('YouTube posted')
            elif social_posting.get('post_to_youtube'):
                parts.append('YouTube failed')
            if parts:
                completion_message = f"Video ready! {', '.join(parts)}."

        # Mark as completed with social posting results
        update_progress(
            task_id,
            'completed',
            100,
            completion_message,
            extra_data={
                's3_url': s3_url,
                's3_key': s3_output_key,
                'instagram_posted': social_results['instagram_posted'],
                'youtube_posted': social_results['youtube_posted'],
                'instagram_error': social_results['instagram_error'],
                'youtube_error': social_results['youtube_error'],
            }
        )

        print(f"Video generation completed: {s3_url}")

        return {
            'statusCode': 200,
            'body': json.dumps({
                'task_id': task_id,
                's3_url': s3_url,
                'status': 'completed',
                'social_posting': social_results
            })
        }

    except Exception as e:
        error_message = str(e)
        print(f"Error generating video: {error_message}")

        # Update status to failed
        update_progress(
            task_id,
            'failed',
            0,
            f'Error: {error_message}'
        )

        return {
            'statusCode': 500,
            'body': json.dumps({
                'task_id': task_id,
                'error': error_message,
                'status': 'failed'
            })
        }

    finally:
        # Clean up temp directory
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass


# For local testing
if __name__ == '__main__':
    test_event = {
        'task_id': 'test-123',
        'quiz_slug': 'test-quiz',
        'quiz_title': 'Test Quiz',
        'questions': [
            {
                'text': 'What is the capital of France?',
                'options': [
                    {'text': 'London', 'is_correct': False},
                    {'text': 'Paris', 'is_correct': True},
                    {'text': 'Berlin', 'is_correct': False},
                    {'text': 'Madrid', 'is_correct': False}
                ]
            }
        ],
        'config': {
            'show_answer': True,
            'handle_name': '@test'
        },
        's3_output_key': 'videos/test-123/test.mp4',
        'user_id': 1,
        'quiz_id': 1
    }

    result = handler(test_event, None)
    print(json.dumps(result, indent=2))
