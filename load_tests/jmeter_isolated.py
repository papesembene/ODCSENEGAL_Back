"""Run JMeter against a private API and disposable MongoDB, never production.

Requires this backend's dependencies, mongod, Java and Apache JMeter installed.
No remote URL, existing database URI or production env file is accepted.
"""
import argparse
import codecs
from collections import Counter
import csv
from datetime import datetime, timedelta, timezone
import json
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from uuid import uuid4
import xml.etree.ElementTree as ET

from pymongo import MongoClient
from bson import ObjectId
import requests

from registration_load import (
    ROOT, child_environment, free_port, sample_resources, stop_process, summarize,
)
from registration_campaign import ResourceSamples, peak_resources, make_endurance_plan, time_buckets, arrival_observation

ANSWERS = {'0': 2, '1': [0, 1, 3], '2': 'Reponse de charge'}
PEAK_PROFILES = {
    'connection': {'ramp': 60, 'p95': 3000, 'target': 'Connexion',
                   'labels': {'Metadonnees', 'Acces', 'Questions', 'Connexion'}},
    'submission': {'ramp': 10, 'p95': 5000, 'target': 'Soumission',
                   'labels': {'Soumission'}},
    'combined': {'ramp': 60, 'p95': 5000, 'target': 'Combine',
                 'labels': {'Metadonnees', 'Acces', 'Questions', 'Brouillon', 'Soumission', 'Combine'}},
}


def isolated_child():
    """Validate all targets before importing the app or loading any dotenv."""
    run_id = os.environ.get('ODC_LOAD_RUN_ID', '')
    database = 'odc_registration_load_' + run_id
    mongo_port = os.environ.get('ODC_JMETER_MONGO_PORT', '')
    if (len(run_id) != 32 or any(c not in '0123456789abcdef' for c in run_id)
            or not mongo_port.isdigit()
            or os.environ.get('MONGO_DBNAME') != database
            or os.environ.get('MONGO_URI') != f'mongodb://127.0.0.1:{mongo_port}/{database}'
            or os.environ.get('HOST') != '127.0.0.1'
            or os.environ.get('EMAIL_PROVIDER') != 'smtp'
            or os.environ.get('EMAIL_DELIVERY_MODE') != 'queued'
            or Path(os.environ.get('ODC_ENV_FILE', '')).read_text(encoding='utf-8').strip()
            != '# Deliberately empty; no production configuration.'):
        raise RuntimeError('Refusing non-isolated child configuration')

    # Defense in depth: application and seeder cannot open external connections,
    # including HTTPS email APIs. SMTP connections are forbidden even on loopback.
    def network_guard(event, args):
        if event == 'smtplib.connect':
            raise RuntimeError('SMTP forbidden in isolated load environment')
        if event == 'socket.connect':
            address = args[1]
            if not isinstance(address, tuple) or address[0] != '127.0.0.1':
                raise RuntimeError('External connection forbidden in isolated load environment')
    sys.addaudithook(network_guard)
    sys.path.insert(0, str(ROOT))
    from app.services.email_transport import EmailTransport

    def forbidden_email(*args, **kwargs):
        raise RuntimeError('Email delivery forbidden in isolated load environment')
    EmailTransport.send_html = forbidden_email


def child_seed(count, output):
    isolated_child()
    from app import create_app
    from seed_online_test_load_data import seed_load_data
    app = create_app()
    with app.app_context():
        test, _group, total = seed_load_data(count, 'Dev Web', str(output / 'candidates.csv'))
        (output / 'test.json').write_text(json.dumps({'id': str(test.id), 'count': total}), encoding='utf-8')


def prop(parent, name, value, kind='stringProp'):
    item = ET.SubElement(parent, kind, name=name)
    item.text = str(value)
    return item


def node(parent, tag, name, gui):
    element = ET.SubElement(parent, tag, guiclass=gui, testclass=tag, testname=name, enabled='true')
    tree = ET.SubElement(parent, 'hashTree')
    return element, tree


def sampler(tree, name, method, path, port, body=None, expected=200, check=None, synchronize=0, timeout_ms=20000):
    element, children = node(tree, 'HTTPSamplerProxy', name, 'HttpTestSampleGui')
    for key, value in {
        'domain': '127.0.0.1', 'port': port, 'protocol': 'http',
        'path': path, 'method': method, 'connect_timeout': 10000,
        'response_timeout': timeout_ms, 'contentEncoding': 'UTF-8',
    }.items():
        prop(element, 'HTTPSampler.' + key, value)
    # Do not hold hundreds of idle preflight connections at the barrier.
    # Windows Waitress counts its listener/trigger against its connection limit.
    for key, value in {'follow_redirects': 'false', 'auto_redirects': 'false', 'use_keepalive': 'false'}.items():
        prop(element, 'HTTPSampler.' + key, value, 'boolProp')
    args = ET.SubElement(element, 'elementProp', name='HTTPsampler.Arguments', elementType='Arguments',
                         guiclass='HTTPArgumentsPanel', testclass='Arguments', enabled='true')
    collection = ET.SubElement(args, 'collectionProp', name='Arguments.arguments')
    if body is not None:
        prop(element, 'HTTPSampler.postBodyRaw', 'true', 'boolProp')
        argument = ET.SubElement(collection, 'elementProp', name='', elementType='HTTPArgument')
        prop(argument, 'HTTPArgument.always_encode', 'false', 'boolProp')
        prop(argument, 'Argument.value', body if isinstance(body, str) else json.dumps(body, ensure_ascii=False))
        prop(argument, 'Argument.metadata', '=')
    if synchronize:
        timer, _ = node(children, 'SyncTimer', 'Attendre tous les utilisateurs', 'TestBeanGUI')
        prop(timer, 'groupSize', synchronize, 'intProp')
        # No partial burst: launcher timeout stops JMeter if a user never arrives.
        prop(timer, 'timeoutInMs', 0, 'longProp')
    assertion, _ = node(children, 'JSR223Assertion', 'HTTP et contenu attendus', 'TestBeanGUI')
    prop(assertion, 'scriptLanguage', 'groovy')
    prop(assertion, 'cacheKey', 'true')
    script = f"if (prev.getResponseCode() != '{expected}') {{ AssertionResult.setFailure(true); AssertionResult.setFailureMessage('Unexpected HTTP: ' + prev.getResponseCode() + ' ' + prev.getResponseDataAsString().take(300)); return }}\n"
    if check:
        script += "def body = new groovy.json.JsonSlurper().parseText(prev.getResponseDataAsString())\n"
        script += f"if (!({check})) {{ AssertionResult.setFailure(true); AssertionResult.setFailureMessage('Invalid response content: ' + prev.getResponseDataAsString().take(400)) }}"
    prop(assertion, 'script', script)
    return children


def make_plan(path, port, users, ramp, mode, run_id, test_id='', offset=0, registration_arrival='burst'):
    root = ET.Element('jmeterTestPlan', version='1.2', properties='5.0', jmeter='5.6.3')
    top = ET.SubElement(root, 'hashTree')
    plan, plan_tree = node(top, 'TestPlan', 'ODC - base et API jetables', 'TestPlanGui')
    ET.SubElement(ET.SubElement(plan, 'elementProp', name='TestPlan.user_defined_variables',
                               elementType='Arguments'), 'collectionProp', name='Arguments.arguments')
    group, tree = node(plan_tree, 'ThreadGroup', mode, 'ThreadGroupGui')
    prop(group, 'ThreadGroup.num_threads', users)
    prop(group, 'ThreadGroup.ramp_time', ramp)
    prop(group, 'ThreadGroup.on_sample_error', 'stopthread')
    controller = ET.SubElement(group, 'elementProp', name='ThreadGroup.main_controller',
                               elementType='LoopController', guiclass='LoopControlPanel',
                               testclass='LoopController', enabled='true')
    prop(controller, 'LoopController.loops', 1)
    prop(controller, 'LoopController.continue_forever', 'false', 'boolProp')
    headers, _ = node(tree, 'HeaderManager', 'JSON', 'HeaderPanel')
    header = ET.SubElement(ET.SubElement(headers, 'collectionProp', name='HeaderManager.headers'),
                           'elementProp', name='', elementType='Header')
    prop(header, 'Header.name', 'Content-Type')
    prop(header, 'Header.value', 'application/json')
    if mode == 'registration':
        setup, _ = node(tree, 'JSR223Sampler', 'Identite synthetique', 'TestBeanGUI')
        prop(setup, 'scriptLanguage', 'groovy')
        prop(setup, 'script', "vars.put('i', (ctx.getThreadNum() + 1).toString())")
        email = f'load-{run_id}-${{i}}@example.invalid'
        sampler(tree, 'Campagne', 'GET', '/api/candidature/status?formation=Dev%20Web', port,
                check='body.data?.isOpen == true')
        sampler(tree, 'Unicite', 'GET', f'/api/candidature/check-unique?field=email&value={email}', port,
                check='body.exists == false')
        payload = {
            'first_name': 'TEST-CHARGE', 'last_name': 'ODC-${i}', 'email': email,
            'phone': '770000000', 'date_of_birth': '2000-01-01', 'place_of_birth': 'Dakar',
            'gender': 'male', 'cni_or_passport_number': f'LOAD-{run_id}-${{i}}',
            'nationality': 'Senegalaise', 'region_of_residence': 'Dakar',
            'computer_skills': True, 'available_for_10_months': True,
            'desired_training': 'Dev Web', 'training_site': 'dakar', 'accept_conditions': True,
        }
        sampler(tree, 'Inscription', 'POST', '/api/candidature/apply', port, payload, 201,
                "body.candidature_id && body.email_status == 'queued'",
                synchronize=users if registration_arrival == 'burst' else 0)
    else:
        setup, _ = node(tree, 'JSR223Sampler', 'Candidat affecte au test', 'TestBeanGUI')
        prop(setup, 'scriptLanguage', 'groovy')
        prop(setup, 'script', f"def i = ctx.getThreadNum() + 1 + {offset}\n"
             "vars.put('email', String.format('loadtest+%05d@load.odc.local', i))\n"
             "vars.put('phone', String.format('77%07d', i))\n"
             "vars.put('name', String.format('Load Candidate %05d', i))")
        identity = {'email': '${email}', 'phone': '${phone}'}
        base = '/api/admin/tests/' + test_id
        measured_tree = tree
        if mode in {'connection', 'combined'}:
            transaction, measured_tree = node(tree, 'TransactionController',
                PEAK_PROFILES[mode]['target'], 'TransactionControllerGui')
            # Emit child HTTP samples plus a separate complete-journey sample.
            prop(transaction, 'TransactionController.parent', 'false', 'boolProp')
            prop(transaction, 'TransactionController.includeTimers', 'false', 'boolProp')
        if mode != 'submission':
            sampler(measured_tree, 'Metadonnees', 'GET', base + '/public', port, check='body.success == true')
            sampler(measured_tree, 'Acces', 'POST', base + '/verify-access', port, identity,
                    check="body.authorized == true && body.candidate?.email == vars.get('email')",
                    synchronize=users if mode == 'online' else 0)
            sampler(measured_tree, 'Questions', 'POST', base + '/content', port, identity,
                    check=f"body.success == true && body.data.id == '{test_id}' && body.data.questions.size() == 3")
        if mode == 'online':
            timer, _ = node(tree, 'ConstantTimer', 'Pause entre requetes (1 seconde)', 'ConstantTimerGui')
            prop(timer, 'ConstantTimer.delay', 1000)
        draft = {**identity, 'name': '${name}', 'answers': ANSWERS,
                 'lastQuestion': 2, 'remainingTime': 3500}
        if mode in {'online', 'combined'}:
            sampler(measured_tree, 'Brouillon', 'PUT', base + '/session-draft', port, draft,
                    check='body.success == true')
        if mode != 'connection':
            sampler(measured_tree, 'Soumission', 'POST', '/api/admin/tests/results', port,
                    {'testId': test_id, 'candidate': {**identity, 'name': '${name}'}, 'answers': draft['answers']},
                    201, f"body.success == true && body.data.id && body.data.testId == '{test_id}' && body.data.candidate?.email == vars.get('email') && body.data.answers == new groovy.json.JsonSlurper().parseText('{json.dumps(ANSWERS)}')")
    ET.indent(root)
    ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)


def read_results(path):
    groups = {}
    with path.open(newline='', encoding='utf-8-sig') as source:
        for row in csv.DictReader(source):
            if not all(row.get(key) for key in ('label', 'elapsed', 'responseCode', 'success')):
                continue  # The generator may still be writing the last row.
            if row['label'] in {'Identite synthetique', 'Candidat affecte au test',
                                'Preparer sauvegarde', 'Preparer soumission'}:
                continue
            groups.setdefault(row['label'], []).append((float(row['elapsed']), row['responseCode'], row['success'] == 'true'))
    return {name: summarize(values) for name, values in groups.items()}


def first_failed_sample(path):
    if not path.is_file():
        return None
    with path.open(newline='', encoding='utf-8-sig') as source:
        for row in csv.DictReader(source):
            if row.get('success') == 'false':
                return {key: row.get(key) for key in ('label', 'responseCode', 'failureMessage')}
    return None


class LiveSamples:
    """Read only newly appended CSV records during long tests, including quoted
    multiline failures and records split across flushes."""
    def __init__(self):
        self.offset = 0
        self.buffer = ''
        self.decoder = codecs.getincrementaldecoder('utf-8-sig')()
        self.headers = None
        self.counts = Counter()
        self.failure = None

    def poll(self, path):
        if not path.is_file():
            return self.failure
        with path.open('rb') as source:
            source.seek(self.offset)
            self.buffer += self.decoder.decode(source.read(), final=False)
            self.offset = source.tell()
        ready = self.buffer.rfind('\n') + 1
        stream = io.StringIO(self.buffer[:ready], newline='')
        reader = csv.reader(stream, strict=True)
        consumed = 0
        while True:
            try:
                values = next(reader)
            except (StopIteration, csv.Error):
                break
            consumed = stream.tell()
            if self.headers is None:
                self.headers = values
                continue
            if len(values) != len(self.headers):
                continue
            row = dict(zip(self.headers, values))
            self.counts[row.get('label', '')] += 1
            if row.get('success') == 'false' and self.failure is None:
                self.failure = {key: row.get(key) for key in ('label', 'responseCode', 'failureMessage')}
        self.buffer = self.buffer[consumed:]
        return self.failure


def build_schedule(levels, scenario):
    modes = ['registration', 'online'] if scenario == 'both' else [scenario]
    schedule = [(mode, 1, 0) for mode in modes]
    offset = 1
    for users in levels:
        schedule.extend((mode, users, offset if mode != 'registration' else 0) for mode in modes)
        offset += users
    return schedule


def candidate_emails(users, offset):
    return {f'loadtest+{index:05d}@load.odc.local' for index in range(offset + 1, offset + users + 1)}


def registration_integrity(db, run_id, users):
    emails = {f'load-{run_id}-{i}@example.invalid' for i in range(1, users + 1)}
    identities = {f'LOAD-{run_id}-{i}' for i in range(1, users + 1)}
    rows = list(db.candidatures_load.find({'email': {'$in': sorted(emails)}},
                {'email': 1, 'cni_or_passport_number': 1}))
    observed = [row['email'] for row in rows]
    observed_identities = [row.get('cni_or_passport_number') for row in rows]
    return {'expected_stage_candidates': users, 'stored_stage_candidates': len(rows),
            'unique_stage_emails': len(set(observed)), 'unique_stage_identities': len(set(observed_identities)),
            'valid': len(rows) == users and set(observed) == emails and set(observed_identities) == identities}


def access_integrity(path, expected):
    observed = []
    with path.open(newline='', encoding='utf-8-sig') as source:
        for row in csv.DictReader(source):
            if row.get('label') == 'Acces' and row.get('success') == 'true':
                observed.append(row.get('email'))
    return {'expected_unique_accesses': len(expected), 'observed_unique_accesses': len(set(observed)),
            'valid': len(observed) == len(expected) and set(observed) == expected}


def result_integrity(db, test_id, expected, stage_expected=None):
    rows = list(db.test_results.find({'testId': test_id}))
    observed = [row.get('candidate', {}).get('email') for row in rows]
    sessions = list(db.test_sessions.find({'testId': test_id, 'status': 'submitted'}))
    submitted = [row.get('candidateEmail') for row in sessions]
    stage_expected = expected if stage_expected is None else stage_expected
    stage_rows = [email for email in observed if email in stage_expected]
    return {'expected_unique_submissions': len(expected), 'stored_results': len(rows),
            'unique_result_candidates': len(set(observed)), 'submitted_sessions': len(sessions),
            'expected_stage_submissions': len(stage_expected), 'stored_stage_submissions': len(stage_rows),
            'unique_stage_submissions': len(set(stage_rows)),
            'valid': (len(rows) == len(expected) and set(observed) == expected
                      and len(submitted) == len(expected) and set(submitted) == expected
                      and all(row.get('answers') == ANSWERS for row in rows)
                      and all(row.get('answers') == ANSWERS for row in sessions))}


def start_isolated_api(env, directory, logs):
    api = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--serve'],
                           cwd=directory, env=env, stdout=logs, stderr=logs)
    try:
        with requests.Session() as session:
            session.trust_env = False
            for attempt in range(60):
                if api.poll() is not None:
                    raise RuntimeError('API jetable arretee au demarrage; voir processes.log')
                try:
                    body = session.get(f"http://127.0.0.1:{env['PORT']}/health", timeout=2).json()
                    if body.get('status') == 'healthy' and body.get('version') == 'load-' + env['ODC_LOAD_RUN_ID']:
                        return api
                except (requests.RequestException, ValueError):
                    pass
                if attempt == 59:
                    raise RuntimeError('API jetable indisponible')
                time.sleep(.5)
    except BaseException:
        stop_process(api)
        raise


def verify_exam_metadata(env, test_id, start):
    with requests.Session() as session:
        session.trust_env = False
        response = session.get(f"http://127.0.0.1:{env['PORT']}/api/admin/tests/{test_id}/public", timeout=5)
        body = response.json()
    metadata = body.get('data') or {}
    if (response.status_code != 200 or body.get('success') is not True
            or metadata.get('duration') != 15
            or metadata.get('scheduledDate') != start.strftime('%Y-%m-%d')
            or metadata.get('scheduledTime') != start.strftime('%H:%M')):
        raise RuntimeError('Metadonnees du creneau 15 minutes non confirmees; charge annulee')
    return {'duration_minutes': metadata['duration'], 'scheduledDate': metadata['scheduledDate'],
            'scheduledTime': metadata['scheduledTime'], 'api_restarted_after_schedule': True}


def run(args):
    run_id = uuid4().hex
    output = args.output.resolve() / run_id
    output.mkdir(parents=True, exist_ok=False)
    report = {'run_id': run_id, 'scenario': args.scenario, 'api_threads': args.threads,
              'ramp_seconds': args.ramp, 'max_p95_ms': args.max_p95_ms,
              'scope': 'API + MongoDB jetables, sans IIS/TLS/frontend, generateur sur le meme serveur',
              'stages': [], 'email_worker_started': False, 'cleanup_complete': False}
    if args.scenario in {'registration', 'both'}:
        report['registration_arrival'] = args.registration_arrival
    if args.preload_candidates or args.endurance_seconds:
        report['campaign'] = {'preloaded_candidates': args.preload_candidates,
            'endurance_seconds': args.endurance_seconds, 'endurance_rate_per_second': args.endurance_rate,
            'endurance_new_candidates': args.endurance_seconds * args.endurance_rate}
    if args.scenario == 'exam15':
        report['exam'] = {'seconds': args.exam_seconds, 'answer_change_every_seconds': args.answer_every,
                         'forced_save_every_seconds': args.forced_save_every,
                         'change_debounce_ms': 1200, 'submission_wave_seconds': args.submit_seconds,
                         'draft_cutoff_seconds_before_close': args.draft_cutoff_seconds,
                         'connection_p95_target_ms': 3000, 'draft_p95_target_ms': 3000,
                         'submission_p95_target_ms': args.max_p95_ms,
                         'same_machine_generator': True}
    mongo = api = jmeter = client = None
    stop = threading.Event()
    monitor = None
    failed = False
    try:
        with tempfile.TemporaryDirectory(prefix='odc-jmeter-') as scratch:
            directory = Path(scratch)
            with (output / 'processes.log').open('wb') as logs:
                try:
                    mongo_port, port = free_port(), free_port()
                    while mongo_port == port:
                        port = free_port()
                    env = child_environment(run_id, mongo_port, port, directory, args.threads, 50)
                    env.update({'EMAIL_PROVIDER': 'smtp', 'ODC_JMETER_MONGO_PORT': str(mongo_port)})
                    data = directory / 'mongo'
                    data.mkdir()
                    mongo = subprocess.Popen([str(args.mongod.resolve()), '--bind_ip', '127.0.0.1',
                        '--port', str(mongo_port), '--dbpath', str(data), '--wiredTigerCacheSizeGB', '0.25'],
                        stdout=logs, stderr=logs, env=env)
                    client = MongoClient(env['MONGO_URI'], serverSelectionTimeoutMS=500)
                    for attempt in range(60):
                        if mongo.poll() is not None:
                            raise RuntimeError('MongoDB jetable arrete au demarrage')
                        try:
                            client.admin.command('ping')
                            break
                        except Exception:
                            if attempt == 59:
                                raise
                            time.sleep(.5)
                    db = client[env['MONGO_DBNAME']]
                    now = datetime.now(timezone.utc)
                    db.candidature_campaigns.insert_one({'title': '[LOAD] JMeter', 'formation': 'all',
                        'status': 'published', 'start_at': now - timedelta(days=1), 'end_at': now + timedelta(days=1)})
                    if args.preload_candidates:
                        print(f'Preparation: {args.preload_candidates} candidatures fictives, sans emails', flush=True)
                        subprocess.run([sys.executable, str(Path(__file__).resolve()), '--seed-registrations',
                            str(args.preload_candidates), str(output)], cwd=directory, env=env,
                            stdout=logs, stderr=logs, check=True, timeout=600)
                        if (db.candidatures_load.count_documents({'first_name': 'PRELOAD'}) != args.preload_candidates
                                or db.email_jobs.count_documents({}) != 0):
                            raise RuntimeError('Prechargement incoherent ou presence inattendue d emails')
                        print(f'Prechargement confirme: {args.preload_candidates} candidatures; 0 email en file', flush=True)
                    # Registration-only measurements do not create online exams
                    # or pre-seed unrelated candidates. Other scenarios need them.
                    seed_count = 0 if args.scenario == 'registration' else sum(args.levels) + 1
                    test_id = ''
                    if seed_count:
                        subprocess.run([sys.executable, str(Path(__file__).resolve()), '--seed',
                            str(seed_count), str(output)], cwd=directory, env=env,
                            stdout=logs, stderr=logs, check=True, timeout=300)
                        test_id = json.loads((output / 'test.json').read_text(encoding='utf-8'))['id']
                    if args.scenario == 'submission':
                        # Prepare already-started sessions without adding access,
                        # content or draft HTTP requests to the submission peak.
                        with (output / 'candidates.csv').open(newline='', encoding='utf-8') as source:
                            db.test_sessions.insert_many([{
                                'testId': test_id, 'candidateEmail': row['email'],
                                'candidatePhone': row['phone'], 'candidateName': row['name'],
                                'answers': ANSWERS, 'lastQuestion': 2, 'remainingTime': 3500,
                                'status': 'in_progress', 'startedAt': now, 'lastSeenAt': now,
                            } for row in csv.DictReader(source)])
                    api = start_isolated_api(env, directory, logs)
                    measurements = ResourceSamples()
                    processes = {'api': api, 'mongo': mongo, 'jmeter': None}
                    monitor = threading.Thread(target=sample_resources,
                        args=(processes, stop, measurements), daemon=True)
                    monitor.start()
                    # One functional check per journey precedes the 500-user stage.
                    schedule = build_schedule(args.levels, args.scenario)
                    if args.endurance_seconds:
                        schedule.append(('registration_endurance', args.endurance_seconds * args.endurance_rate, 0))
                    expected_candidates = seed_count + args.preload_candidates
                    expected_emails = 0
                    expected_results = 0
                    expected_result_emails = set()
                    expected_exam_answers = {}
                    for index, (mode, users, offset) in enumerate(schedule):
                        prefix = output / f'{index:02d}-{mode}-{users}'
                        plan, results = prefix.with_suffix('.jmx'), prefix.with_suffix('.jtl')
                        stage_exam = None
                        stage_run_id = uuid4().hex
                        registration_phase = mode in {'registration', 'registration_endurance'}
                        if mode == 'exam15':
                            from exam_scenario import exam_clock, make_exam_plan
                            seconds = 6 if users == 1 else args.exam_seconds
                            entry = 0 if users == 1 else args.ramp
                            change = 1 if users == 1 else args.answer_every
                            cutoff = min(args.draft_cutoff_seconds, max(1, seconds // 4)) if users == 1 else args.draft_cutoff_seconds
                            start, end = exam_clock(seconds)
                            if users > 1 and args.exam_seconds == 900:
                                updated_test = db.tests.update_one({'_id': ObjectId(test_id)}, {'$set': {
                                    'scheduledDate': start.strftime('%Y-%m-%d'),
                                    'scheduledTime': start.strftime('%H:%M'), 'duration': 15}})
                                updated_group = db.test_groups.update_one({'test_id': test_id}, {'$set': {'duration': 15, 'test_date': start}})
                                if updated_test.matched_count != 1 or updated_group.matched_count != 1:
                                    raise RuntimeError('Impossible de configurer le test et son groupe pour 15 minutes')
                                # The functional pilot cached the old 60-minute
                                # fixture for five minutes. Restart only our own
                                # disposable API after changing its test schedule.
                                stop_process(api)
                                api = start_isolated_api(env, directory, logs)
                                processes['api'] = api
                                metadata_check = verify_exam_metadata(env, test_id, start)
                                print('Creneau confirme par API temporaire: 15 minutes; cache renouvele', flush=True)
                            make_exam_plan(plan, port, users, entry, test_id, offset,
                                int(start.timestamp() * 1000), seconds, change,
                                args.forced_save_every, 0 if users == 1 else args.submit_seconds, cutoff)
                            stage_exam = {'seconds': seconds, 'start': start.isoformat(), 'end': end.isoformat(),
                                          'start_epoch': start.timestamp(), 'minimum_saves':
                                          max(0, (seconds - entry - cutoff - 1) // args.forced_save_every),
                                          'draft_cutoff_seconds_before_close': cutoff}
                            if users > 1 and args.exam_seconds == 900:
                                stage_exam['metadata_preflight'] = metadata_check
                        elif mode == 'registration_endurance':
                            make_endurance_plan(plan, port, users, args.threads, args.endurance_rate,
                                                stage_run_id, int((time.time() + 10) * 1000))
                        else:
                            make_plan(plan, port, users, 1 if users == 1 else args.ramp,
                                      mode, stage_run_id, test_id, offset, args.registration_arrival)
                        start_sample = len(measurements)
                        measurements.phase = f'{mode}-{users}'
                        command = [str(args.jmeter.resolve()), '-n', '-t', str(plan), '-l', str(results),
                                   '-j', str(prefix.with_suffix('.log')), '-e', '-o', str(prefix) + '-html',
                                   '-Jjmeter.save.saveservice.output_format=csv',
                                   '-Jjmeter.save.saveservice.autoflush=true',
                                   '-Jsample_variables=email,expected_answers']
                        # Launch the same JMeter JAR directly on Windows to avoid
                        # cmd.exe quoting problems with paths containing spaces.
                        if os.name == 'nt' and args.jmeter.suffix.lower() in {'.bat', '.cmd'}:
                            java = (str(Path(os.environ['JAVA_HOME']) / 'bin' / 'java.exe')
                                    if os.environ.get('JAVA_HOME') else shutil.which('java'))
                            if not java:
                                raise RuntimeError('Java introuvable: configurer JAVA_HOME ou PATH')
                            command = [java, '-Djava.awt.headless=true', '-Xms256m', '-Xmx1g',
                                       '-jar', str(args.jmeter.resolve().parent / 'ApacheJMeter.jar'),
                                       *command[1:]]
                        if mode == 'registration_endurance':
                            print(f'Endurance: {users} nouvelles candidatures, {args.endurance_rate}/s pendant {args.endurance_seconds}s, {min(users, args.threads)} clients', flush=True)
                        else:
                            print(f'{mode}: {users} utilisateurs', flush=True)
                        # Java needs JAVA_HOME when it is not on PATH. This does not
                        # pass application/email/production settings to the generator.
                        jmeter_env = dict(env)
                        if os.environ.get('JAVA_HOME'):
                            jmeter_env['JAVA_HOME'] = os.environ['JAVA_HOME']
                        jmeter = subprocess.Popen(command, cwd=directory, env=jmeter_env, stdout=logs, stderr=logs)
                        processes['jmeter'] = jmeter
                        started = time.monotonic()
                        deadline = time.monotonic() + args.timeout
                        live = LiveSamples()
                        last_progress = time.monotonic()
                        while jmeter.poll() is None:
                            failure = live.poll(results)
                            if failure:
                                report['failed_sample'] = failure
                                raise RuntimeError('Echec JMeter: arret immediat apres erreur de requete ou assertion')
                            if time.monotonic() >= deadline:
                                raise RuntimeError('Delai maximal JMeter depasse')
                            readings = measurements[start_sample:]
                            if any(s.get('system_cpu_percent', 0) > args.max_cpu for s in readings[-4:]) and len(readings) >= 4 and all(s.get('system_cpu_percent', 0) > args.max_cpu for s in readings[-4:]):
                                raise RuntimeError('CPU global au-dessus du seuil pendant une seconde; charge arretee')
                            if mode == 'exam15' and time.monotonic() - last_progress >= 30:
                                remaining = max(0, int(stage_exam['start_epoch'] + stage_exam['seconds'] - time.time()))
                                print(f"exam15: fin epreuve dans {remaining}s; acces={live.counts['Acces']}; brouillons={live.counts['Brouillon periodique']}; soumissions={live.counts['Soumission']}", flush=True)
                                last_progress = time.monotonic()
                            if mode == 'registration_endurance' and time.monotonic() - last_progress >= 30:
                                print(f"Endurance: {live.counts['Inscription']}/{users} inscriptions terminees; ecoule={int(time.monotonic() - started)}s", flush=True)
                                last_progress = time.monotonic()
                            time.sleep(.25)
                        endpoints = read_results(results)
                        names = ({'Metadonnees', 'Acces', 'Questions', 'Connexion', 'Lecture brouillon', 'Brouillon initial',
                                  'Brouillon periodique', 'Soumission', 'Statut final'} if mode == 'exam15' else
                                 PEAK_PROFILES[mode]['labels'] if mode in PEAK_PROFILES else
                                 {'Campagne', 'Unicite', 'Inscription'} if registration_phase else
                                 {'Metadonnees', 'Acces', 'Questions', 'Brouillon', 'Soumission'})
                        if registration_phase:
                            expected_candidates += users
                            expected_emails += users
                        elif mode != 'connection':
                            expected_results += users
                            expected_result_emails.update(candidate_emails(users, offset))
                        integrity = (db.candidatures_load.count_documents({}) == expected_candidates
                                     and db.test_results.count_documents({}) == expected_results
                                     and db.email_jobs.count_documents({}) == expected_emails
                                     and db.email_jobs.count_documents({'status': 'pending', 'attempts': 0}) == expected_emails)
                        stage = {'mode': mode, 'users': min(users, args.threads) if mode == 'registration_endurance' else users,
                                 'journeys': users, 'endpoints': endpoints, 'integrity_ok': integrity,
                                 'queued_test_emails': db.email_jobs.count_documents({}), 'passed': False}
                        stage['wall_duration_seconds'] = round(time.monotonic() - started, 3)
                        if registration_phase:
                            stage['data_checks'] = registration_integrity(db, stage_run_id, users)
                            stage['integrity_ok'] = integrity and stage['data_checks']['valid']
                            stage['arrival_mode'] = 'fixed_rate' if mode == 'registration_endurance' else args.registration_arrival
                            stage['arrival_observation'] = arrival_observation(results)
                            stage['preloaded_candidates_intact'] = db.candidatures_load.count_documents({'first_name': 'PRELOAD'}) == args.preload_candidates
                            stage['integrity_ok'] = stage['integrity_ok'] and stage['preloaded_candidates_intact']
                        if mode in PEAK_PROFILES:
                            stage['data_checks'] = result_integrity(db, test_id, expected_result_emails,
                                candidate_emails(users, offset) if mode != 'connection' else set())
                            if mode != 'submission':
                                stage['access_checks'] = access_integrity(results, candidate_emails(users, offset))
                            stage['integrity_ok'] = (integrity and stage['data_checks']['valid']
                                and stage.get('access_checks', {'valid': True})['valid'])
                        if mode == 'exam15':
                            from exam_scenario import exam_checks
                            stage['data_checks'], expected_exam_answers = exam_checks(db, test_id, results,
                                expected_result_emails, candidate_emails(users, offset), expected_exam_answers,
                                stage_exam['minimum_saves'])
                            stage['access_checks'] = access_integrity(results, candidate_emails(users, offset))
                            stage['integrity_ok'] = integrity and stage['data_checks']['valid'] and stage['access_checks']['valid']
                            stage['exam_timing'] = stage_exam
                            if 'Brouillon periodique' not in endpoints and stage_exam['minimum_saves'] == 0:
                                names = names - {'Brouillon periodique'}
                        readings = measurements[start_sample:]
                        stage['peak_resources'] = peak_resources(readings)
                        latency_labels = ({'Soumission'} if mode == 'exam15' else
                                          {PEAK_PROFILES[mode]['target']} if mode in PEAK_PROFILES else names)
                        stage['latency_target_ms'] = args.max_p95_ms
                        stage['latency_labels'] = sorted(latency_labels)
                        stage['passed'] = (jmeter.returncode == 0 and set(endpoints) == names and stage['integrity_ok']
                            and all((s['requests'] == users or (mode == 'exam15' and label == 'Brouillon periodique'))
                                    and s['errors'] == 0 for label, s in endpoints.items())
                            and all(endpoints[label]['p95_ms'] <= args.max_p95_ms for label in latency_labels))
                        if mode == 'exam15':
                            stage['latency_labels'] = ['Connexion', 'Brouillon initial', 'Brouillon periodique', 'Soumission']
                            stage['passed'] = (stage['passed'] and endpoints['Connexion']['p95_ms'] <= 3000
                                and endpoints['Brouillon initial']['p95_ms'] <= 3000
                                and endpoints.get('Brouillon periodique', {'p95_ms': 0})['p95_ms'] <= 3000)
                        if mode == 'registration_endurance':
                            stage['five_minute_buckets'] = time_buckets(results)
                            wanted_span = (users - 1) / args.endurance_rate
                            stage['requested_arrival_rate_per_second'] = args.endurance_rate
                            stage['arrival_schedule_ok'] = (stage['arrival_observation']['observed_arrivals'] == users
                                and abs(stage['arrival_observation']['first_to_last_arrival_seconds'] - wanted_span)
                                <= max(2, wanted_span * .05))
                            stage['passed'] = stage['passed'] and stage['arrival_schedule_ok'] and all(
                                row['errors'] == 0 and row['p95_ms'] <= args.max_p95_ms
                                for bucket in stage['five_minute_buckets'] for row in bucket['endpoints'].values())
                        report['stages'].append(stage)
                        console_stage = {key: value for key, value in stage.items() if key != 'five_minute_buckets'}
                        if 'five_minute_buckets' in stage:
                            console_stage['five_minute_buckets_count'] = len(stage['five_minute_buckets'])
                        print(json.dumps(console_stage), flush=True)
                        if not stage['passed']:
                            raise RuntimeError('Seuil, erreurs ou integrite: aucun palier superieur lance')
                        if users > 1:
                            time.sleep(2)
                    report['passed'] = True
                finally:
                    stop.set()
                    if monitor:
                        monitor.join(timeout=5)
                    stop_process(jmeter)
                    stop_process(api)
                    if client:
                        client.close()
                    stop_process(mongo)
                    if 'measurements' in locals():
                        measurements.write_csv(output / 'resources.csv')
            report['cleanup_complete'] = True
    except KeyboardInterrupt:
        failed = True
        report.update({'passed': False, 'error': 'Interruption manuelle; aucun palier suivant lance'})
    except Exception as error:
        failed = True
        report.update({'passed': False, 'error': str(error)})
    finally:
        report['cleanup_complete'] = (all(process is None or process.poll() is not None
                                         for process in (jmeter, api, mongo))
                                      and ('directory' not in locals() or not directory.exists()))
        (output / 'summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(f'Rapports: {output}', flush=True)
    return 1 if failed else 0


def main():
    if sys.argv[1:] == ['--serve']:
        isolated_child()
        from run import run_server
        run_server()
        return 0
    if len(sys.argv) == 4 and sys.argv[1] == '--seed':
        child_seed(int(sys.argv[2]), Path(sys.argv[3]))
        return 0
    if len(sys.argv) == 4 and sys.argv[1] == '--seed-registrations':
        from registration_campaign import preload_candidates
        preload_candidates(int(sys.argv[2]), Path(sys.argv[3]))
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mongod', type=Path, required=True)
    parser.add_argument('--jmeter', type=Path, required=True)
    parser.add_argument('--levels', default='500', help='Paliers croissants; defaut 500 uniquement')
    parser.add_argument('--scenario', choices=['both', 'registration', 'online', 'exam15', *PEAK_PROFILES], default='both',
                        help='Parcours a mesurer; online ne lance aucune requete d inscription')
    parser.add_argument('--ramp', type=int, help='Secondes de montee; 10 soumission, 60 autres')
    parser.add_argument('--threads', type=int, default=8)
    parser.add_argument('--registration-arrival', choices=['burst', 'progressive'], default='burst',
                        help='burst: soumissions synchronisees; progressive: arrivees etalees sur ramp')
    parser.add_argument('--preload-candidates', type=int, default=0, help='Volume fictif initial, registration seulement, maximum 75000')
    parser.add_argument('--endurance-seconds', type=int, default=0, help='Phase reguliere apres le pic, registration seulement')
    parser.add_argument('--endurance-rate', type=int, default=1, help='Nouvelles candidatures par seconde pendant endurance')
    parser.add_argument('--max-p95-ms', type=float, help='Seuil; connexion 3000, soumission/combine 5000, historique 1500')
    parser.add_argument('--max-cpu', type=float, default=85)
    parser.add_argument('--timeout', type=int, help='Limite par execution; 1800 s exam15, 600 autres')
    parser.add_argument('--exam-seconds', type=int, default=900, help='900 en reel; reduction pour validation du lanceur')
    parser.add_argument('--answer-every', type=int, default=30, help='Hypothese: changement de reponse toutes les 30 s')
    parser.add_argument('--forced-save-every', type=int, default=90, help='Frequence forcee du frontend: 90 s')
    parser.add_argument('--submit-seconds', type=int, default=10)
    parser.add_argument('--draft-cutoff-seconds', type=int, default=10,
                        help='Fin des nouveaux brouillons avant cloture; defaut 10 s (timeout 8 s + marge 2 s)')
    parser.add_argument('--output', type=Path, default=ROOT / 'load_tests' / 'reports' / 'jmeter')
    args = parser.parse_args()
    profile = PEAK_PROFILES.get(args.scenario, {'ramp': 60, 'p95': 5000 if args.scenario == 'exam15' else 1500})
    if args.ramp is None:
        args.ramp = profile['ramp']
    if args.max_p95_ms is None:
        args.max_p95_ms = profile['p95']
    if args.timeout is None:
        args.timeout = 1800 if args.scenario == 'exam15' else max(600, args.endurance_seconds + 300)
    try:
        args.levels = [int(value) for value in args.levels.split(',')]
    except ValueError:
        parser.error('--levels doit contenir des entiers separes par des virgules')
    max_users = 3000 if args.scenario == 'registration' else 2000
    if (not args.levels or args.levels != sorted(set(args.levels))
            or not 1 <= min(args.levels) <= max(args.levels) <= max_users
            or sum(args.levels) > 10000 or not 1 <= args.threads <= 64
            or args.ramp < 1 or args.timeout < 1 or args.max_p95_ms <= 0
            or not 6 <= args.exam_seconds <= 900 or args.answer_every < 1
            or args.forced_save_every < 1 or not 1 <= args.submit_seconds <= 60
            or not 1 <= args.draft_cutoff_seconds <= 60
            or not 0 <= args.preload_candidates <= 75000
            or not 0 <= args.endurance_seconds <= 7200 or not 1 <= args.endurance_rate <= 10
            or args.endurance_seconds * args.endurance_rate + sum(args.levels) > 10000
            or not 1 <= args.max_cpu <= 100):
        parser.error(f'Parametres hors limites: paliers 1..{max_users}, somme <=10000, CPU 1..100, threads 1..64')
    if (args.preload_candidates or args.endurance_seconds) and args.scenario != 'registration':
        parser.error('Prechargement et endurance reserves au scenario registration')
    if args.endurance_seconds and args.timeout < args.endurance_seconds + 120:
        parser.error('Timeout endurance trop court: au moins duree +120 s')
    if args.scenario == 'exam15' and (args.ramp >= args.exam_seconds
            or args.ramp + args.draft_cutoff_seconds >= args.exam_seconds
            or args.timeout < args.exam_seconds + args.submit_seconds + 120):
        parser.error('exam15: montee inferieure a l epreuve; timeout >= epreuve + soumissions +120 s')
    if not args.mongod.is_file() or not args.jmeter.is_file():
        parser.error('Fournir les chemins de mongod et JMeter deja installes')
    return run(args)


if __name__ == '__main__':
    raise SystemExit(main())
