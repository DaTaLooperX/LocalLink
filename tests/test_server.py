"""Integration checks using real HTTP clients and an isolated temporary database."""
import concurrent.futures
import hashlib
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import ChatServer


class LocalLinkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.start_server()

    def start_server(self):
        self.server = ChatServer(("127.0.0.1", 0), self.temp.name, "test-password", 1, 2)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, method, path, obj=None, cookie=None, raw=None, extra=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        headers = {"X-Local-Chat": "1"}
        if cookie:
            headers["Cookie"] = cookie
        if obj is not None:
            raw = json.dumps(obj).encode()
            headers["Content-Type"] = "application/json"
        headers.update(extra or {})
        conn.request(method, path, body=raw, headers=headers)
        response = conn.getresponse()
        body = response.read()
        result = (response.status, dict(response.getheaders()), body)
        conn.close()
        return result

    def join(self, name="Alice"):
        code, headers, _ = self.request("POST", "/api/join", {"name": name, "password": "test-password"})
        self.assertEqual(code, 200)
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        return headers["Set-Cookie"].split(";")[0]

    def test_access_controls_and_input_validation(self):
        self.assertEqual(self.request("GET", "/api/messages")[0], 401)
        self.assertEqual(self.request("POST", "/api/join", {"name": "A", "password": "wrong"})[0], 403)
        self.assertEqual(self.request("POST", "/api/join", {"name": "A"}, extra={"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.request("GET", "/", extra={"Host": "evil.example"})[0], 403)
        cookie = self.join()
        self.assertEqual(self.request("POST", "/api/messages", {"text": " "}, cookie)[0], 400)
        self.assertEqual(self.request("POST", "/api/messages", {"text": "x" * 4001}, cookie)[0], 400)
        self.assertEqual(self.request("POST", "/api/messages", {"text": "hello"}, cookie, extra={"X-Local-Chat": ""})[0], 403)
        self.assertEqual(self.request("GET", "/files/../../server.py", cookie=cookie)[0], 404)
        self.assertEqual(self.request("POST", "/api/logout", {}, cookie)[0], 200)
        self.assertEqual(self.request("GET", "/api/me", cookie=cookie)[0], 401)

    def test_two_clients_and_live_delivery(self):
        alice = self.join("Alice")
        bob = self.join("Bob")
        with concurrent.futures.ThreadPoolExecutor() as pool:
            pending = pool.submit(self.request, "GET", "/api/messages?after=0", None, bob)
            time.sleep(0.1)
            code, _, body = self.request("POST", "/api/messages", {"text": "Hello سلام 🌿"}, alice)
            self.assertEqual(code, 201)
            sent = json.loads(body)
            code, _, body = pending.result(timeout=3)
            received = json.loads(body)
            self.assertEqual(received["messages"][0]["text"], "Hello سلام 🌿")
            self.assertEqual(received["messages"][0]["id"], sent["id"])
            self.assertEqual({p["name"] for p in received["people"]}, {"Alice", "Bob"})

    def test_files_integrity_unicode_names_empty_and_quota(self):
        alice = self.join()
        bob = self.join("Bob")
        data = bytes(range(256)) * 4096
        filename = "../../گزارش <demo>.bin"
        code, _, body = self.request("POST", "/api/files?name=" + quote(filename), cookie=alice, raw=data)
        self.assertEqual(code, 201)
        message = json.loads(body)
        self.assertEqual(message["filename"], "گزارش <demo>.bin")
        code, headers, downloaded = self.request("GET", "/files/" + message["file_id"], cookie=bob)
        self.assertEqual(code, 200)
        self.assertEqual(hashlib.sha256(data).digest(), hashlib.sha256(downloaded).digest())
        self.assertTrue(headers["Content-Disposition"].startswith("attachment;"))
        self.assertEqual(self.request("GET", "/files/" + message["file_id"])[0], 401)
        self.assertEqual(self.request("POST", "/api/files?name=empty.txt", cookie=alice, raw=b"")[0], 201)
        self.assertEqual(self.request("POST", "/api/files?name=second.bin", cookie=alice, raw=data)[0], 201)
        self.assertEqual(self.request("POST", "/api/files?name=full.bin", cookie=alice, raw=b"x")[0], 507)
        self.assertEqual(self.request("POST", "/api/files?name=big.bin", cookie=alice, raw=b"", extra={"Content-Length": str(1048577)})[0], 413)

    def test_history_pagination_and_restart_persistence(self):
        alice = self.join()
        for index in range(105):
            self.assertEqual(self.request("POST", "/api/messages", {"text": str(index)}, alice)[0], 201)
        _, _, body = self.request("GET", "/api/messages", cookie=alice)
        recent = json.loads(body)
        self.assertTrue(recent["has_more"])
        self.assertEqual(len(recent["messages"]), 100)
        _, _, body = self.request("GET", "/api/messages?before=" + str(recent["messages"][0]["id"]), cookie=alice)
        older = json.loads(body)
        self.assertEqual([m["text"] for m in older["messages"]], [str(i) for i in range(5)])
        _, _, body = self.request("GET", "/api/messages?after=0", cookie=alice)
        self.assertEqual([m["text"] for m in json.loads(body)["messages"]], [str(i) for i in range(100)])
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.start_server()
        bob = self.join("Bob")
        _, _, body = self.request("GET", "/api/messages", cookie=bob)
        self.assertEqual(json.loads(body)["messages"][-1]["text"], "104")


if __name__ == "__main__":
    unittest.main(verbosity=2)
