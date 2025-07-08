import http
import json
import os
import random
import threading
import time
import urllib
import uuid

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

# --- DynamoDB 및 환경 변수 설정 ---
dynamodb = boto3.resource("dynamodb")
users_table = dynamodb.Table(os.environ["USERS_TABLE_NAME"])
sessions_table = dynamodb.Table(os.environ["SESSIONS_TABLE_NAME"])
auth_logs_table = dynamodb.Table(os.environ["AUTH_LOGS_TABLE_NAME"])

MAX_RETRIES = 3
BASE_DELAY = 0.1
LOG_RETENTION_DAYS = int(os.environ["LOG_RETENTION_DAYS"])

ADMIN_KEY = os.environ["ADMIN_KEY"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

APP_VERSION = "2.1"


# --- 메인 핸들러 ---
def lambda_handler(event, context):
    method, path = event["routeKey"].split()
    body = json.loads(event.get("body", "{}"))
    ip = event.get("requestContext", {}).get("http", {}).get("sourceIp", "Unknown")

    # --- 관리자 기능 라우팅 ---
    if path.startswith("/admin/"):
        if ADMIN_KEY != body.get("adminKey"):
            return response(403, "Unauthorized: Invalid admin key")

        user_id = body.get("userId")  # 관리자 기능은 body에서 userId를 받음

        if method == "POST" and path == "/admin/users/create":
            return create_user(user_id)
        if method == "POST" and path == "/admin/users/list":
            return list_users()
        if method == "POST" and path == "/admin/users/delete":
            return delete_user(user_id)
        if method == "POST" and path == "/admin/users/reset":
            return reset_user(user_id)

    # --- 기존 클라이언트 앱 기능 라우팅 ---
    app_version = body.get("appVersion")
    if APP_VERSION != app_version:
        return response(400, "Update to the new version.")

    user_id = body.get("userId")
    if not user_id:
        return response(400, "Missing userId")

    if method == "POST" and path == "/authenticate":
        return authenticate(user_id, ip)
    elif method == "POST" and path == "/validate":
        return validate_session(user_id, body.get("sessionToken"), ip)
    elif method == "POST" and path == "/cleanup-logs":
        # adminKey는 body에 있어야 함
        if ADMIN_KEY != body.get("adminKey"):
            return response(403, "Unauthorized")
        return cleanup_old_logs()
    elif method == "POST" and path == "/clear-logs":
        if ADMIN_KEY != body.get("adminKey"):
            return response(403, "Unauthorized")
        return clear_logs()

    return response(404, "Not Found")


# --- 신규 관리자 기능 ---
def create_user(user_id):
    if not user_id:
        return response(400, "userId is required for creation")
    try:
        users_table.put_item(
            Item={"userId": user_id, "createdAt": int(time.time())},
            ConditionExpression="attribute_not_exists(userId)",
        )
        return response(200, f"User '{user_id}' created successfully.")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return response(409, f"User '{user_id}' already exists.")
        print(f"Error in create_user: {e}")
        return response(500, "Internal server error during user creation.")


def list_users():
    try:
        # 참고: scan은 큰 테이블에서는 비효율적일 수 있습니다.
        scan_response = users_table.scan(ProjectionExpression="userId")
        users = scan_response.get("Items", [])
        # 페이지네이션 처리
        while "LastEvaluatedKey" in scan_response:
            scan_response = users_table.scan(
                ProjectionExpression="userId",
                ExclusiveStartKey=scan_response["LastEvaluatedKey"],
            )
            users.extend(scan_response.get("Items", []))
        return response(200, "Users listed successfully", {"users": users})
    except Exception as e:
        print(f"Error in list_users: {e}")
        return response(500, "Internal server error while listing users.")


def delete_user(user_id):
    if not user_id:
        return response(400, "userId is required for deletion")
    try:
        users_table.delete_item(Key={"userId": user_id})
        return response(200, f"User '{user_id}' deleted successfully.")
    except Exception as e:
        print(f"Error in delete_user: {e}")
        return response(500, "Internal server error during user deletion.")


def reset_user(user_id):
    if not user_id:
        return response(400, "userId is required for reset")
    try:
        # 1. 세션 테이블에서 해당 사용자의 모든 세션 삭제
        session_query = sessions_table.query(
            KeyConditionExpression=Key("userId").eq(user_id)
        )
        with sessions_table.batch_writer() as batch:
            for item in session_query.get("Items", []):
                batch.delete_item(Key={"userId": item["userId"]})

        # 2. 사용자 테이블에서 lastLogin, lastIpAddress 제거(리셋)
        users_table.update_item(
            Key={"userId": user_id},
            UpdateExpression="REMOVE lastLogin, lastIpAddress",
            ConditionExpression="attribute_exists(userId)",
        )
        return response(200, f"User '{user_id}' has been reset successfully.")
    except ClientError as e:
        # 사용자가 존재하지 않을 때 발생하는 오류를 잡아서 404로 응답
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return response(404, f"User '{user_id}' not found.")
        print(f"Error in reset_user: {e}")
        return response(500, "Internal server error during user reset.")
    except Exception as e:
        print(f"Error in reset_user: {e}")
        return response(500, "Internal server error during user reset.")


# --- 기존 기능 (일부 수정 포함) ---
def authenticate(user_id, ip):
    # (내용 변경 없음, 원본과 동일)
    try:
        user = retry_operation(users_table.get_item, Key={"userId": user_id})
        if "Item" not in user:
            send_telegram_message(user_id, ip, "Authentication failed")
            return response(401, "Authentication failed")

        current_time = int(time.time())
        session_token = str(uuid.uuid4())

        retry_operation(
            sessions_table.put_item,
            Item={
                "userId": user_id,
                "sessionToken": session_token,
                "expirationTime": current_time + 720,
                "createdAt": current_time,
                "lastAccessedAt": current_time,
                "lastIpAddress": ip,
            },
        )
        retry_operation(
            users_table.update_item,
            Key={"userId": user_id},
            UpdateExpression="SET lastLogin = :time, lastIpAddress = :ip",
            ExpressionAttributeValues={":time": current_time, ":ip": ip},
        )
        log_auth_request(user_id, "authenticate", ip, "success")
        send_telegram_message(user_id, ip, "Authentication successful")
        return response(
            200, "Authentication successful", {"sessionToken": session_token}
        )
    except Exception as e:
        print(f"Error in authenticate: {str(e)}")
        log_auth_request(user_id, "authenticate", ip, "error")
        send_telegram_message(user_id, ip, f"Internal server error: {str(e)}")
        return response(500, "Internal server error")


def validate_session(user_id, session_token, ip):
    if not session_token:
        return response(400, "Missing sessionToken")
    try:
        # BUG FIX: get_item이 아닌 query를 사용해야 함
        session_response = retry_operation(
            sessions_table.query,
            KeyConditionExpression=Key("userId").eq(user_id)
            & Key("sessionToken").eq(session_token),
        )

        if not session_response.get("Items"):
            log_auth_request(user_id, "validate", ip, "invalid")
            send_telegram_message(user_id, ip, "Invalid session")
            return response(401, "Invalid session")

        session_item = session_response["Items"][0]
        current_time = int(time.time())

        if current_time > session_item["expirationTime"]:
            # 세션이 만료된 경우 isExpired 같은 플래그 대신 그냥 삭제하는 것이 더 깔끔할 수 있습니다.
            # 여기서는 원본 로직을 유지합니다.
            retry_operation(
                sessions_table.update_item,
                Key={"userId": user_id, "sessionToken": session_token},
                UpdateExpression="SET isExpired = :expired",
                ExpressionAttributeValues={":expired": True},
            )
            log_auth_request(user_id, "validate", ip, "expired")
            send_telegram_message(user_id, ip, "Session expired")
            return response(401, "Session expired")

        retry_operation(
            sessions_table.update_item,
            Key={"userId": user_id, "sessionToken": session_token},
            UpdateExpression="SET lastAccessedAt = :time, lastIpAddress = :ip, expirationTime = :new_expiration",
            ExpressionAttributeValues={
                ":time": current_time,
                ":ip": ip,
                ":new_expiration": current_time + 900,
            },
        )
        log_auth_request(user_id, "validate", ip, "success")
        return response(200, "Session is valid")
    except Exception as e:
        print(f"Error in validate_session: {str(e)}")
        send_telegram_message(user_id, ip, f"Internal server error: {str(e)}")
        return response(500, "Internal server error")


def clear_logs():
    try:
        # Clear logs from auth_logs_table
        scan_response = auth_logs_table.scan()

        with auth_logs_table.batch_writer() as batch:
            for item in scan_response["Items"]:
                batch.delete_item(
                    Key={
                        "userIdTimestamp": item["userIdTimestamp"],
                        "timestamp": item["timestamp"],
                    }
                )

        # Check if there are more items to process in auth_logs_table
        while "LastEvaluatedKey" in scan_response:
            scan_response = auth_logs_table.scan(
                ExclusiveStartKey=scan_response["LastEvaluatedKey"]
            )

            with auth_logs_table.batch_writer() as batch:
                for item in scan_response["Items"]:
                    batch.delete_item(
                        Key={
                            "userIdTimestamp": item["userIdTimestamp"],
                            "timestamp": item["timestamp"],
                        }
                    )

        # Clear logs from sessions_table
        scan_response = sessions_table.scan()

        with sessions_table.batch_writer() as batch:
            for item in scan_response["Items"]:
                batch.delete_item(
                    Key={"userId": item["userId"], "sessionToken": item["sessionToken"]}
                )

        # Check if there are more items to process in sessions_table
        while "LastEvaluatedKey" in scan_response:
            scan_response = sessions_table.scan(
                ExclusiveStartKey=scan_response["LastEvaluatedKey"]
            )

            with sessions_table.batch_writer() as batch:
                for item in scan_response["Items"]:
                    batch.delete_item(
                        Key={
                            "userId": item["userId"],
                            "sessionToken": item["sessionToken"],
                        }
                    )

        return response(200, "Logs cleared successfully")
    except Exception as e:
        print(f"Error in clear_logs: {str(e)}")
        return response(500, "Internal server error while clearing logs")


def retry_operation(operation, **kwargs):
    retries = 0
    while retries < MAX_RETRIES:
        try:
            return operation(**kwargs)
        except ClientError as e:
            if e.response["Error"]["Code"] == "ProvisionedThroughputExceededException":
                sleep_time = (2**retries * BASE_DELAY) + (random.random() * BASE_DELAY)
                time.sleep(sleep_time)
                retries += 1
            else:
                raise
    raise Exception("Max retries exceeded")


def log_auth_request(user_id, action, ip, status):
    current_time = int(time.time())
    expiration_time = current_time + (
        LOG_RETENTION_DAYS * 24 * 60 * 60
    )  # TTL in seconds

    # Create a composite key: userId#timestamp
    composite_key = f"{user_id}#{current_time}"

    log_item = {
        "userIdTimestamp": composite_key,  # Partition key
        "timestamp": current_time,  # Sort key
        "action": action,
        "status": status,
        "ip": ip,
    }

    retry_operation(auth_logs_table.put_item, Item=log_item)


def cleanup_old_logs():
    current_time = int(time.time())
    cutoff_time = current_time - (LOG_RETENTION_DAYS * 24 * 60 * 60)

    try:
        # Scan the table for old logs
        scan_response = auth_logs_table.scan(
            FilterExpression=Key("timestamp").lt(cutoff_time)
        )

        with auth_logs_table.batch_writer() as batch:
            for item in scan_response["Items"]:
                batch.delete_item(
                    Key={
                        "userIdTimestamp": item["userIdTimestamp"],
                        "timestamp": item["timestamp"],
                    }
                )

        # Check if there are more items to process
        while "LastEvaluatedKey" in scan_response:
            scan_response = auth_logs_table.scan(
                FilterExpression=Key("timestamp").lt(cutoff_time),
                ExclusiveStartKey=scan_response["LastEvaluatedKey"],
            )

            with auth_logs_table.batch_writer() as batch:
                for item in scan_response["Items"]:
                    batch.delete_item(
                        Key={
                            "userIdTimestamp": item["userIdTimestamp"],
                            "timestamp": item["timestamp"],
                        }
                    )

        return response(
            200, f"Logs older than {LOG_RETENTION_DAYS} days have been removed"
        )
    except Exception as e:
        print(f"Error in cleanup_old_logs: {str(e)}")
        return response(500, "Internal server error during log cleanup")


def response(status_code, message, additional_data=None):
    body = {"message": message}
    if additional_data:
        body.update(additional_data)
    return {"statusCode": status_code, "body": json.dumps(body)}


def send_telegram_message(user_id, ip, status):
    thread = threading.Thread(
        target=send_telegram_message_async, args=(user_id, ip, status)
    )
    thread.start()
    thread.join(timeout=2)


def send_telegram_message_async(user_id, ip, status):
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
