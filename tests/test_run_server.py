import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


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
                serve, logger, app = Mock(), Mock(), object()
                scope = {
                    "os": SimpleNamespace(name=platform, getenv=environment.get, getpid=lambda: 123),
                    "socket": SimpleNamespace(gethostname=lambda: "test-host"),
                    "serve": serve,
                    "logger": logger,
                    "app": app,
                }
                exec(self.code, scope)
                scope["run_server"]()
                serve.assert_called_once()
                self.assertIs(serve.call_args.args[0], app)
                self.assertEqual(serve.call_args.kwargs["connection_limit"], expected)
                self.assertEqual(serve.call_args.kwargs["threads"], 8)
                self.assertIn("connection_limit=%s", logger.info.call_args.args[0])
                self.assertEqual(logger.info.call_args.args[-1], expected)


if __name__ == "__main__":
    unittest.main()
