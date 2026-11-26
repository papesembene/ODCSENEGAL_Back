"""Run the three independent ODC peaks on isolated disposable environments."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from jmeter_isolated import PEAK_PROFILES, ROOT


def can_continue(report, users):
    """A completed latency miss does not prevent an independent measurement.

    Integrity, request, resource, setup or cleanup errors stop the suite.
    """
    if not report.get('cleanup_complete'):
        return False
    if report.get('passed'):
        return True
    stages = report.get('stages') or []
    if not stages:
        return False
    stage = stages[-1]
    return (report.get('error') == 'Seuil, erreurs ou integrite: aucun palier superieur lance'
            and stage.get('users') == users and stage.get('integrity_ok') is True
            and bool(stage.get('endpoints'))
            and all(row.get('errors') == 0 and row.get('requests') == users
                    for row in stage['endpoints'].values()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mongod', type=Path, required=True)
    parser.add_argument('--jmeter', type=Path, required=True)
    parser.add_argument('--users', type=int, default=1000)
    parser.add_argument('--threads', type=int, default=16)
    parser.add_argument('--output', type=Path, default=ROOT / 'load_tests' / 'reports' / 'online-peaks')
    args = parser.parse_args()
    if not 2 <= args.users <= 2000 or not 1 <= args.threads <= 64:
        parser.error('Utilisateurs 2..2000; threads 1..64')
    if not args.mongod.is_file() or not args.jmeter.is_file():
        parser.error('Chemins de mongod et JMeter introuvables')
    output = args.output.resolve() / uuid4().hex
    output.mkdir(parents=True)
    summary = {'timestamp_utc': datetime.now(timezone.utc).isoformat(),
               'users': args.users, 'api_threads': args.threads, 'scenarios': [],
               'scope': 'Three independent private API/MongoDB runs, no frontend/IIS/TLS',
               'passed': False}
    try:
        for scenario, profile in PEAK_PROFILES.items():
            print(f"\n=== {scenario}: {args.users} candidats, montee {profile['ramp']} s, p95 <= {profile['p95']} ms ===", flush=True)
            target = output / scenario
            result = subprocess.run([sys.executable, str(Path(__file__).with_name('jmeter_isolated.py')),
                '--mongod', str(args.mongod.resolve()), '--jmeter', str(args.jmeter.resolve()),
                '--levels', str(args.users), '--threads', str(args.threads), '--scenario', scenario,
                '--ramp', str(profile['ramp']), '--max-p95-ms', str(profile['p95']), '--output', str(target)])
            reports = list(target.glob('*/summary.json'))
            if len(reports) != 1:
                raise RuntimeError(f'Rapport {scenario} manquant ou ambigu')
            report = json.loads(reports[0].read_text(encoding='utf-8'))
            summary['scenarios'].append({'scenario': scenario, 'exit_code': result.returncode,
                'report': str(reports[0]), 'passed': report.get('passed', False),
                'cleanup_complete': report.get('cleanup_complete', False),
                'stage': (report.get('stages') or [None])[-1]})
            if not can_continue(report, args.users):
                raise RuntimeError(f'Suite arretee apres {scenario}: {report.get("error", "echec")}. Voir son rapport.')
        summary['passed'] = all(row['passed'] for row in summary['scenarios'])
    except KeyboardInterrupt:
        summary['error'] = 'Interruption manuelle: aucun autre scenario lance'
    except Exception as error:
        summary['error'] = str(error)
    finally:
        path = output / 'suite-summary.json'
        path.write_text(json.dumps(summary, indent=2), encoding='utf-8')
        print(f'Bilan des trois scenarios: {path}', flush=True)
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
