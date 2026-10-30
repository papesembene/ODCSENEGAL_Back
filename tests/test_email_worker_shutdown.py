from contextlib import nullcontext
import importlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch


class EmailWorkerShutdownTest(unittest.TestCase):
    def test_stop_marker_prevents_claiming_another_job(self):
        worker=importlib.import_module('email_worker')
        with tempfile.TemporaryDirectory() as directory:
            marker=Path(directory)/'stop'
            marker.touch()
            app=Mock()
            app.app_context.return_value=nullcontext()
            with patch.dict(os.environ,{'ODC_EMAIL_STOP_FILE':str(marker),'ODC_EMAIL_HEARTBEAT_FILE':str(Path(directory)/'heartbeat')}), patch.object(worker,'create_app',return_value=app), patch.object(worker,'EmailOutbox') as queue, patch.object(worker.signal,'signal'):
                worker.main()
            queue.return_value.run_once.assert_not_called()

    def test_current_job_finishes_before_stop_is_observed(self):
        worker=importlib.import_module('email_worker')
        with tempfile.TemporaryDirectory() as directory:
            marker=Path(directory)/'stop'
            app=Mock()
            app.app_context.return_value=nullcontext()
            def finish_job():
                marker.touch()
                return True
            with patch.dict(os.environ,{'ODC_EMAIL_STOP_FILE':str(marker),'ODC_EMAIL_HEARTBEAT_FILE':str(Path(directory)/'heartbeat')}), patch.object(worker,'create_app',return_value=app), patch.object(worker,'EmailOutbox') as queue, patch.object(worker.signal,'signal'), patch.object(worker.time,'sleep'):
                queue.return_value.run_once.side_effect=finish_job
                worker.main()
            queue.return_value.run_once.assert_called_once_with()
