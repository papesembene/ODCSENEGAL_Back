"""Isolation and failure-accounting checks for the JMeter harness."""
import os
import csv
import io
from datetime import datetime, timedelta
from contextlib import redirect_stderr
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'load_tests'))
import jmeter_isolated as load
from run_online_peaks import can_continue
from exam_scenario import exam_clock, make_exam_plan, exam_checks
from registration_campaign import make_endurance_plan, time_buckets, arrival_observation, ResourceSamples


class JMeterIsolationTests(unittest.TestCase):
    def test_campaign_cli_accepts_volume_and_one_hour_but_rejects_other_scenarios(self):
        with tempfile.TemporaryDirectory() as scratch:
            executable = Path(scratch) / 'tool'
            executable.write_text('argument validation only')
            base = ['jmeter_isolated.py', '--mongod', str(executable), '--jmeter', str(executable)]
            options = ['--preload-candidates', '50000', '--endurance-seconds', '3600', '--endurance-rate', '1']
            with patch.object(sys, 'argv', base + ['--scenario', 'registration', '--levels', '3000'] + options), patch.object(load, 'run', return_value=0) as run:
                self.assertEqual(load.main(), 0)
                self.assertEqual(run.call_args.args[0].timeout, 3900)
                self.assertEqual(run.call_args.args[0].preload_candidates, 50000)
            with patch.object(sys, 'argv', base + ['--scenario', 'exam15', '--levels', '1000'] + options), patch.object(load, 'run') as run, redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    load.main()
                run.assert_not_called()

    def test_endurance_uses_bounded_workers_and_skips_incomplete_final_round(self):
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / 'endurance.jmx'
            make_endurance_plan(path, 5401, 5, 3, 1, 'a'*32, 1794052800000)
            root = ET.parse(path)
            self.assertEqual(root.find(".//stringProp[@name='ThreadGroup.num_threads']").text, '3')
            self.assertEqual(root.find(".//stringProp[@name='LoopController.loops']").text, '2')
            self.assertEqual(len(root.findall('.//IfController/../hashTree/HTTPSamplerProxy')), 3)
            self.assertFalse(root.findall('.//SyncTimer'))
            self.assertIn('i &lt;= 5', path.read_text())
            self.assertIn('sequence * 3', path.read_text())
            self.assertEqual(len(root.findall('.//JSR223Timer')), 1)

    def test_endurance_buckets_use_chronological_origin_even_if_results_finish_out_of_order(self):
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / 'results.jtl'
            path.write_text('timeStamp,elapsed,label,responseCode,success\n'
                            '1301000,4000,Inscription,201,true\n'
                            '1000000,5,Campagne,200,true\n'
                            '1001000,6,Campagne,200,true\n', encoding='utf-8')
            buckets = time_buckets(path)
            self.assertEqual([b['from_seconds'] for b in buckets], [0, 300])
            self.assertEqual(buckets[0]['endpoints']['Campagne']['requests'], 2)
            self.assertEqual(buckets[1]['endpoints']['Inscription']['p95_ms'], 4000)
            self.assertEqual(arrival_observation(path)['observed_rate_per_second'], 1)

    def test_resource_monitor_handles_generator_not_started_and_writes_timestamped_phase(self):
        values = ResourceSamples()
        state = {'stop': False}
        stop = SimpleNamespace(is_set=lambda: state['stop'], wait=lambda delay: state.update(stop=True))
        load.sample_resources({'api': None, 'mongo': None, 'jmeter': None}, stop, values)
        self.assertEqual(len(values), 1)
        self.assertEqual(values[0]['jmeter_rss_mb'], 0)
        self.assertEqual(values[0]['phase'], 'preparation')
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / 'resources.csv'
            values.write_csv(path)
            self.assertIn('timestamp_utc', path.read_text())

    def test_three_thousand_allowed_only_for_registration(self):
        with tempfile.TemporaryDirectory() as scratch:
            executable = Path(scratch) / 'installed-tool'
            executable.write_text('placeholder for argument validation only')
            arguments = ['jmeter_isolated.py', '--mongod', str(executable), '--jmeter', str(executable), '--levels', '3000']
            with patch.object(sys, 'argv', arguments + ['--scenario', 'registration']), patch.object(load, 'run', return_value=0) as run:
                self.assertEqual(load.main(), 0)
                self.assertEqual(run.call_args.args[0].levels, [3000])
            with patch.object(sys, 'argv', arguments + ['--scenario', 'exam15']), patch.object(load, 'run') as run, redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    load.main()
                self.assertEqual(error.exception.code, 2)
                run.assert_not_called()

    def test_progressive_registrations_have_no_synchronization_barrier(self):
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / 'registration.jmx'
            load.make_plan(path, 5401, 3000, 60, 'registration', 'a'*32, registration_arrival='progressive')
            root = ET.parse(path)
            self.assertFalse(root.findall('.//SyncTimer'))
            self.assertEqual(len(root.findall('.//HTTPSamplerProxy')), 3)
            self.assertEqual(root.find(".//stringProp[@name='ThreadGroup.ramp_time']").text, '60')

    def test_registration_integrity_rejects_wrong_or_duplicate_candidate_identities(self):
        run_id = 'a'*32
        rows = [{'email': f'load-{run_id}-1@example.invalid', 'cni_or_passport_number': f'LOAD-{run_id}-1'},
                {'email': f'load-{run_id}-2@example.invalid', 'cni_or_passport_number': f'LOAD-{run_id}-2'}]
        db = SimpleNamespace(candidatures_load=SimpleNamespace(find=lambda *args: rows))
        self.assertTrue(load.registration_integrity(db, run_id, 2)['valid'])
        rows[1]['cni_or_passport_number'] = rows[0]['cni_or_passport_number']
        self.assertFalse(load.registration_integrity(db, run_id, 2)['valid'])

    def test_exam_clock_matches_real_fifteen_minute_backend_window(self):
        now = datetime(2026, 11, 7, 12, 0, 45)
        start, end = exam_clock(now=now)
        self.assertEqual(start, datetime(2026, 11, 7, 12, 2))
        self.assertEqual(end - start, timedelta(minutes=15))
        self.assertEqual(start.second, 0)
        self.assertGreaterEqual((start - now).total_seconds(), 60)

    def test_exam_metadata_preflight_rejects_stale_cached_duration(self):
        start = datetime(2026, 11, 7, 12, 2)
        metadata = {'duration': 60, 'scheduledDate': '2026-11-07', 'scheduledTime': '12:02'}
        response = SimpleNamespace(status_code=200, json=lambda: {'success': True, 'data': metadata})
        session = SimpleNamespace(get=lambda *a, **k: response)
        with patch.object(load.requests, 'Session') as factory:
            factory.return_value.__enter__.return_value = session
            env = {'PORT': '5401'}
            with self.assertRaisesRegex(RuntimeError, 'non confirmees'):
                load.verify_exam_metadata(env, 'test-id', start)
            metadata['duration'] = 15
            self.assertEqual(load.verify_exam_metadata(env, 'test-id', start)['duration_minutes'], 15)
            metadata['scheduledTime'] = '11:00'
            with self.assertRaisesRegex(RuntimeError, 'non confirmees'):
                load.verify_exam_metadata(env, 'test-id', start)

    def test_exam_has_repeated_drafts_and_common_deadline_not_short_combined_transaction(self):
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / 'exam.jmx'
            make_exam_plan(path, 5401, 2000, 60, 'b'*24, 1, 1794052800000)
            root = ET.parse(path)
            samples = root.findall('.//HTTPSamplerProxy')
            self.assertEqual(len(samples), 8)
            self.assertTrue(root.findall('.//WhileController'))
            self.assertFalse(root.findall('.//SyncTimer'))
            self.assertFalse(root.findall('.//ConstantTimer'))
            self.assertEqual(root.find('.//TransactionController').get('testname'), 'Connexion')
            periodic = next(s for s in samples if s.get('testname') == 'Brouillon periodique')
            self.assertEqual(periodic.find("stringProp[@name='HTTPSampler.response_timeout']").text, '8000')
            self.assertEqual(periodic.find(".//stringProp[@name='Argument.value']").text, '${draft_json}')
            text = path.read_text()
            self.assertIn('90000L', text)
            self.assertIn('31200L', text)
            self.assertIn("vars.get('submit_at')", text)
            self.assertIn("vars.get('expected_answers')", text)
            self.assertIn('1794053690000L', text)  # No new draft in last ten seconds.
            self.assertIn('1794053700000L', text)  # Final submission still at true expiry.

    def test_long_exam_csv_monitor_handles_partial_multiline_and_utf8_without_recounting(self):
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / 'live.jtl'
            buffer = io.StringIO(newline='')
            writer = csv.writer(buffer)
            writer.writerow(['label', 'success', 'responseCode', 'failureMessage'])
            writer.writerow(['Brouillon periodique', 'true', '200', ''])
            writer.writerow(['Soumission', 'false', '500', 'erreur\nreseau é'])
            raw = buffer.getvalue().encode('utf-8')
            cut = raw.index('é'.encode('utf-8')) + 1
            path.write_bytes(raw[:cut])
            monitor = load.LiveSamples()
            self.assertIsNone(monitor.poll(path))
            self.assertEqual(monitor.counts['Brouillon periodique'], 1)
            with path.open('ab') as target:
                target.write(raw[cut:])
            self.assertEqual(monitor.poll(path)['failureMessage'], 'erreur\nreseau é')
            self.assertEqual(monitor.counts['Brouillon periodique'], 1)
            self.assertEqual(monitor.counts['Soumission'], 1)
            monitor.poll(path)
            self.assertEqual(monitor.counts['Soumission'], 1)

    def test_exam_integrity_uses_latest_changing_answers_and_checks_draft_history(self):
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / 'exam.jtl'
            expected = {**load.ANSWERS, '2': 'revision 5'}
            rows = [{'candidate': {'email': 'a'}, 'answers': dict(expected)}]
            sessions = [{'candidateEmail': 'a', 'answers': dict(expected)}]
            db = SimpleNamespace(test_results=SimpleNamespace(find=lambda q: rows),
                                 test_sessions=SimpleNamespace(find=lambda q: sessions))
            with path.open('w', newline='') as target:
                writer = csv.DictWriter(target, fieldnames=['label', 'success', 'email', 'expected_answers'])
                writer.writeheader()
                writer.writerow({'label': 'Brouillon periodique', 'success': 'true', 'email': 'a'})
                writer.writerow({'label': 'Soumission', 'success': 'true', 'email': 'a',
                                 'expected_answers': __import__('json').dumps(expected)})
            result, _ = exam_checks(db, 'test', path, {'a'}, {'a'}, {}, 1)
            self.assertTrue(result['valid'])
            rows[0]['answers'] = dict(load.ANSWERS)
            self.assertFalse(exam_checks(db, 'test', path, {'a'}, {'a'}, {}, 1)[0]['valid'])
            rows[0]['answers'] = dict(expected)
            self.assertFalse(exam_checks(db, 'test', path, {'a'}, {'a'}, {}, 2)[0]['valid'])

    def test_suite_continues_after_only_a_latency_miss_and_stops_on_data_or_request_failure(self):
        report = {'cleanup_complete': True, 'passed': False,
                  'error': 'Seuil, erreurs ou integrite: aucun palier superieur lance',
                  'stages': [{'users': 1000, 'integrity_ok': True,
                              'endpoints': {'Connexion': {'requests': 1000, 'errors': 0}}}]}
        self.assertTrue(can_continue(report, 1000))
        report['stages'][0]['endpoints']['Connexion']['errors'] = 1
        self.assertFalse(can_continue(report, 1000))
        report['stages'][0]['endpoints']['Connexion']['errors'] = 0
        report['stages'][0]['integrity_ok'] = False
        self.assertFalse(can_continue(report, 1000))
        report['stages'][0]['integrity_ok'] = True
        report['error'] = 'CPU global au-dessus du seuil pendant une seconde; charge arretee'
        self.assertFalse(can_continue(report, 1000))
        report['passed'] = True
        report['cleanup_complete'] = False
        self.assertFalse(can_continue(report, 1000))

    def test_peak_profiles_match_requested_ramps_and_thresholds(self):
        for mode, ramp, threshold in [('connection', 60, 3000), ('submission', 10, 5000), ('combined', 60, 5000)]:
            with self.subTest(mode=mode):
                self.assertEqual(load.PEAK_PROFILES[mode]['ramp'], ramp)
                self.assertEqual(load.PEAK_PROFILES[mode]['p95'], threshold)
                self.assertEqual(load.build_schedule([1000], mode), [(mode, 1, 0), (mode, 1000, 1)])

    def test_peaks_measure_only_the_requested_http_actions_without_barrier_or_pause(self):
        with tempfile.TemporaryDirectory() as scratch:
            for mode, count in [('connection', 3), ('submission', 1), ('combined', 5)]:
                with self.subTest(mode=mode):
                    path = Path(scratch) / f'{mode}.jmx'
                    load.make_plan(path, 5401, 1000, load.PEAK_PROFILES[mode]['ramp'], mode, 'a'*32, 'b'*24, 1)
                    root = ET.parse(path)
                    samplers = root.findall('.//HTTPSamplerProxy')
                    self.assertEqual(len(samplers), count)
                    self.assertFalse(root.findall('.//SyncTimer'))
                    self.assertFalse(root.findall('.//ConstantTimer'))
                    names = {item.get('testname') for item in samplers}
                    if mode == 'connection':
                        self.assertEqual(names, {'Metadonnees', 'Acces', 'Questions'})
                    if mode == 'submission':
                        self.assertEqual(names, {'Soumission'})
                    if mode != 'submission':
                        self.assertEqual(root.find('.//TransactionController').get('testname'), load.PEAK_PROFILES[mode]['target'])

    def test_valid_accesses_must_belong_to_distinct_expected_candidates(self):
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / 'access.jtl'
            path.write_text('label,success,email\nAcces,true,a\nAcces,true,a\n', encoding='utf-8')
            self.assertFalse(load.access_integrity(path, {'a', 'b'})['valid'])
            path.write_text('label,success,email\nAcces,true,a\nAcces,true,b\n', encoding='utf-8')
            self.assertTrue(load.access_integrity(path, {'a', 'b'})['valid'])

    def test_submission_integrity_rejects_duplicates_missing_sessions_and_lost_answers(self):
        rows = [{'candidate': {'email': 'a'}, 'answers': dict(load.ANSWERS)},
                {'candidate': {'email': 'b'}, 'answers': dict(load.ANSWERS)}]
        sessions = [{'candidateEmail': 'a', 'answers': dict(load.ANSWERS)},
                    {'candidateEmail': 'b', 'answers': dict(load.ANSWERS)}]
        db = SimpleNamespace(test_results=SimpleNamespace(find=lambda query: rows),
                             test_sessions=SimpleNamespace(find=lambda query: sessions))
        result = load.result_integrity(db, 'test', {'a', 'b'}, {'b'})
        self.assertTrue(result['valid'])
        self.assertEqual(result['unique_stage_submissions'], 1)
        rows[1]['candidate']['email'] = 'a'
        self.assertFalse(load.result_integrity(db, 'test', {'a', 'b'})['valid'])
        rows[1]['candidate']['email'] = 'b'
        rows[1]['answers'] = {}
        self.assertFalse(load.result_integrity(db, 'test', {'a', 'b'})['valid'])
        rows[1]['answers'] = dict(load.ANSWERS)
        sessions.pop()
        self.assertFalse(load.result_integrity(db, 'test', {'a', 'b'})['valid'])

    def test_independent_online_run_skips_registration_and_never_reuses_candidate(self):
        schedule = load.build_schedule([500, 1000], 'online')
        self.assertEqual(schedule, [('online', 1, 0), ('online', 500, 1), ('online', 1000, 501)])
        ids = [candidate for _, users, offset in schedule for candidate in range(offset + 1, offset + users + 1)]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(load.build_schedule([500], 'registration'),
                         [('registration', 1, 0), ('registration', 500, 0)])
        self.assertEqual(len(load.build_schedule([500], 'both')), 4)

    def test_production_targets_rejected_before_app_import(self):
        with tempfile.TemporaryDirectory() as scratch:
            env = load.child_environment('a' * 32, 27029, 5401, Path(scratch), 8, 50)
            env.update({'EMAIL_PROVIDER': 'smtp', 'ODC_JMETER_MONGO_PORT': '27029'})
            for key, value in (
                ('MONGO_URI', 'mongodb://127.0.0.1:27017/production'),
                ('MONGO_DBNAME', 'production'),
                ('HOST', '0.0.0.0'),
                ('EMAIL_PROVIDER', 'resend'),
            ):
                with self.subTest(key=key), patch.dict(os.environ, {**env, key: value}, clear=True):
                    with self.assertRaisesRegex(RuntimeError, 'non-isolated'):
                        load.isolated_child()

    def test_every_http_sampler_targets_loopback_and_stops_on_failure(self):
        with tempfile.TemporaryDirectory() as scratch:
            for mode, expected in [('registration', 3), ('online', 5)]:
                path = Path(scratch) / f'{mode}.jmx'
                load.make_plan(path, 5401, 500, 60, mode, 'b' * 32, 'c' * 24, 501)
                root = ET.parse(path)
                samples = root.findall('.//HTTPSamplerProxy')
                self.assertEqual(len(samples), expected)
                for sample in samples:
                    self.assertEqual(sample.find("stringProp[@name='HTTPSampler.domain']").text, '127.0.0.1')
                    self.assertEqual(sample.find("stringProp[@name='HTTPSampler.port']").text, '5401')
                    self.assertEqual(sample.find("boolProp[@name='HTTPSampler.follow_redirects']").text, 'false')
                    self.assertEqual(sample.find("boolProp[@name='HTTPSampler.use_keepalive']").text, 'false')
                self.assertEqual(root.find(".//stringProp[@name='ThreadGroup.on_sample_error']").text, 'stopthread')
                self.assertEqual(root.find(".//stringProp[@name='LoopController.loops']").text, '1')
                self.assertEqual(root.find(".//boolProp[@name='LoopController.continue_forever']").text, 'false')
                self.assertEqual(len(root.findall('.//JSR223Assertion')), expected)
                self.assertEqual(root.find(".//SyncTimer/intProp[@name='groupSize']").text, '500')
                self.assertEqual(root.find(".//SyncTimer/longProp[@name='timeoutInMs']").text, '0')

    def test_email_and_external_connections_blocked_before_network_io(self):
        with tempfile.TemporaryDirectory() as scratch:
            env = load.child_environment('a' * 32, 27029, 5401, Path(scratch), 8, 50)
            env.update({'EMAIL_PROVIDER': 'smtp', 'ODC_JMETER_MONGO_PORT': '27029'})
            code = '''
import jmeter_isolated as load
load.isolated_child()
import socket, smtplib
from app.services.email_transport import EmailTransport
checks = [lambda: EmailTransport().send_html([], 'test', 'test'),
          lambda: socket.create_connection(('192.0.2.1', 443), timeout=.1),
          lambda: smtplib.SMTP('127.0.0.1', 2525, timeout=.1)]
for check in checks:
    try:
        check()
    except RuntimeError as error:
        assert 'forbidden' in str(error)
    else:
        raise AssertionError('Email or network was not blocked')
'''
            result = subprocess.run([sys.executable, '-c', code], env=env,
                cwd=Path(load.__file__).parent, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_failed_requests_count_in_percentiles_and_error_total(self):
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / 'results.jtl'
            path.write_text('elapsed,label,responseCode,success\n10,Inscription,201,true\n2000,Inscription,500,false\n', encoding='utf-8')
            result = load.read_results(path)['Inscription']
            self.assertEqual(result['requests'], 2)
            self.assertEqual(result['errors'], 1)
            self.assertEqual(result['p95_ms'], 2000)

    def test_failed_preflight_detected_while_other_users_wait_at_barrier(self):
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / 'live.jtl'
            self.assertIsNone(load.first_failed_sample(path))
            path.write_text('elapsed,label,responseCode,success,failureMessage\n10,Campagne,200,true,\n20000,Campagne,Non HTTP response,false,timeout\n2,Unicite', encoding='utf-8')
            self.assertEqual(load.first_failed_sample(path)['failureMessage'], 'timeout')
            self.assertEqual(set(load.read_results(path)), {'Campagne'})


if __name__ == '__main__':
    unittest.main()
