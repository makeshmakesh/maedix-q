# Subscription Enforcer Lambda

Runs once a day to expire stale subscriptions. Finds active subscriptions past their `end_date`, switches users to the free plan, and deactivates excess flows (marked `deactivated_by='system'` so they auto-reactivate on upgrade).

## Deploy (first time)

### 1. Create ECR repo (one-time)

```bash
aws ecr create-repository --repository-name maedix-subscription-enforcer --region us-east-1
```

### 2. Build & push the Docker image

```bash
# Login to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 061051221530.dkr.ecr.us-east-1.amazonaws.com

# Build
cd lambda/subscription_enforcer
docker build -t maedix-subscription-enforcer .

# Tag & push
docker tag maedix-subscription-enforcer:latest 061051221530.dkr.ecr.us-east-1.amazonaws.com/maedix-subscription-enforcer:latest
docker push 061051221530.dkr.ecr.us-east-1.amazonaws.com/maedix-subscription-enforcer:latest
```

### 3. Create the Lambda function

```bash
aws lambda create-function \
  --function-name maedix-subscription-enforcer \
  --package-type Image \
  --code ImageUri=061051221530.dkr.ecr.us-east-1.amazonaws.com/maedix-subscription-enforcer:latest \
  --role arn:aws:iam::061051221530:role/maedix-video-gen-VideoGeneratorFunctionRole-oytOGubbP7jb \
  --timeout 120 \
  --memory-size 256 \
  --environment 'Variables={CONFIG="{\"db_host\":\"...\",\"db_name\":\"...\",\"db_user\":\"...\",\"db_password\":\"...\",\"db_port\":5432}"}' \
  --region us-east-1
```

### 4. Add the daily schedule (EventBridge)

```bash
# Create rule
aws events put-rule \
  --name maedix-subscription-enforcer-schedule \
  --schedule-expression "rate(1 day)" \
  --region us-east-1

# Grant EventBridge permission to invoke Lambda
aws lambda add-permission \
  --function-name maedix-subscription-enforcer \
  --statement-id eventbridge-invoke \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn arn:aws:events:us-east-1:061051221530:rule/maedix-subscription-enforcer-schedule

# Add Lambda as target
aws events put-targets \
  --rule maedix-subscription-enforcer-schedule \
  --targets "Id"="1","Arn"="arn:aws:lambda:us-east-1:061051221530:function:maedix-subscription-enforcer"
```

## Update after code changes

```bash
cd lambda/subscription_enforcer
docker build -t maedix-subscription-enforcer .
docker tag maedix-subscription-enforcer:latest 061051221530.dkr.ecr.us-east-1.amazonaws.com/maedix-subscription-enforcer:latest
docker push 061051221530.dkr.ecr.us-east-1.amazonaws.com/maedix-subscription-enforcer:latest
aws lambda update-function-code \
  --function-name maedix-subscription-enforcer \
  --image-uri 061051221530.dkr.ecr.us-east-1.amazonaws.com/maedix-subscription-enforcer:latest
```

## Test manually

```bash
aws lambda invoke \
  --function-name maedix-subscription-enforcer \
  --payload '{}' \
  --cli-binary-format raw-in-base64-out \
  output.json && cat output.json
```

## Note

The Lambda needs network access to your PostgreSQL DB. If your DB is in a VPC, put the Lambda in the same VPC. No outbound internet access needed (no HTTP calls, DB-only).
