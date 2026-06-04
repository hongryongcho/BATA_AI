"""
BATAGOTA 랜딩 페이지 서버 (포트 8080)
"""
import http.server
import socketserver
from pathlib import Path

PORT = 8080
DIRECTORY = Path(__file__).parent


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIRECTORY), **kwargs)

    def log_message(self, format, *args):
        pass  # 로그 억제


if __name__ == "__main__":
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        httpd.serve_forever()
