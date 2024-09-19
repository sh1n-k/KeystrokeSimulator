import http
import json
import os
import time
import urllib
import uuid
import boto3
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key
import random

dynamodb = boto3.resource('dynamodb')
users_table = dynamodb.Table(os.environ['USERS_TABLE_NAME'])
sessions_table = dynamodb.Table(os.environ['SESSIONS_TABLE_NAME'])
auth_logs_table = dynamodb.Table(os.environ['AUTH_LOGS_TABLE_NAME'])

MAX_RETRIES = 3
BASE_DELAY = 0.1
LOG_RETENTION_DAYS = int(os.environ['LOG_RETENTION_DAYS'])

ADMIN_KEY = os.environ['ADMIN_KEY']
BOT_TOKEN = os.environ['BOT_TOKEN']
CHAT_ID = os.environ['CHAT_ID']

def lambda_handler(event, context):
    method, path = event['routeKey'].split()
    body = json.loads(event.get('body', '{}'))
    ip = event.get('requestContext', {}).get('http', {}).get('sourceIp', 'Unknown')
    user_id = body.get('userId')

    if method == 'POST' and path == '/cleanup-logs':
        if ADMIN_KEY != body.get('adminKey'):
            return response(400, 'Unavailable request')
        return cleanup_old_logs()

    if not user_id:
        return response(400, 'Missing userId')

    if method == 'POST' and path == '/authenticate':
        return authenticate(user_id, ip)
    elif method == 'POST' and path == '/validate':
        return validate_session(user_id, body.get('sessionToken'), ip)
    else:
        return response(404, 'Not Found')

def authenticate(user_id, ip):
    try:
        user = retry_operation(users_table.get_item, Key={'userId': user_id})
        if 'Item' not in user:
            send_telegram_message(user_id, ip, 'Authentication failed')
            return response(401, 'Authentication failed')

        current_time = int(time.time())
        session_token = str(uuid.uuid4())

        # Create new session
        retry_operation(sessions_table.put_item, Item={
            'userId': user_id,
            'sessionToken': session_token,
            'expirationTime': current_time + 3600,
            'createdAt': current_time,
            'lastAccessedAt': current_time,
            'lastIpAddress': ip
        })

        # Update user's last login
        retry_operation(users_table.update_item,
                        Key={'userId': user_id},
                        UpdateExpression='SET lastLogin = :time, lastIpAddress = :ip',
                        ExpressionAttributeValues={':time': current_time, ':ip': ip}
                        )

        # Log authentication
        log_auth_request(user_id, 'authenticate', ip, 'success')
        send_telegram_message(user_id, ip, 'Authentication successful')

        return response(200, 'Authentication successful', {'sessionToken': session_token})
    except Exception as e:
        print(f"Error in authenticate: {str(e)}")
        log_auth_request(user_id, 'authenticate', ip, 'error')
        send_telegram_message(user_id, ip, f'Internal server error: {str(e)}')
        return response(500, 'Internal server error')

def validate_session(user_id, session_token, ip):
    if not session_token:
        return response(400, 'Missing sessionToken')

    try:
        session = retry_operation(sessions_table.get_item, Key={'userId': user_id})
        if 'Item' not in session or session_token != session['Item']['sessionToken']:
            log_auth_request(user_id, 'validate', ip, 'invalid')
            send_telegram_message(user_id, ip, 'Invalid session')
            return response(401, 'Invalid session')

        current_time = int(time.time())
        if current_time > session['Item']['expirationTime']:
            retry_operation(sessions_table.update_item,
                            Key={'userId': user_id},
                            UpdateExpression='SET isExpired = :expired',
                            ExpressionAttributeValues={':expired': True}
                            )
            log_auth_request(user_id, 'validate', ip, 'expired')
            send_telegram_message(user_id, ip, 'Session expired')
            return response(401, 'Session expired')

        # Update session
        retry_operation(sessions_table.update_item,
                        Key={'userId': user_id},
                        UpdateExpression='SET lastAccessedAt = :time, lastIpAddress = :ip',
                        ExpressionAttributeValues={':time': current_time, ':ip': ip}
                        )

        # Log validation
        log_auth_request(user_id, 'validate', ip, 'success')

        return response(200, 'Session is valid')
    except Exception as e:
        print(f"Error in validate_session: {str(e)}")
        send_telegram_message(user_id, ip, f'Internal server error: {str(e)}')
        return response(500, 'Internal server error')

def retry_operation(operation, **kwargs):
    retries = 0
    while retries < MAX_RETRIES:
        try:
            return operation(**kwargs)
        except ClientError as e:
            if e.response['Error']['Code'] == 'ProvisionedThroughputExceededException':
                sleep_time = (2 ** retries * BASE_DELAY) + (random.random() * BASE_DELAY)
                time.sleep(sleep_time)
                retries += 1
            else:
                raise
    raise Exception("Max retries exceeded")

def log_auth_request(user_id, action, ip, status):
    current_time = int(time.time())
    expiration_time = current_time + (LOG_RETENTION_DAYS * 24 * 60 * 60)  # TTL in seconds

    # Create a composite key: userId#timestamp
    composite_key = f"{user_id}#{current_time}"

    log_item = {
        'userIdTimestamp': composite_key,  # Partition key
        'timestamp': current_time,  # Sort key
        'action': action,
        'status': status,
        'ip': ip,
    }

    retry_operation(auth_logs_table.put_item, Item=log_item)

def cleanup_old_logs():
    current_time = int(time.time())
    cutoff_time = current_time - (LOG_RETENTION_DAYS * 24 * 60 * 60)

    try:
        # Scan the table for old logs
        scan_response = auth_logs_table.scan(
            FilterExpression=Key('timestamp').lt(cutoff_time)
        )

        with auth_logs_table.batch_writer() as batch:
            for item in scan_response['Items']:
                batch.delete_item(
                    Key={
                        'userIdTimestamp': item['userIdTimestamp'],
                        'timestamp': item['timestamp']
                    }
                )

        # Check if there are more items to process
        while 'LastEvaluatedKey' in scan_response:
            scan_response = auth_logs_table.scan(
                FilterExpression=Key('timestamp').lt(cutoff_time),
                ExclusiveStartKey=scan_response['LastEvaluatedKey']
            )

            with auth_logs_table.batch_writer() as batch:
                for item in scan_response['Items']:
                    batch.delete_item(
                        Key={
                            'userIdTimestamp': item['userIdTimestamp'],
                            'timestamp': item['timestamp']
                        }
                    )

        return response(200, f"Logs older than {LOG_RETENTION_DAYS} days have been removed")
    except Exception as e:
        print(f"Error in cleanup_old_logs: {str(e)}")
        return response(500, 'Internal server error during log cleanup')

def response(status_code, message, additional_data=None):
    body = {'message': message}
    if additional_data:
        body.update(additional_data)
    return {
        'statusCode': status_code,
        'body': json.dumps(body)
    }

def send_telegram_message(user_id, ip, status):
    try:
        message = f"User ID: {user_id}\nIP: {ip}\nStatus: {status}"
        encoded_message = urllib.parse.quote(message)

        url = f"api.telegram.org"
        path = f"/bot{BOT_TOKEN}/sendMessage?chat_id={CHAT_ID}&text={encoded_message}"

        conn = http.client.HTTPSConnection(url)
        conn.request("GET", path)
        telegram_response = conn.getresponse()
        telegram_response.read()
        conn.close()
    except Exception as e:
        print(f"Error sending message to Telegram: {str(e)}")