# /function/storage/terem-files

import base64
import json
import logging
import mimetypes
import os
import re
import time
from email.message import EmailMessage
from html import escape

import boto3
from botocore.config import Config


CORS_ALLOWED_ORIGIN = os.getenv("CORS_ALLOWED_ORIGIN", "*")
CORS_ALLOWED_METHODS = os.getenv("CORS_ALLOWED_METHODS", "POST, OPTIONS")
CORS_ALLOWED_HEADERS = os.getenv(
    "CORS_ALLOWED_HEADERS",
    "Content-Type, Authorization, X-Request-Id",
)

STORAGE_ROOT = os.getenv("TEREM_FILES_STORAGE_ROOT", "/function/storage/terem-files")

EMAIL_FROM = os.getenv("L4_EMAIL_FROM_L4DESK", "") or os.getenv("L4_EMAIL_FROM", "")
EMAIL_FROM_PL = os.getenv("L4_EMAIL_FROM_PLATERRA", "")
EMAIL_POSTBOX_ENDPOINT_URL = os.getenv(
    "L4_EMAIL_POSTBOX_ENDPOINT_URL",
    "https://postbox.cloud.yandex.net",
)
EMAIL_POSTBOX_REGION = os.getenv("L4_EMAIL_POSTBOX_REGION", "ru-central1")

ACCESS_KEY_ID = os.getenv("ACCESS_KEY_ID", "")
SECRET_ACCESS_KEY = os.getenv("SECRET_ACCESS_KEY", "")

MAX_FILE_BYTES = int(os.getenv("SEND_EMAIL_MAX_FILE_BYTES", str(10 * 1024 * 1024)))

SAFE_SEGMENT_RE = re.compile(r"[^A-Za-z0-9._-]+")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

logger = logging.getLogger(__name__)


def cors_headers():
    return {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": CORS_ALLOWED_ORIGIN,
        "Access-Control-Allow-Methods": CORS_ALLOWED_METHODS,
        "Access-Control-Allow-Headers": CORS_ALLOWED_HEADERS,
    }


def json_response(body, status_code=200):
    return {
        "statusCode": status_code,
        "headers": cors_headers(),
        "body": json.dumps(body, ensure_ascii=False),
    }


def error_response(status_code, error_code, message):
    return json_response(
        {
            "error_code": error_code,
            "message": message,
        },
        status_code,
    )


def preflight_response():
    headers = cors_headers()
    headers["Access-Control-Max-Age"] = "86400"
    return {
        "statusCode": 200,
        "headers": headers,
        "body": "",
    }


def get_http_method(event):
    method = event.get("httpMethod")
    if method:
        return method.upper()

    request_context = event.get("requestContext") or {}
    http_context = request_context.get("http") or {}
    method = http_context.get("method")

    return method.upper() if method else None


def get_path_param(event, name):
    # Yandex API Gateway variants + AWS-compatible variants.
    for container_name in ("pathParams", "pathParameters"):
        container = event.get(container_name) or {}
        value = container.get(name)
        if value:
            return str(value).strip()

    params = event.get("params") or {}
    path_params = params.get("path") or {}
    value = path_params.get(name)

    return str(value).strip() if value else None


def get_query_param(event, name):
    for container_name in ("queryStringParameters",):
        container = event.get(container_name) or {}
        value = container.get(name)
        if value is not None:
            return str(value).strip()

    params = event.get("params") or {}
    query_params = params.get("query") or {}
    value = query_params.get(name)

    return str(value).strip() if value is not None else None


def get_header(event, name):
    headers = event.get("headers") or {}
    lowered = {str(k).lower(): v for k, v in headers.items()}
    return lowered.get(name.lower())


def sanitize_segment(value, field_name, max_length=128):
    if not isinstance(value, str):
        raise ValueError(f"Field '{field_name}' must be a string.")

    value = value.strip()
    if not value:
        raise ValueError(f"Field '{field_name}' cannot be empty.")

    value = value.replace("\\", "/")
    value = value.split("/")[-1] if field_name == "file_name" else value
    value = SAFE_SEGMENT_RE.sub("_", value)

    if value in {".", ".."} or not value:
        raise ValueError(f"Field '{field_name}' is invalid.")

    if len(value) > max_length:
        raise ValueError(f"Field '{field_name}' exceeds max length {max_length}.")

    return value


def validate_email(email_address):
    if not isinstance(email_address, str):
        raise ValueError("Recipient email must be a string.")

    email_address = email_address.strip()
    if not email_address:
        raise ValueError("Recipient email cannot be empty.")

    if len(email_address) > 320 or not EMAIL_RE.match(email_address):
        raise ValueError("Recipient email must be a valid email address.")

    return email_address


def normalize_optional_text(value, field_name):
    if value is None:
        return None

    if not isinstance(value, str):
        raise ValueError(f"Field '{field_name}' must be a string.")

    value = value.strip()
    return value or None


def validate_recipients(recipients):
    if not isinstance(recipients, list):
        raise ValueError("Field 'recipients' must be an array of email addresses.")

    if not recipients:
        raise ValueError("Field 'recipients' must contain at least one email address.")

    normalized = []
    seen = set()
    for recipient in recipients:
        try:
            email_address = validate_email(recipient)
        except ValueError as e:
            raise ValueError(
                "Field 'recipients' must contain valid email addresses."
            ) from e
        email_key = email_address.lower()
        if email_key in seen:
            continue
        seen.add(email_key)
        normalized.append(email_address)

    if not normalized:
        raise ValueError("Field 'recipients' must contain at least one email address.")

    return normalized


def parse_json_body(event):
    body = event.get("body")
    if body is None or body == "":
        raise ValueError("Request body must be a JSON object.")

    content_type = get_header(event, "Content-Type") or ""
    if "application/json" not in content_type.lower():
        raise ValueError("Content-Type must be application/json.")

    if event.get("isBase64Encoded"):
        try:
            body = base64.b64decode(body).decode("utf-8")
        except Exception as e:
            raise ValueError(f"Request body base64 is invalid: {e}") from e

    if isinstance(body, str):
        try:
            body = json.loads(body)
        except Exception as e:
            raise ValueError(f"Request body must be valid JSON: {e}") from e

    if not isinstance(body, dict):
        raise ValueError("Request body must be a JSON object.")

    return body


def extract_request(event):
    """
    Supported request variant:
    POST /backend-api/v1/send-email/{device_id}
    Content-Type: application/json
    {
      "file_name": "a.pdf",
      "recipients": ["user@example.com"],
      "subject": "Optional subject",
      "message": "Optional message",
      "file_base64": "..."
    }
    """
    device_id = get_path_param(event, "device_id")
    json_body = parse_json_body(event)

    recipients = json_body.get("recipients")
    subject = normalize_optional_text(json_body.get("subject"), "subject")
    message = normalize_optional_text(json_body.get("message"), "message")

    device_id = sanitize_segment(device_id, "device_id")
    recipients = validate_recipients(recipients)

    file_base64 = json_body.get("file_base64")
    file_name = None
    file_bytes = None

    if file_base64 is not None:
        if not isinstance(file_base64, str):
            raise ValueError("Field 'file_base64' must be a string.")

        if file_base64.strip():
            try:
                file_bytes = base64.b64decode(file_base64, validate=True)
            except Exception as e:
                raise ValueError(
                    f"Field 'file_base64' must be valid base64: {e}"
                ) from e

            if not file_bytes:
                raise ValueError("Uploaded file is empty.")

            if len(file_bytes) > MAX_FILE_BYTES:
                raise ValueError(
                    f"Uploaded file exceeds max size {MAX_FILE_BYTES} bytes."
                )

            file_name = normalize_optional_text(json_body.get("file_name"), "file_name")
            if file_name is None:
                file_name = f"file-{device_id}-{int(time.time())}.txt"

            file_name = sanitize_segment(file_name, "file_name", max_length=255)

    return {
        "device_id": device_id,
        "file_name": file_name,
        "recipients": recipients,
        "subject": subject,
        "message": message,
        "file_bytes": file_bytes,
    }


def build_storage_path(device_id, file_name):
    base_dir = os.path.abspath(os.path.join(STORAGE_ROOT, device_id))
    storage_root_abs = os.path.abspath(STORAGE_ROOT)

    if not base_dir.startswith(storage_root_abs):
        raise ValueError("Invalid storage path.")

    os.makedirs(base_dir, exist_ok=True)

    file_path = os.path.abspath(os.path.join(base_dir, file_name))
    if not file_path.startswith(base_dir):
        raise ValueError("Invalid file path.")

    return file_path


def save_file_to_mounted_bucket(device_id, file_name, file_bytes):
    file_path = build_storage_path(device_id, file_name)

    with open(file_path, "wb") as f:
        f.write(file_bytes)

    return file_path


def read_file_from_mounted_bucket(file_path):
    with open(file_path, "rb") as f:
        return f.read()


def resolve_email_subject(device_id, file_name=None, subject=None):
    if subject:
        return subject

    if file_name:
        return f"Файл от устройства {device_id}: {file_name}"

    return f"Сообщение от устройства {device_id}"


def resolve_email_message(device_id, file_name=None, message=None):
    if message:
        return message

    lines = [
        "Здравствуйте.",
        "",
    ]

    if file_name:
        lines.extend(
            [
                f"Во вложении файл от устройства: {device_id}",
                f"Имя файла: {file_name}",
                "",
            ]
        )
    else:
        lines.extend(
            [
                f"Сообщение от устройства: {device_id}",
                "",
            ]
        )

    lines.append("Письмо отправлено автоматически.")
    return "\n".join(lines)


def resolve_email_html_body(device_id, file_name=None, message=None):
    if message:
        return "".join(
            [
                "<!doctype html>",
                '<html lang="ru">',
                '<head><meta charset="utf-8"></head>',
                "<body>",
                f"<p>{escape(message).replace('\n', '<br>')}</p>",
                "</body>",
                "</html>",
            ]
        )

    safe_device_id = escape(device_id)

    if file_name:
        safe_file_name = escape(file_name)
        return "".join(
            [
                "<!doctype html>",
                '<html lang="ru">',
                '<head><meta charset="utf-8"></head>',
                "<body>",
                "<p>Здравствуйте.</p>",
                f"<p>Во вложении файл от устройства: <b>{safe_device_id}</b></p>",
                f"<p>Имя файла: <b>{safe_file_name}</b></p>",
                "<p>Письмо отправлено автоматически.</p>",
                "</body>",
                "</html>",
            ]
        )

    return "".join(
        [
            "<!doctype html>",
            '<html lang="ru">',
            '<head><meta charset="utf-8"></head>',
            "<body>",
            "<p>Здравствуйте.</p>",
            f"<p>Сообщение от устройства: <b>{safe_device_id}</b></p>",
            "<p>Письмо отправлено автоматически.</p>",
            "</body>",
            "</html>",
        ]
    )


def resolve_email_sender(device_id):
    # Sender is selected on the server, never from an untrusted JSON field.
    if not isinstance(device_id, str) or not device_id.strip():
        raise ValueError("device_id must be a non-empty suffix")
    if device_id == "l4desk-landing":
        sender, variable = EMAIL_FROM, "L4_EMAIL_FROM_L4DESK (or L4_EMAIL_FROM)"
    else:
        sender, variable = EMAIL_FROM_PL, "L4_EMAIL_FROM_PLATERRA"
    if not sender:
        raise RuntimeError(
            f"Email sender configuration is incomplete. Missing: {variable}"
        )
    try:
        return validate_email(sender)
    except ValueError as exc:
        raise RuntimeError(f"Invalid email sender configuration: {variable}") from exc


def ensure_email_config(device_id):
    sender = resolve_email_sender(device_id)
    missing = []
    if not ACCESS_KEY_ID:
        missing.append("ACCESS_KEY_ID")
    if not SECRET_ACCESS_KEY:
        missing.append("SECRET_ACCESS_KEY")
    if missing:
        raise RuntimeError(
            f"Email Postbox configuration is incomplete. Missing: {', '.join(missing)}"
        )
    return sender


def send_email_with_attachment(
    recipients, device_id, file_name=None, file_bytes=None, subject=None, message=None
):
    sender = ensure_email_config(device_id)

    email_subject = resolve_email_subject(device_id, file_name, subject)

    email_message = EmailMessage()
    email_message["From"] = sender
    email_message["To"] = ", ".join(recipients)
    email_message["Subject"] = email_subject

    email_message.set_content(resolve_email_message(device_id, file_name, message))
    html_body = resolve_email_html_body(device_id, file_name, message)

    email_message.add_alternative(html_body, subtype="html")

    if file_bytes is not None:
        if not isinstance(file_name, str) or not file_name:
            raise ValueError("Attachment file_name is required.")
        content_type, _ = mimetypes.guess_type(file_name)
        if content_type:
            maintype, subtype = content_type.split("/", 1)
        else:
            maintype, subtype = "application", "octet-stream"

        email_message.add_attachment(
            file_bytes,
            maintype=maintype,
            subtype=subtype,
            filename=file_name,
        )

    ses_client = boto3.client(
        "sesv2",
        endpoint_url=EMAIL_POSTBOX_ENDPOINT_URL,
        aws_access_key_id=ACCESS_KEY_ID,
        aws_secret_access_key=SECRET_ACCESS_KEY,
        config=Config(region_name=EMAIL_POSTBOX_REGION),
    )

    response = ses_client.send_email(
        FromEmailAddress=sender,
        Destination={
            "ToAddresses": recipients,
        },
        Content={
            "Raw": {
                "Data": email_message.as_bytes(),
            },
        },
    )

    return response.get("MessageId")


def handler(event, context):
    method = get_http_method(event)

    if method == "OPTIONS":
        return preflight_response()

    if method != "POST":
        return error_response(405, "METHOD_NOT_ALLOWED", "Only POST is allowed.")

    try:
        request = extract_request(event)

        saved_path = None
        file_bytes_from_bucket = None

        if request["file_bytes"] is not None:
            saved_path = save_file_to_mounted_bucket(
                request["device_id"],
                request["file_name"],
                request["file_bytes"],
            )

            # Required by the task: after saving to mounted bucket,
            # read the file back from bucket and attach this read content.
            file_bytes_from_bucket = read_file_from_mounted_bucket(saved_path)

        postbox_message_id = send_email_with_attachment(
            request["recipients"],
            request["device_id"],
            request["file_name"],
            file_bytes_from_bucket,
            subject=request["subject"],
            message=request["message"],
        )

        email_subject = resolve_email_subject(
            request["device_id"], request["file_name"], request["subject"]
        )

        logger.info(
            "send-email completed device_id=%s file_name=%s recipients=%s storage_path=%s postbox_message_id=%s",
            request["device_id"],
            request["file_name"],
            ",".join(request["recipients"]),
            saved_path,
            postbox_message_id,
        )

        response_body = {
            "status": "sent",
            "sender": resolve_email_sender(request["device_id"]),
            "device_id": request["device_id"],
            "recipients": request["recipients"],
            "subject": email_subject,
            "postbox_message_id": postbox_message_id,
        }
        if request["file_name"] is not None:
            response_body["file_name"] = request["file_name"]
        if saved_path is not None:
            response_body["storage_path"] = saved_path

        return json_response(response_body, 200)

    except ValueError as e:
        logger.warning("validation error: %s", e)
        return error_response(400, "VALIDATION_ERROR", str(e))

    except Exception as e:
        logger.exception("send-email failed: %s: %s", type(e).__name__, e)
        return error_response(
            503,
            "EMAIL_SEND_FAILED",
            f"Unable to save file or send email: {type(e).__name__}",
        )
