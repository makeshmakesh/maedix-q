# Video Generation Lambda - Deployment Guide

This guide covers deploying the video generation Lambda function using Docker containers.

## Architecture Overview

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐     ┌─────────────┐
│   Django    │────▶│    Lambda    │────▶│     S3      │────▶│  DynamoDB   │
│   Server    │     │  (Video Gen) │     │  (Videos)   │     │  (Progress) │
└─────────────┘     └──────────────┘     └─────────────┘     └─────────────┘
       │                    │                                       │
       │                    │    Progress updates                   │
       │                    └───────────────────────────────────────┘
       │
       └──────────── Polls DynamoDB for progress ──────────────────┘
```

## Prerequisites

1. **AWS CLI** configured with appropriate credentials
2. **AWS SAM CLI** installed (`pip install aws-sam-cli`)
3. **Docker** installed and running (for building container image)
4. **S3 bucket** for video storage (create if not exists)

## Quick Start

```bash
# 1. Navigate to aws directory
cd /home/makesh/personal/main/maedix-q/aws

# 2. Build SAM application (builds Docker image)
sam build

# 3. Deploy (first time - guided)
sam deploy --guided

# 4. Deploy (subsequent times)
sam deploy
```

## Detailed Deployment Steps

### Step 1: Build SAM Application

```bash
cd /home/makesh/personal/main/maedix-q/aws
sam build
```

This builds a Docker container image containing:
- Python 3.12 runtime
- FFmpeg static binary
- DejaVu fonts
- Python dependencies (moviepy, pillow, numpy, boto3)
- Video generator code

### Step 2: Deploy to AWS

**First-time deployment (guided):**
```bash
sam deploy --guided
```

You'll be prompted for:
- Stack name: `maedix-video-gen`
- AWS Region: `us-east-1`
- Parameter values (Environment, S3BucketName, DynamoDBTableName)
- Confirm changeset deployment
- Allow SAM to create ECR repository

**Subsequent deployments:**
```bash
sam deploy
```

### Step 3: Configure Django

Add these configuration keys in Django Admin (Core > Configuration):

| Key | Value | Description |
|-----|-------|-------------|
| `use_lambda_video_gen` | `true` | Enable Lambda video generation |
| `lambda_video_function` | `maedix-video-generator-production` | Lambda function name |
| `dynamodb_video_jobs_table` | `video_generation_jobs` | DynamoDB table name |
| `video_s3_bucket` | `maedix-q` | S3 bucket for videos |

### Step 4: Configure IAM for Django Server

The Django server needs permissions to invoke Lambda and read from DynamoDB.

Add this IAM policy to your Django server's IAM user/role:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "lambda:InvokeFunction"
            ],
            "Resource": "arn:aws:lambda:us-east-1:*:function:maedix-video-generator-*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "dynamodb:GetItem",
                "dynamodb:Query"
            ],
            "Resource": "arn:aws:dynamodb:us-east-1:*:table/video_generation_jobs*"
        }
    ]
}
```

## Testing

### Test Lambda in AWS

```bash
aws lambda invoke \
    --function-name maedix-video-generator-production \
    --invocation-type Event \
    --payload file://test-event.json \
    response.json
```

### Verify DynamoDB Table

```bash
aws dynamodb scan --table-name video_generation_jobs --max-items 5
```

## Configuration Reference

### Lambda Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ENVIRONMENT` | `production` | Deployment environment |
| `S3_BUCKET` | `maedix-q` | S3 bucket for video output |
| `DYNAMODB_TABLE` | `video_generation_jobs` | DynamoDB table for job tracking |

### Lambda Configuration

| Setting | Value | Rationale |
|---------|-------|-----------|
| Memory | 3008 MB | MoviePy + FFmpeg needs ~2-3GB |
| Timeout | 600 seconds | Videos take 2-5 min + buffer |
| Ephemeral Storage | 1024 MB | Video output + temp files |
| Runtime | Python 3.12 (Container) | Latest stable |

### DynamoDB Table Schema

| Attribute | Type | Description |
|-----------|------|-------------|
| `task_id` | String (PK) | UUID |
| `status` | String | pending/processing/completed/failed |
| `progress_percent` | Number | 0-100 |
| `progress_message` | String | Current step description |
| `s3_url` | String | Final video URL |
| `user_id` | Number | Django user ID |
| `quiz_id` | Number | Quiz ID |
| `created_at` | String | ISO timestamp |
| `updated_at` | String | ISO timestamp |
| `ttl` | Number | Auto-delete after 7 days |

## Monitoring

### CloudWatch Logs

View Lambda logs:
```bash
sam logs -n VideoGeneratorFunction --stack-name maedix-video-gen --tail
```

### CloudWatch Metrics

Key metrics to monitor:
- `Invocations` - Number of video generation requests
- `Duration` - Time taken per video
- `Errors` - Failed generations
- `ConcurrentExecutions` - Concurrent video generations

## Cost Estimation

| Component | Estimated Cost |
|-----------|---------------|
| Lambda (3GB, 5min avg) | ~$0.015 per video |
| DynamoDB (on-demand) | ~$0.001 per video |
| S3 (storage + transfer) | ~$0.001 per video |
| **Total** | **~$0.017 per video** |

For 500 videos/month: ~$8.50/month

## Troubleshooting

### Lambda Timeout
- Check video duration (max ~3 min video recommended)
- Consider reducing video quality settings

### Out of Memory
- Increase Lambda memory (up to 10GB available)
- Check for memory leaks in video processing

### S3 Upload Failed
- Verify S3 bucket exists and permissions
- Check bucket policy for public access

### DynamoDB Errors
- Verify table exists
- Check IAM permissions

### Docker Build Issues
- Ensure Docker daemon is running
- Check available disk space
- Run `docker system prune` to clean up unused images

## Development Environment

Deploy to development:
```bash
sam deploy --config-env dev
```

Deploy to staging:
```bash
sam deploy --config-env staging
```
