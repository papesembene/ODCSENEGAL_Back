import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call


class ProductionServerConnectionLimitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "run.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                        and node.name == "run_server")
        # Execute the actual entrypoint function without importing create_app or
        # opening database connections during configuration-only tests.
        cls.code = compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec")

    def scope(self, platform, environment=None, server=None):
        server = Mock() if server is None else server
        creator, logger, app = Mock(return_value=server), Mock(), object()
        scope = {
            "os": SimpleNamespace(name=platform, getenv=(environment or {}).get, getpid=lambda: 123),
            "socket": SimpleNamespace(gethostname=lambda: "test-host"),
            "create_server": creator,
            "logger": logger,
            "app": app,
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

    def test_backlog_is_reapplied_only_on_windows_before_run_and_close(self):
        for platform, configured, expected in [("nt", None, 2048), ("nt", "4096", 4096),
                                                 ("posix", None, 1024), ("posix", "4096", 4096)]:
            with self.subTest(platform=platform, configured=configured):
                environment = {"WAITRESS_THREADS": "64"}
                if configured is not None:
                    environment["WAITRESS_BACKLOG"] = configured
                scope, creator, logger, server = self.scope(platform, environment)
                scope["run_server"]()
                self.assertEqual(creator.call_args.kwargs["backlog"], expected)
                self.assertEqual(creator.call_args.kwargs["threads"], 64)
                self.assertEqual(logger.info.call_args.args[-1], expected)
                expected_calls = [call.socket.listen(expected)] if platform == "nt" else []
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

    def test_server_is_closed_when_native_listen_fails(self):
        server = Mock()
        server.socket.listen.side_effect = OSError("listen failed")
        scope, _, _, _ = self.scope("nt", server=server)
        with self.assertRaisesRegex(OSError, "listen failed"):
            scope["run_server"]()
        server.run.assert_not_called()
        server.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
