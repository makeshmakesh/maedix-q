# Queue Processor Lambda

Processes queued flow triggers every 5 minutes. Connects to PostgreSQL to find pending triggers, checks rate limits, and calls the Django internal API to process eligible triggers.

## Deploy (first time)

### 1. Create ECR repo (one-time)

```bash
aws ecr create-repository --repository-name maedix-queue-processor --region us-east-1
```

### 2. Build & push the Docker image

```bash
# Login to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 061051221530.dkr.ecr.us-east-1.amazonaws.com

# Build
cd lambda/queue_processor
docker build -t maedix-queue-processor .

# Tag & push
docker tag maedix-queue-processor:latest 061051221530.dkr.ecr.us-east-1.amazonaws.com/maedix-queue-processor:latest
docker push 061051221530.dkr.ecr.us-east-1.amazonaws.com/maedix-queue-processor:latest
```

### 3. Create the Lambda function

```bash
aws lambda create-function \
  --function-name maedix-queue-processor \
  --package-type Image \
  --code ImageUri=061051221530.dkr.ecr.us-east-1.amazonaws.com/maedix-queue-processor:latest \
  --role arn:aws:iam::061051221530:role/maedix-video-gen-VideoGeneratorFunctionRole-oytOGubbP7jb \
  --timeout 120 \
  --memory-size 256 \
  --environment 'Variables={CONFIG="{\"db_host\":\"...\",\"db_name\":\"...\",\"db_user\":\"...\",\"db_password\":\"...\",\"db_port\":5432,\"app_url\":\"https://maedix.com\",\"INTERNAL_API_KEY\":\"...\"}"}' \
  --region us-east-1
```

### 4. Add the 5-minute schedule (EventBridge)

```bash
# Create rule
aws events put-rule \
  --name maedix-queue-processor-schedule \
  --schedule-expression "rate(5 minutes)" \
  --region us-east-1

# Grant EventBridge permission to invoke Lambda
aws lambda add-permission \
  --function-name maedix-queue-processor \
  --statement-id eventbridge-invoke \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn arn:aws:events:us-east-1:061051221530:rule/maedix-queue-processor-schedule

# Add Lambda as target
aws events put-targets \
  --rule maedix-queue-processor-schedule \
  --targets "Id"="1","Arn"="arn:aws:lambda:us-east-1:061051221530:function:maedix-queue-processor"
```

### 5. Set INTERNAL_API_KEY in Django

Add the key to your `core_configuration` table (same value as in the Lambda CONFIG):

```sql
INSERT INTO core_configuration (key, value, created_at, updated_at)
VALUES ('INTERNAL_API_KEY', 'your-secret-key-here', NOW(), NOW());
```

## Update after code changes

```bash
cd lambda/queue_processor
docker build -t maedix-queue-processor .
docker tag maedix-queue-processor:latest 061051221530.dkr.ecr.us-east-1.amazonaws.com/maedix-queue-processor:latest
docker push 061051221530.dkr.ecr.us-east-1.amazonaws.com/maedix-queue-processor:latest
aws lambda update-function-code \
  --function-name maedix-queue-processor \
  --image-uri 061051221530.dkr.ecr.us-east-1.amazonaws.com/maedix-queue-processor:latest
```

## Test manually

```bash
aws lambda invoke \
  --function-name maedix-queue-processor \
  --payload '{}' \
  --cli-binary-format raw-in-base64-out \
  output.json && cat output.json
```

## Note

The Lambda needs network access to both your PostgreSQL DB and your Django app (maedix.com). If your DB is in a VPC, you'll need to put the Lambda in the same VPC and add a NAT gateway for outbound internet access to reach the Django endpoint.
