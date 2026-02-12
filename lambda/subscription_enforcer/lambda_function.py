"""
AWS Lambda handler for enforcing subscription expiry.

Runs once a day via CloudWatch EventBridge — rate(1 day).
Connects to PostgreSQL to find expired subscriptions, switches users
to the free plan, and deactivates excess flows.
"""
import os
import json

import psycopg2
import psycopg2.extras


def get_config():
    """Parse CONFIG environment variable."""
    config_str = os.environ.get('CONFIG', '{}')
    return json.loads(config_str)


def get_db_connection(config):
    """Create a read-write PostgreSQL connection."""
    print(f"Connecting to DB at {config['db_host']}:{config.get('db_port', 5432)}/{config['db_name']}")
    conn = psycopg2.connect(
        host=config['db_host'],
        dbname=config['db_name'],
        user=config['db_user'],
        password=config['db_password'],
        port=config.get('db_port', 5432),
    )
    conn.autocommit = False
    print("DB connection established (read-write)")
    return conn


def get_free_plan(cursor):
    """Get the free plan's ID and ig_flow_builder limit."""
    cursor.execute("""
        SELECT id, features FROM core_plan
        WHERE plan_type = 'free' AND is_active = true
        LIMIT 1
    """)
    row = cursor.fetchone()
    if not row:
        raise RuntimeError("No active free plan found")

    plan_id = row['id']
    features = row['features']

    # Parse ig_flow_builder limit from features
    flow_limit = 1  # default
    if isinstance(features, str):
        features = json.loads(features)
    if isinstance(features, list):
        for feature in features:
            if feature.get('code') == 'ig_flow_builder' and feature.get('limit') is not None:
                flow_limit = int(feature['limit'])
                break

    print(f"Free plan: id={plan_id}, ig_flow_builder limit={flow_limit}")
    return plan_id, flow_limit


def find_expired_subscriptions(cursor):
    """Find active subscriptions past their end_date."""
    cursor.execute("""
        SELECT id, user_id, plan_id
        FROM core_subscription
        WHERE status = 'active'
          AND end_date IS NOT NULL
          AND end_date < NOW()
    """)
    rows = cursor.fetchall()
    print(f"Found {len(rows)} expired subscription(s)")
    return rows


def switch_to_free_plan(cursor, subscription_id, free_plan_id):
    """Switch subscription to free plan, clear end_date."""
    cursor.execute("""
        UPDATE core_subscription
        SET plan_id = %s, status = 'active', end_date = NULL,
            usage_data = '{}', updated_at = NOW()
        WHERE id = %s
    """, (free_plan_id, subscription_id))


def deactivate_excess_flows(cursor, user_id, free_limit):
    """
    If user has more active flows than free_limit, deactivate excess.
    Keeps the oldest N flows (by created_at) active.
    Returns the number of flows deactivated.
    """
    # Count active flows
    cursor.execute("""
        SELECT COUNT(*) FROM instagram_dmflow
        WHERE user_id = %s AND is_active = true
    """, (user_id,))
    active_count = cursor.fetchone()[0]

    if active_count <= free_limit:
        return 0

    excess = active_count - free_limit

    # Get IDs of excess flows (newest first — keep oldest active)
    cursor.execute("""
        SELECT id FROM instagram_dmflow
        WHERE user_id = %s AND is_active = true
        ORDER BY created_at ASC
        OFFSET %s
    """, (user_id, free_limit))
    excess_ids = [row[0] for row in cursor.fetchall()]

    if not excess_ids:
        return 0

    cursor.execute("""
        UPDATE instagram_dmflow
        SET is_active = false, deactivated_by = 'system', updated_at = NOW()
        WHERE id = ANY(%s)
    """, (excess_ids,))

    print(f"  Deactivated {len(excess_ids)} excess flow(s) for user {user_id}: {excess_ids}")
    return len(excess_ids)


def handler(event, context):
    """
    Lambda handler — scheduled via CloudWatch EventBridge rate(1 day).

    1. Get free plan ID and flow limit
    2. Find expired subscriptions
    3. For each: switch to free plan + deactivate excess flows
    4. COMMIT per user
    """
    print("=" * 60)
    print("Subscription enforcer started")
    print(f"Event: {json.dumps(event, default=str)}")

    config = get_config()

    summary = {
        'expired_count': 0,
        'flows_deactivated': 0,
        'users': [],
        'errors': [],
    }

    conn = None
    try:
        conn = get_db_connection(config)
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        free_plan_id, free_limit = get_free_plan(cursor)

        expired_subs = find_expired_subscriptions(cursor)

        if not expired_subs:
            print("No expired subscriptions. Exiting.")
            return {
                'statusCode': 200,
                'body': json.dumps({'message': 'No expired subscriptions', 'summary': summary}),
            }

        for sub in expired_subs:
            sub_id = sub['id']
            user_id = sub['user_id']
            old_plan_id = sub['plan_id']

            print(f"\n--- Subscription {sub_id} (user={user_id}, old_plan={old_plan_id}) ---")

            try:
                switch_to_free_plan(cursor, sub_id, free_plan_id)
                deactivated = deactivate_excess_flows(cursor, user_id, free_limit)
                conn.commit()

                summary['expired_count'] += 1
                summary['flows_deactivated'] += deactivated
                summary['users'].append({
                    'user_id': user_id,
                    'subscription_id': sub_id,
                    'old_plan_id': old_plan_id,
                    'flows_deactivated': deactivated,
                })
                print(f"  Committed: switched to free plan, deactivated {deactivated} flow(s)")

            except Exception as e:
                conn.rollback()
                error_msg = f"Error processing subscription {sub_id} (user {user_id}): {e}"
                print(f"  {error_msg}")
                summary['errors'].append(error_msg)

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
    print(f"Subscription enforcer finished: expired={summary['expired_count']}, flows_deactivated={summary['flows_deactivated']}, errors={len(summary['errors'])}")
    print(f"{'=' * 60}")

    return {
        'statusCode': 200,
        'body': json.dumps({'summary': summary}),
    }
