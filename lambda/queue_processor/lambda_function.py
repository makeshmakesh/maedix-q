"""
AWS Lambda handler for processing queued flow triggers.

Runs on a schedule (every 5 minutes via CloudWatch EventBridge).
Connects to PostgreSQL to find pending triggers, checks rate limits,
and calls the Django internal API to process eligible triggers.
"""
import os
import json

import psycopg2
import psycopg2.extras
import requests


def get_config():
    """Parse CONFIG environment variable."""
    config_str = os.environ.get('CONFIG', '{}')
    return json.loads(config_str)


def get_db_connection(config):
    """Create a read-only PostgreSQL connection."""
    print(f"Connecting to DB at {config['db_host']}:{config.get('db_port', 5432)}/{config['db_name']}")
    conn = psycopg2.connect(
        host=config['db_host'],
        dbname=config['db_name'],
        user=config['db_user'],
        password=config['db_password'],
        port=config.get('db_port', 5432),
        options='-c default_transaction_read_only=on',
    )
    print("DB connection established")
    return conn


def fetch_pending_triggers(cursor):
    """Fetch pending QueuedFlowTrigger records from last 24 hours."""
    print("Querying pending triggers from last 24 hours...")
    cursor.execute("""
        SELECT qt.id, qt.account_id, qt.flow_id, qt.created_at
        FROM instagram_queuedflowtrigger qt
        WHERE qt.status = 'pending'
          AND qt.created_at >= NOW() - INTERVAL '24 hours'
        ORDER BY qt.created_at ASC
    """)
    rows = cursor.fetchall()
    print(f"Found {len(rows)} pending triggers")
    return rows


def get_calls_last_hour(cursor, account_id):
    """Count successful API calls in the last hour for an account."""
    cursor.execute("""
        SELECT COUNT(*) FROM instagram_apicalllog
        WHERE account_id = %s
          AND sent_at >= NOW() - INTERVAL '1 hour'
          AND success = true
    """, (account_id,))
    count = cursor.fetchone()[0]
    print(f"  Account {account_id}: {count} API calls in last hour")
    return count


def get_rate_limit(cursor, account_id):
    """
    Get rate limit for an account.
    Checks subscription plan first, falls back to global config.
    """
    # Check subscription plan for ig_rate_limit
    cursor.execute("""
        SELECT p.features FROM core_plan p
        JOIN core_subscription s ON s.plan_id = p.id
        JOIN instagram_instagramaccount ia ON ia.user_id = s.user_id
        WHERE ia.id = %s AND s.status = 'active' AND s.end_date > NOW()
    """, (account_id,))
    row = cursor.fetchone()
    if row and row[0]:
        features = row[0]
        if isinstance(features, str):
            features = json.loads(features)
        # features is a list of dicts like [{"code": "ig_rate_limit", "limit": 500}, ...]
        if isinstance(features, list):
            for feature in features:
                if feature.get('code') == 'ig_rate_limit' and feature.get('limit'):
                    limit = int(feature['limit'])
                    print(f"  Account {account_id}: rate limit {limit} (from subscription plan)")
                    return limit
        elif isinstance(features, dict) and features.get('ig_rate_limit'):
            limit = int(features['ig_rate_limit'])
            print(f"  Account {account_id}: rate limit {limit} (from subscription plan dict)")
            return limit

    # Fallback: global config
    cursor.execute("""
        SELECT value FROM core_configuration WHERE key = 'INSTAGRAM_RATE_LIMIT'
    """)
    row = cursor.fetchone()
    if row:
        try:
            limit = int(row[0])
            print(f"  Account {account_id}: rate limit {limit} (from global config)")
            return limit
        except (ValueError, TypeError):
            pass

    print(f"  Account {account_id}: rate limit 200 (default)")
    return 200


def process_trigger(app_url, api_key, trigger_id):
    """Call Django internal API to process a single trigger."""
    url = f"{app_url}/instagram/api/internal/process-trigger/{trigger_id}/"
    print(f"  POST {url}")
    try:
        response = requests.post(
            url,
            headers={'X-Internal-API-Key': api_key},
            timeout=60,
        )
        body = response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text
        print(f"  Response {response.status_code}: {body}")
        return {
            'trigger_id': trigger_id,
            'status_code': response.status_code,
            'response': body,
            'success': response.status_code == 200,
        }
    except requests.RequestException as e:
        print(f"  HTTP error processing trigger {trigger_id}: {e}")
        return {
            'trigger_id': trigger_id,
            'success': False,
            'error': str(e),
        }


def handler(event, context):
    """
    Lambda handler — scheduled via CloudWatch EventBridge.

    1. Fetch pending triggers from PostgreSQL
    2. Calculate rate limit budget per account
    3. Call Django endpoint for eligible triggers
    4. Return summary
    """
    print("=" * 60)
    print("Queue processor started")
    print(f"Event: {json.dumps(event, default=str)}")

    config = get_config()
    app_url = config.get('app_url', '').rstrip('/')
    api_key = config.get('INTERNAL_API_KEY', '')

    print(f"App URL: {app_url}")
    print(f"API key configured: {'yes' if api_key else 'NO'}")

    if not app_url or not api_key:
        print("ERROR: Missing app_url or INTERNAL_API_KEY in CONFIG")
        return {'statusCode': 200, 'body': json.dumps({'error': 'Missing configuration'})}

    summary = {
        'processed': 0,
        'skipped': 0,
        'failed': 0,
        'accounts': {},
    }

    conn = None
    try:
        conn = get_db_connection(config)
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Fetch all pending triggers
        triggers = fetch_pending_triggers(cursor)

        if not triggers:
            print("No pending triggers found. Exiting.")
            return {
                'statusCode': 200,
                'body': json.dumps({'message': 'No pending triggers', 'summary': summary}),
            }

        # Group by account_id
        accounts = {}
        for row in triggers[0:5]:
            account_id = row['account_id']
            if account_id not in accounts:
                accounts[account_id] = []
            accounts[account_id].append({
                'id': row['id'],
                'flow_id': row['flow_id'],
                'created_at': str(row['created_at']),
            })

        print(f"Grouped into {len(accounts)} accounts")

        # Process each account
        for account_id, account_triggers in accounts.items():
            print(f"\n--- Account {account_id} ({len(account_triggers)} pending) ---")

            calls_last_hour = get_calls_last_hour(cursor, account_id)
            rate_limit = get_rate_limit(cursor, account_id)
            safety_buffer = 50
            available = rate_limit - calls_last_hour - safety_buffer
            max_triggers = max(0, available // 10)

            print(f"  Budget: limit={rate_limit}, used={calls_last_hour}, available={available}, max_triggers={max_triggers}")

            account_summary = {
                'rate_limit': rate_limit,
                'calls_last_hour': calls_last_hour,
                'available': available,
                'max_triggers': max_triggers,
                'total_pending': len(account_triggers),
                'results': [],
            }

            if max_triggers <= 0:
                summary['skipped'] += len(account_triggers)
                account_summary['skipped'] = len(account_triggers)
                print(f"  SKIPPED all {len(account_triggers)} triggers (no budget)")
            else:
                eligible = account_triggers[:max_triggers]
                skipped_count = len(account_triggers) - len(eligible)
                summary['skipped'] += skipped_count
                account_summary['skipped'] = skipped_count

                print(f"  Processing {len(eligible)} triggers (skipping {skipped_count})")

                for i, trigger in enumerate(eligible):
                    # Check remaining time — stop if less than 30s left
                    remaining_ms = context.get_remaining_time_in_millis() if context else 999999
                    if remaining_ms < 30000:
                        remaining_skipped = len(eligible) - i
                        summary['skipped'] += remaining_skipped
                        print(f"  TIMEOUT APPROACHING ({remaining_ms}ms left) — skipping remaining {remaining_skipped} triggers")
                        break

                    print(f"  [{i+1}/{len(eligible)}] Trigger {trigger['id']} (flow={trigger['flow_id']}, created={trigger['created_at']})")
                    result = process_trigger(app_url, api_key, trigger['id'])
                    account_summary['results'].append(result)
                    if result['success']:
                        summary['processed'] += 1
                        print(f"  [{i+1}/{len(eligible)}] SUCCESS")
                    else:
                        summary['failed'] += 1
                        print(f"  [{i+1}/{len(eligible)}] FAILED: {result.get('error', result.get('response', 'unknown'))}")

            summary['accounts'][str(account_id)] = account_summary

    except psycopg2.Error as e:
        print(f"DATABASE ERROR: {e}")
        return {
            'statusCode': 200,
            'body': json.dumps({'error': f'Database error: {str(e)}'}),
        }
    except Exception as e:
        print(f"UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 200,
            'body': json.dumps({'error': str(e)}),
        }
    finally:
        if conn:
            conn.close()
            print("DB connection closed")

    print(f"\n{'=' * 60}")
    print(f"Queue processor finished: processed={summary['processed']}, skipped={summary['skipped']}, failed={summary['failed']}")
    print(f"{'=' * 60}")

    return {
        'statusCode': 200,
        'body': json.dumps({'summary': summary}),
    }
