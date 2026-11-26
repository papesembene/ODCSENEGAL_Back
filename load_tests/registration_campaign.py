"""Synthetic campaign volume, bounded-rate endurance and resource traces."""
from collections import defaultdict
import csv
from datetime import datetime, timedelta, timezone
import json
import math
import time
import xml.etree.ElementTree as ET

import psutil


def preload_candidates(count, output):
    from jmeter_isolated import isolated_child
    isolated_child()  # Check private launcher contract before any app import.
    if not 0 <= count <= 75000:
        raise RuntimeError('Volume de prechargement hors limites')
    from app import create_app
    from app.models.candidature import Candidature
    import os
    run_id = os.environ['ODC_LOAD_RUN_ID']
    now = datetime.now(timezone.utc)
    app = create_app()
    with app.app_context():
        collection = Candidature._get_collection()
        if collection.name != 'candidatures_load':
            raise RuntimeError('Collection temporaire inattendue')
        Candidature.ensure_indexes()
        if collection.count_documents({}) != 0:
            raise RuntimeError('Prechargement refuse: la collection temporaire doit etre vide')
        for begin in range(0, count, 1000):
            batch = []
            for i in range(begin + 1, min(count, begin + 1000) + 1):
                candidate = Candidature(
                    first_name='PRELOAD', last_name=f'Candidate {i:06d}',
                    email=f'preload-{run_id}-{i}@example.invalid', phone=str(700000000 + i),
                    date_of_birth=datetime(2000, 1, 1), place_of_birth='Dakar', gender='male',
                    cni_or_passport_number=f'PRELOAD-{run_id}-{i}', nationality='Senegalaise',
                    region_of_residence='Dakar', computer_skills=True, available_for_10_months=True,
                    desired_training='Dev Web', training_site='dakar', training_site_name='Dakar',
                    accept_conditions=True, status='pending',
                    created_at=now - timedelta(seconds=(i * 7 * 86400) // max(1, count)),
                )
                candidate.validate()
                batch.append(candidate.to_mongo().to_dict())
            collection.insert_many(batch, ordered=True)
        total = collection.count_documents({})
        if total != count:
            raise RuntimeError('Nombre de candidatures prechargees incoherent')
        (output / 'preload.json').write_text(json.dumps({'count': total,
            'collection': collection.name, 'emails_queued_by_preload': 0}), encoding='utf-8')


def make_endurance_plan(path, port, count, workers, rate, run_id, start_ms):
    from jmeter_isolated import make_plan, node, prop
    workers = min(workers, count)
    make_plan(path, port, workers, 1, 'registration', run_id, registration_arrival='progressive')
    root = ET.parse(path)
    group = root.find('.//ThreadGroup')
    group.set('testname', 'registration_endurance')
    group.find(".//stringProp[@name='LoopController.loops']").text = str(math.ceil(count / workers))
    setup = root.find('.//JSR223Sampler')
    setup.find("stringProp[@name='script']").text = f'''
def sequence = (vars.get('sequence') ?: '0').toInteger()
def i = ctx.getThreadNum() + sequence * {workers} + 1
vars.put('sequence', (sequence + 1).toString())
vars.put('i', i.toString())
vars.put('do_journey', (i <= {count}).toString())
vars.put('arrival_at', ({start_ms}L + (long)((i - 1) * 1000d / {rate}d)).toString())
'''
    # Keep the normal three-request candidature journey under a conditional,
    # so the last incomplete worker round cannot insert extra candidates.
    group_tree = None
    # Locate the hashTree paired with ThreadGroup (XPath parent lookup is not
    # portable between ElementTree implementations).
    for parent in root.iter():
        children = list(parent)
        if group in children:
            group_tree = children[children.index(group) + 1]
            break
    if group_tree is None:
        raise RuntimeError('Structure du plan JMeter inattendue')
    pairs = list(group_tree)
    http_pairs = []
    for i, element in enumerate(pairs):
        if element.tag == 'HTTPSamplerProxy':
            http_pairs.append((element, pairs[i + 1]))
    if len(http_pairs) != 3:
        raise RuntimeError('Le parcours candidature doit contenir trois requetes')
    for sample, subtree in http_pairs:
        group_tree.remove(sample)
        group_tree.remove(subtree)
    conditional, journey = node(group_tree, 'IfController', 'Nouvelle candidature attendue', 'IfControllerPanel')
    prop(conditional, 'IfController.condition', '${do_journey}')
    prop(conditional, 'IfController.useExpression', 'true', 'boolProp')
    prop(conditional, 'IfController.evaluateAll', 'false', 'boolProp')
    for sample, subtree in http_pairs:
        journey.append(sample)
        journey.append(subtree)
    timer, _ = node(http_pairs[0][1], 'JSR223Timer', 'Rythme des candidatures', 'TestBeanGUI')
    prop(timer, 'scriptLanguage', 'groovy')
    prop(timer, 'cacheKey', 'true')
    prop(timer, 'script', "return Math.max(0L, vars.get('arrival_at').toLong() - System.currentTimeMillis())")
    ET.indent(root)
    root.write(path, encoding='utf-8', xml_declaration=True)


def time_buckets(path, width_seconds=300):
    from registration_load import summarize
    groups = defaultdict(lambda: defaultdict(list))
    with path.open(newline='', encoding='utf-8-sig') as source:
        rows = [row for row in csv.DictReader(source) if row.get('label') in {'Campagne', 'Unicite', 'Inscription'}]
    first = min((int(row['timeStamp']) for row in rows), default=0)
    for row in rows:
        index = int((int(row['timeStamp']) - first) // (width_seconds * 1000))
        groups[index][row['label']].append((float(row['elapsed']), row['responseCode'], row['success'] == 'true'))
    return [{'from_seconds': index * width_seconds, 'to_seconds': (index + 1) * width_seconds,
             'endpoints': {label: summarize(samples) for label, samples in labels.items()}}
            for index, labels in sorted(groups.items())]


def arrival_observation(path):
    starts = []
    with path.open(newline='', encoding='utf-8-sig') as source:
        for row in csv.DictReader(source):
            if row.get('label') == 'Campagne':
                starts.append(int(row['timeStamp']))
    span = (max(starts) - min(starts)) / 1000 if len(starts) > 1 else 0
    return {'observed_arrivals': len(starts), 'first_to_last_arrival_seconds': round(span, 3),
            'observed_rate_per_second': round((len(starts) - 1) / span, 3) if span else None}


class ResourceSamples(list):
    def __init__(self):
        super().__init__()
        self.origin = time.monotonic()
        self.phase = 'preparation'

    def append(self, sample):
        super().append({**sample, 'elapsed_seconds': round(time.monotonic() - self.origin, 3),
                       'timestamp_utc': datetime.now(timezone.utc).isoformat(), 'phase': self.phase,
                       'system_memory_percent': psutil.virtual_memory().percent})

    def write_csv(self, path):
        if not self:
            return
        with path.open('w', newline='', encoding='utf-8') as target:
            writer = csv.DictWriter(target, fieldnames=list(self[0]))
            writer.writeheader()
            writer.writerows(self)


def peak_resources(readings):
    if not readings:
        return {}
    return {key: max(row[key] for row in readings) for key in readings[0]
            if key.endswith('_percent') or key.endswith('_rss_mb')}
