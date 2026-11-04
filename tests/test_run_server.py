import ast
import ctypes
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call


class ProductionServerConnectionLimitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "run.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name in {"_listen_windows", "run_server"}]
        # Execute the actual entrypoint function without importing create_app or
        # opening database connections during configuration-only tests.
        cls.code = compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec")

    def scope(self, platform, environment=None, server=None):
        server = Mock() if server is None else server
        creator, logger, app = Mock(return_value=server), Mock(), object()
        winsock = Mock()
        winsock.listen.return_value = 0
        winsock.WSAGetLastError.return_value = 10055
        scope = {
            "os": SimpleNamespace(name=platform, getenv=(environment or {}).get, getpid=lambda: 123),
            "socket": SimpleNamespace(gethostname=lambda: "test-host"),
            "create_server": creator,
            "logger": logger,
            "app": app,
            "ctypes": SimpleNamespace(WinDLL=Mock(return_value=winsock),
                                      c_size_t=ctypes.c_size_t, c_int=ctypes.c_int),
        }
        exec(self.code, scope)
        return scope, creator, logger, server

    def test_platform_connection_limits_and_startup_log(self):
        cases = [
            ("nt", None, 500),
            ("nt", "1000", 500),
            ("nt", "512", 500),
            ("nt", "128", 128),
            ("posix", None, 1000),
            ("posix", "2048", 2048),
            ("posix", "128", 128),
        ]
        for platform, configured, expected in cases:
            with self.subTest(platform=platform, configured=configured):
                environment = {} if configured is None else {"WAITRESS_CONNECTION_LIMIT": configured}
                scope, creator, logger, server = self.scope(platform, environment)
                scope["run_server"]()
                creator.assert_called_once()
                self.assertIs(creator.call_args.args[0], scope["app"])
                self.assertEqual(creator.call_args.kwargs["connection_limit"], expected)
                self.assertEqual(creator.call_args.kwargs["threads"], 8)
                self.assertIn("connection_limit=%s", logger.info.call_args.args[0])
                self.assertEqual(logger.info.call_args.args[-2], expected)

    def test_windows_hint_is_first_listen_before_accept_run_and_close(self):
        for platform, configured, expected in [("nt", None, 2048), ("nt", "4096", 4096),
                                                 ("posix", None, 1024), ("posix", "4096", 4096)]:
            with self.subTest(platform=platform, configured=configured):
                environment = {"WAITRESS_THREADS": "64"}
                if configured is not None:
                    environment["WAITRESS_BACKLOG"] = configured
                scope, creator, logger, server = self.scope(platform, environment)
                server.socket.fileno.return_value = 12345
                native = scope["ctypes"].WinDLL.return_value
                before_accept = []
                native.listen.side_effect = lambda *args: before_accept.append(server.accept_connections.call_count) or 0
                scope["run_server"]()
                self.assertEqual(creator.call_args.kwargs["backlog"], expected)
                self.assertEqual(creator.call_args.kwargs["threads"], 64)
                self.assertEqual(logger.info.call_args.args[-1], expected)
                if platform == "nt":
                    self.assertIs(creator.call_args.kwargs["_start"], False)
                    scope["ctypes"].WinDLL.assert_called_once_with("Ws2_32")
                    native.listen.assert_called_once_with(12345, -expected)
                    self.assertEqual(native.listen.argtypes, (ctypes.c_size_t, ctypes.c_int))
                    self.assertIs(native.listen.restype, ctypes.c_int)
                    self.assertEqual(before_accept, [0])
                    expected_calls = [call.socket.fileno(), call.accept_connections()]
                else:
                    self.assertNotIn("_start", creator.call_args.kwargs)
                    scope["ctypes"].WinDLL.assert_not_called()
                    expected_calls = []
                self.assertEqual(server.mock_calls, expected_calls + [call.run(), call.close()])

    def test_server_is_closed_when_run_fails(self):
        server = Mock()
        server.run.side_effect = RuntimeError("run failed")
        scope, _, _, _ = self.scope("nt", server=server)
        with self.assertRaisesRegex(RuntimeError, "run failed"):
            scope["run_server"]()
        server.close.assert_called_once_with()

    def test_missing_windows_listener_fails_clearly_and_closes_server(self):
        server = SimpleNamespace(run=Mock(), close=Mock())
        scope, _, _, _ = self.scope("nt", server=server)
        with self.assertRaisesRegex(RuntimeError, "one listening socket"):
            scope["run_server"]()
        server.run.assert_not_called()
        server.close.assert_called_once_with()

    def test_winsock_error_is_reported_and_server_closed_before_accept(self):
        server = Mock()
        scope, _, _, _ = self.scope("nt", server=server)
        native = scope["ctypes"].WinDLL.return_value
        native.listen.return_value = -1
        with self.assertRaisesRegex(OSError, "Windows listen failed") as error:
            scope["run_server"]()
        self.assertEqual(error.exception.errno, 10055)
        native.WSAGetLastError.assert_called_once_with()
        self.assertEqual(native.WSAGetLastError.argtypes, ())
        self.assertIs(native.WSAGetLastError.restype, ctypes.c_int)
        server.accept_connections.assert_not_called()
        server.run.assert_not_called()
        server.close.assert_called_once_with()

    def test_windows_backlog_boundaries_are_validated_before_server_creation(self):
        for backlog in ("0", "199", "65536"):
            with self.subTest(backlog=backlog):
                scope, creator, _, _ = self.scope("nt", {"WAITRESS_BACKLOG": backlog})
                with self.assertRaisesRegex(ValueError, "between 200 and 65535"):
                    scope["run_server"]()
                creator.assert_not_called()
                scope["ctypes"].WinDLL.assert_not_called()
        for backlog in ("200", "65535"):
            with self.subTest(backlog=backlog):
                scope, _, _, _ = self.scope("nt", {"WAITRESS_BACKLOG": backlog})
                scope["run_server"]()
                self.assertEqual(scope["ctypes"].WinDLL.return_value.listen.call_args.args[1], -int(backlog))


if __name__ == "__main__":
    unittest.main()
