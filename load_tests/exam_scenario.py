"""A common 15-minute exam window, repeated drafts and a final submission wave."""
from collections import Counter
import csv
from datetime import datetime, timedelta
import json
import xml.etree.ElementTree as ET


def exam_clock(seconds=900, now=None, preparation_seconds=60):
    now = datetime.now() if now is None else now
    if seconds == 900:
        earliest = now + timedelta(seconds=preparation_seconds)
        start = earliest.replace(second=0, microsecond=0)
        if start < earliest:
            start += timedelta(minutes=1)
    else:
        # Accelerated validation only, not the production-length workload.
        start = now + timedelta(seconds=2)
    return start, start + timedelta(seconds=seconds)


def make_exam_plan(path, port, users, entry_seconds, test_id, offset, start_ms,
                   exam_seconds=900, answer_every=30, forced_every=90, submit_seconds=10,
                   draft_cutoff_seconds=10):
    from jmeter_isolated import ANSWERS, node, prop, sampler
    root = ET.Element('jmeterTestPlan', version='1.2', properties='5.0', jmeter='5.6.3')
    top = ET.SubElement(root, 'hashTree')
    plan, tree = node(top, 'TestPlan', 'ODC - epreuve commune 15 minutes', 'TestPlanGui')
    ET.SubElement(ET.SubElement(plan, 'elementProp', name='TestPlan.user_defined_variables',
        elementType='Arguments'), 'collectionProp', name='Arguments.arguments')
    group, tree = node(tree, 'ThreadGroup', 'exam15', 'ThreadGroupGui')
    prop(group, 'ThreadGroup.num_threads', users)
    # Per-user gates below generate the 60-second entry wave at a known clock
    # time, matching the test's configured opening and closing dates.
    prop(group, 'ThreadGroup.ramp_time', 1)
    prop(group, 'ThreadGroup.on_sample_error', 'stopthread')
    control = ET.SubElement(group, 'elementProp', name='ThreadGroup.main_controller',
        elementType='LoopController', guiclass='LoopControlPanel', testclass='LoopController', enabled='true')
    prop(control, 'LoopController.loops', 1)
    prop(control, 'LoopController.continue_forever', 'false', 'boolProp')
    headers, _ = node(tree, 'HeaderManager', 'JSON', 'HeaderPanel')
    header = ET.SubElement(ET.SubElement(headers, 'collectionProp', name='HeaderManager.headers'),
        'elementProp', name='', elementType='Header')
    prop(header, 'Header.name', 'Content-Type')
    prop(header, 'Header.value', 'application/json')

    def script_node(target, tag, name, code):
        element, children = node(target, tag, name, 'TestBeanGUI')
        prop(element, 'scriptLanguage', 'groovy')
        prop(element, 'cacheKey', 'true')
        prop(element, 'script', code)
        return children

    end_ms = start_ms + exam_seconds * 1000
    cutoff_ms = end_ms - draft_cutoff_seconds * 1000
    answers_json = json.dumps(ANSWERS)
    setup = f'''
def slot = ctx.getThreadNum()
def i = slot + 1 + {offset}
def entry = {start_ms}L + (long)(slot * {entry_seconds * 1000}d / Math.max(1, {users - 1}))
vars.put('email', String.format('loadtest+%05d@load.odc.local', i))
vars.put('email_encoded', java.net.URLEncoder.encode(vars.get('email'), 'UTF-8'))
vars.put('phone', String.format('77%07d', i))
vars.put('name', String.format('Load Candidate %05d', i))
vars.put('entry_at', entry.toString())
vars.put('submit_at', ({end_ms}L + (long)(slot * {submit_seconds * 1000}d / Math.max(1, {users - 1}))).toString())
vars.put('next_change', (entry + {answer_every * 1000 + 1200}L).toString())
vars.put('next_forced', (entry + {forced_every * 1000}L).toString())
vars.put('revision', '0')
vars.put('more_saves', 'true')
vars.put('expected_answers', '{answers_json}')
def identity = [email: vars.get('email'), phone: vars.get('phone'), name: vars.get('name')]
vars.put('draft_json', groovy.json.JsonOutput.toJson(identity + [answers: new groovy.json.JsonSlurper().parseText(vars.get('expected_answers')), lastQuestion: 0, remainingTime: Math.max(0L, (({end_ms}L - entry) / 1000L).longValue())]))
'''
    script_node(tree, 'JSR223Sampler', 'Candidat affecte au test', setup)
    transaction, connection_tree = node(tree, 'TransactionController', 'Connexion', 'TransactionControllerGui')
    prop(transaction, 'TransactionController.parent', 'false', 'boolProp')
    prop(transaction, 'TransactionController.includeTimers', 'false', 'boolProp')
    base = '/api/admin/tests/' + test_id
    # Timer is local to this sampler, so waiting for entry is excluded from
    # connection latency and does not delay the subsequent requests again.
    metadata_check = 'body.success == true'
    if exam_seconds == 900:
        metadata_check += ' && body.data.duration == 15'
    children = sampler(connection_tree, 'Metadonnees', 'GET', base + '/public', port,
                       check=metadata_check, timeout_ms=15000)
    script_node(children, 'JSR223Timer', 'Horaire entree',
                "return Math.max(0L, vars.get('entry_at').toLong() - System.currentTimeMillis())")
    identity = {'email': '${email}', 'phone': '${phone}'}
    sampler(connection_tree, 'Acces', 'POST', base + '/verify-access', port, identity,
        check="body.authorized == true && body.candidate?.email == vars.get('email')", timeout_ms=15000)
    sampler(connection_tree, 'Questions', 'POST', base + '/content', port, identity,
        check=f"body.success == true && body.data.id == '{test_id}' && body.data.questions.size() == 3")
    sampler(tree, 'Lecture brouillon', 'GET', base + '/session-draft?email=${email_encoded}&phone=${phone}', port,
            check='body.success == true && body.data == null', timeout_ms=8000)
    draft_check = "body.success == true && body.data.answers == new groovy.json.JsonSlurper().parseText(vars.get('expected_answers'))"
    sampler(tree, 'Brouillon initial', 'PUT', base + '/session-draft', port, '${draft_json}', check=draft_check, timeout_ms=8000)

    loop, loop_tree = node(tree, 'WhileController', 'Sauvegardes pendant epreuve', 'WhileControllerGui')
    prop(loop, 'WhileController.condition', "${__groovy(vars.get('more_saves') != 'false')}")
    prepare = f'''
def now = System.currentTimeMillis()
def change = vars.get('next_change').toLong()
def forced = vars.get('next_forced').toLong()
def due = Math.min(change, forced)
// Leave the frontend's 8-second draft timeout plus 2 seconds of scheduling
// margin before the server closes draft access. Do not hide rejected writes.
if (due >= {cutoff_ms}L || now >= {cutoff_ms}L) {{
    vars.put('more_saves', 'false'); vars.put('save_due', 'false'); return
}}
// A forced save already captures a change whose debounce is still pending.
if (forced <= change) {{
    if (change <= forced + 1500L) change += {answer_every * 1000}L
    forced += {forced_every * 1000}L
}} else {{ change += {answer_every * 1000}L }}
// Do not replay missed timers in bursts when a previous request was slow.
while (change <= now) change += {answer_every * 1000}L
while (forced <= now) forced += {forced_every * 1000}L
vars.put('next_change', change.toString()); vars.put('next_forced', forced.toString())
vars.put('save_at', Math.max(due, now).toString()); vars.put('save_due', 'true')
def revision = vars.get('revision').toInteger() + 1
vars.put('revision', revision.toString())
def answers = new groovy.json.JsonSlurper().parseText('{answers_json}')
answers['2'] = 'Reponse de charge - revision ' + revision
vars.put('expected_answers', groovy.json.JsonOutput.toJson(answers))
vars.put('draft_json', groovy.json.JsonOutput.toJson([
    email: vars.get('email'), phone: vars.get('phone'), name: vars.get('name'), answers: answers,
    lastQuestion: revision % 3, remainingTime: Math.max(0L, (({end_ms}L - Math.max(due, now)) / 1000L).longValue())]))
'''
    script_node(loop_tree, 'JSR223Sampler', 'Preparer sauvegarde', prepare)
    conditional, writes = node(loop_tree, 'IfController', 'Sauvegarde due', 'IfControllerPanel')
    prop(conditional, 'IfController.condition', '${save_due}')
    prop(conditional, 'IfController.useExpression', 'true', 'boolProp')
    prop(conditional, 'IfController.evaluateAll', 'false', 'boolProp')
    children = sampler(writes, 'Brouillon periodique', 'PUT', base + '/session-draft', port,
                       '${draft_json}', check=draft_check, timeout_ms=8000)
    script_node(children, 'JSR223Timer', 'Horaire sauvegarde',
                "return Math.max(0L, vars.get('save_at').toLong() - System.currentTimeMillis())")
    # Submission uses exactly the latest answers which this candidate saved.
    script_node(tree, 'JSR223Sampler', 'Preparer soumission', f'''
vars.put('submission_json', groovy.json.JsonOutput.toJson([testId: '{test_id}',
    candidate: [email: vars.get('email'), phone: vars.get('phone'), name: vars.get('name')],
    answers: new groovy.json.JsonSlurper().parseText(vars.get('expected_answers'))]))
''')
    children = sampler(tree, 'Soumission', 'POST', '/api/admin/tests/results', port, '${submission_json}', 201,
        f"body.success == true && body.data.testId == '{test_id}' && body.data.candidate?.email == vars.get('email') && body.data.answers == new groovy.json.JsonSlurper().parseText(vars.get('expected_answers'))")
    script_node(children, 'JSR223Timer', 'Horaire soumission finale',
                "return Math.max(0L, vars.get('submit_at').toLong() - System.currentTimeMillis())")
    sampler(tree, 'Statut final', 'POST', base + '/update-status', port,
            check='body.success == true', timeout_ms=10000)
    ET.indent(root)
    ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)


def exam_checks(db, test_id, path, cumulative_expected, stage_expected, previous_answers, min_saves):
    answers = dict(previous_answers)
    saves = Counter()
    stage_rows = []
    with path.open(newline='', encoding='utf-8-sig') as source:
        for row in csv.DictReader(source):
            if row.get('success') != 'true':
                continue
            if row.get('label') == 'Brouillon periodique':
                saves[row['email']] += 1
            if row.get('label') == 'Soumission':
                stage_rows.append(row['email'])
                answers[row['email']] = json.loads(row['expected_answers'])
    rows = list(db.test_results.find({'testId': test_id}))
    sessions = list(db.test_sessions.find({'testId': test_id, 'status': 'submitted'}))
    result_emails = [row['candidate']['email'] for row in rows]
    session_emails = [row['candidateEmail'] for row in sessions]
    valid = (set(answers) == cumulative_expected and len(rows) == len(cumulative_expected)
             and set(result_emails) == cumulative_expected
             and len(sessions) == len(cumulative_expected) and set(session_emails) == cumulative_expected
             and len(stage_rows) == len(stage_expected) and set(stage_rows) == stage_expected
             and all(row.get('answers') == answers.get(row['candidate']['email']) for row in rows)
             and all(row.get('answers') == answers.get(row['candidateEmail']) for row in sessions)
             and all(saves[email] >= min_saves for email in stage_expected))
    return {'valid': valid, 'unique_stage_submissions': len(set(stage_rows)),
            'stored_results_total': len(rows), 'submitted_sessions_total': len(sessions),
            'required_minimum_periodic_saves_per_candidate': min_saves,
            'minimum_periodic_saves_per_candidate': min((saves[e] for e in stage_expected), default=0),
            'maximum_periodic_saves_per_candidate': max((saves[e] for e in stage_expected), default=0),
            'latest_answers_preserved': valid}, answers
