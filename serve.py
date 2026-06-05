#!/usr/bin/env python3
"""Simple HTTP server with CORS headers for local IIIF testing."""
from http.server import SimpleHTTPRequestHandler, HTTPServer

class CORSHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        pass  # suppress logs

if __name__ == "__main__":
    server = HTTPServer(("localhost", 8000), CORSHandler)
    print("Serving at http://localhost:8000")
    server.serve_forever()
