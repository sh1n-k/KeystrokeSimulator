import json
import socketserver
from http.server import BaseHTTPRequestHandler, HTTPServer

class TestRequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        # Check the path to determine the endpoint
        if self.path == '/auth':
            self.handle_auth()
        elif self.path == '/validate':
            self.handle_validate()
        else:
            self.send_response(404)
            self.end_headers()

    def handle_auth(self):
        # Read the request body
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        data = json.loads(post_data)

        # Extract userId from the request
        user_id = data.get('userId')

        # Check if the userId is 'testUser'
        if user_id == 'testUser':
            # Respond with success
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            response = {
                'is_active': True,
                'session_token': 'dummy_token'
            }
        else:
            # Respond with error
            self.send_response(401)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            response = {
                'is_active': False,
                'error': 'Invalid user'
            }

        # Write the response body
        self.wfile.write(json.dumps(response).encode('utf-8'))

    def handle_validate(self):
        # Read the request body
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        data = json.loads(post_data)

        # Extract sessionToken from the request
        session_token = data.get('sessionToken')

        # For simplicity, always validate successfully if session_token is present
        if session_token == 'dummy_token':
            # Respond with success
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            response = {
                'is_active': True
            }
        else:
            # Respond with error
            self.send_response(401)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            response = {
                'is_active': False
            }

        # Write the response body
        self.wfile.write(json.dumps(response).encode('utf-8'))


def run(server_class=HTTPServer, handler_class=TestRequestHandler, port=8000):
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)
    print(f'Starting test server on port {port}...')
    httpd.serve_forever()

if __name__ == '__main__':
    run()
