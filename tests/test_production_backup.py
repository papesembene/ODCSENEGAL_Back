import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('production_backup',Path(__file__).resolve().parents[1]/'ops'/'deployment'/'production_backup.py')
backup=importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


class ProductionBackupTest(unittest.TestCase):
    def test_failed_export_keeps_successful_backups_and_bounds_failed_attempts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            destination=root/'backups'
            destination.mkdir()
            successful=destination/'daily-20261001T023000-aaaaaaaa'
            successful.mkdir()
            (successful/'complete.json').write_text(json.dumps({'schema':1}))
            for index in range(3):
                (destination/f'daily-2026100{index+2}T023000-bbbbbbbb').mkdir()
            env=root/'private.env'
            env.write_text('MONGO_URI=mongodb://127.0.0.1:1/test\nMONGO_DBNAME=test\n')
            with patch.object(backup.subprocess,'run',return_value=SimpleNamespace(returncode=1)):
                with self.assertRaisesRegex(RuntimeError,'export failed'):
                    backup.backup(env,root,root,destination)
            self.assertTrue(successful.exists())
            self.assertEqual(len(list(destination.iterdir())),3)
            self.assertEqual(list(destination.rglob('mongodump-private.yml')),[])

    def test_retention_preserves_seven_successes_and_two_incomplete_copies(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            completed=[]
            partial=[]
            for index in range(10):
                folder=root/f'daily-202610{index+1:02}T023000-aaaaaaaa'
                folder.mkdir()
                (folder/'complete.json').write_text(json.dumps({'schema':1}))
                completed.append(folder)
            for index in range(3):
                folder=root/f'daily-202610{index+11:02}T023000-bbbbbbbb'
                folder.mkdir()
                partial.append(folder)
            legacy=root/'production-20261022.archive.gz'
            legacy.write_bytes(b'legacy')
            backup.prune(root)
            self.assertEqual([p.exists() for p in completed],[False]*3+[True]*7)
            self.assertEqual([p.exists() for p in partial],[False,True,True])
            self.assertTrue(legacy.exists())

    def test_cleanup_refuses_paths_outside_backup_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            target=root/'protected'
            target.mkdir()
            with self.assertRaisesRegex(RuntimeError,'deletion refused'):
                backup.remove_backup(target,root/'backups')
            self.assertTrue(target.exists())
