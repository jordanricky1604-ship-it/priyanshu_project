import http.server
import socketserver
import threading
import os

class SandboxServer:
    def __init__(self, port=8080, directory="tests/sandbox"):
        self.port = port
        self.directory = directory
        self.httpd = None
        self.thread = None

    def start(self):
        import functools
        Handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=self.directory)
        # Allow reusing address to prevent tests from failing if port is locked
        socketserver.TCPServer.allow_reuse_address = True
        self.httpd = socketserver.TCPServer(("localhost", self.port), Handler)
        
        self.thread = threading.Thread(target=self.httpd.serve_forever)
        self.thread.daemon = True
        self.thread.start()

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.thread.join()

if __name__ == "__main__":
    server = SandboxServer()
    print("Starting sandbox server on port 8080...")
    server.start()
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.stop()
        print("Server stopped.")
