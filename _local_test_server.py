import json
import random
import string
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

from loguru import logger


class SimpleAuthServer(BaseHTTPRequestHandler):
    session_token = None
    validate_counter = 0

    def _set_headers(self, status_code=200):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()

    def _send_json_response(self, data, status_code=200):
        self._set_headers(status_code)
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def _issue_token(self):
        # Create a random token
        return "".join(random.choices(string.ascii_letters + string.digits, k=16))

    def do_POST(self):
        # Parse path and content length
        parsed_path = urlparse(self.path)
        content_length = int(self.headers["Content-Length"])
        post_data = self.rfile.read(content_length)
        data = json.loads(post_data)

        if parsed_path.path == "/authenticate":
            self.handle_auth(data)
        elif parsed_path.path == "/validate":
            self.handle_validate(data)
        else:
            self._send_json_response({"message": "Not Found"}, status_code=404)

    def handle_auth(self, data):
        user_id = data.get("userId")

        if user_id == "testUser":
            # Issue a new session token
            SimpleAuthServer.session_token = self._issue_token()
            SimpleAuthServer.validate_counter = 0
            self._send_json_response({"sessionToken": SimpleAuthServer.session_token})
        else:
            self._send_json_response(
                {"message": "Authentication failed."}, status_code=401
            )

    def handle_validate(self, data):
        token = data.get("sessionToken")
        logger.info(f"CurrentToken: {SimpleAuthServer.session_token} / UserToken: {token}")

        # Check if the token is valid and the counter is less than 4
        if (
            token == SimpleAuthServer.session_token
            # and SimpleAuthServer.validate_counter < 2
        ):
            SimpleAuthServer.validate_counter += 1
            self._send_json_response({"message": "Token valid"})
        else:
            # SimpleAuthServer.session_token = None  # Invalidate token
            self._send_json_response({"message": "Invalid token"}, status_code=401)


def run(server_class=HTTPServer, handler_class=SimpleAuthServer, port=8000):
    server_address = ("", port)
    httpd = server_class(server_address, handler_class)
    print(f"Starting http server on port {port}")
    httpd.serve_forever()


if __name__ == "__main__":
    run()
