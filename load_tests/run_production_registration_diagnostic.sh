#!/usr/bin/env bash
set -uo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." || exit 1
fail() { printf '%s\n' "$*" >&2; exit 1; }
py=.venv/bin/python
locust=.venv/bin/locust
[[ -x "$py" && -x "$locust" ]] || fail 'Environnement .venv introuvable dans backend.'
[[ -x /usr/bin/tcpdump ]] || fail '/usr/bin/tcpdump est requis.'
command -v timeout >/dev/null || fail 'timeout est requis.'
ulimit -n 8192 || fail 'Impossible de fixer la limite de fichiers à 8192.'
sudo -v || fail 'Autorisation sudo requise pour observer les en-têtes TCP.'
ODC_LOAD_RUN_ID=$("$py" -c 'import uuid; print(uuid.uuid4().hex[:12])') || exit 1
export ODC_LOAD_RUN_ID ODC_LOAD_EMAILS_PAUSED=YES ODC_LOAD_MAX_SIGNUPS=1000
export ODC_LOAD_ALLOW_LARGE_PROD=YES ODC_LOAD_SYNC_BURST=YES ODC_LOAD_FORMATION='Dev Web'
mkdir -p load_tests/reports || exit 1
prefix="load_tests/reports/prod-1000-$ODC_LOAD_RUN_ID"
capture="$prefix-tcp.txt"
capture_error="$prefix-tcp.stderr.log"
capture_pid=''
trap '[[ -z "$capture_pid" ]] || wait "$capture_pid" 2>/dev/null || true' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
sudo -n timeout -s INT -k 5s 90s env LC_ALL=C TZ=UTC /usr/bin/tcpdump \
  -i any -nn -tttt -l -s 96 \
  'host 154.124.241.143 and tcp port 443 and (tcp[tcpflags] & (tcp-syn|tcp-rst) != 0)' \
  >"$capture" 2>"$capture_error" &
capture_pid=$!
ready=0
for _ in {1..50}; do
  if grep -q 'listening on' "$capture_error"; then ready=1; break; fi
  jobs -pr | grep -qx "$capture_pid" || break
  sleep 0.1
done
if (( ! ready )); then cat "$capture_error" >&2; fail 'Capture non démarrée : test annulé.'; fi
printf 'RUN_ID=%s\nTest en cours pendant 2 minutes.\n' "$ODC_LOAD_RUN_ID"
"$locust" -f load_tests/production_registration_locustfile.py \
  --headless --host https://api.orangedigitalcenter.sn \
  -u 1000 -r 25 -t 2m --only-summary --csv "$prefix" \
  >"$prefix-locust.log" 2>&1
locust_status=$?
wait "$capture_pid"
capture_status=$?
capture_pid=''
printf '\nRUN_ID=%s\nCode Locust : %s\n' "$ODC_LOAD_RUN_ID" "$locust_status"
if (( capture_status != 0 && capture_status != 124 )); then
  printf 'Capture interrompue (code %s).\n' "$capture_status"
fi
if [[ -f "${prefix}_stats.csv" ]]; then cat "${prefix}_stats.csv"; else printf 'CSV absent : voir %s-locust.log\n' "$prefix"; fi
"$py" - "$capture" <<'PY'
import collections
from pathlib import Path
import re
import sys

target = "154.124.241.143"
pattern = re.compile(r"\bIP (\d+\.\d+\.\d+\.\d+)\.(\d+) > (\d+\.\d+\.\d+\.\d+)\.(\d+): Flags \[([^\]]+)\]")
syn = collections.Counter()
synack = set()
rst_out = rst_in = 0
for line in Path(sys.argv[1]).read_text(errors="replace").splitlines():
    match = pattern.search(line)
    if not match:
        continue
    src, sport, dst, dport, flags = match.groups()
    if dst == target and dport == "443":
        if "S" in flags and "." not in flags:
            syn[(src, sport, dst, dport)] += 1
        rst_out += "R" in flags
    elif src == target and sport == "443":
        if "S" in flags and "." in flags:
            synack.add((dst, dport, src, sport))
        rst_in += "R" in flags
answered = set(syn) & synack
print("SYN uniques émis :", len(syn))
print("SYN émis au total :", sum(syn.values()))
print("Retransmissions SYN observées :", sum(syn.values()) - len(syn))
print("Connexions avec SYN-ACK reçu :", len(answered))
print("Connexions sans SYN-ACK observé :", len(set(syn) - answered))
print("RST reçus / émis :", rst_in, "/", rst_out)
print("Comptages à interpréter avec les pertes tcpdump et les éventuels doublons entre interfaces.")
PY
parser_status=$?
printf '\nÉtat tcpdump :\n'
tail -n 4 "$capture_error"
printf 'Log complet : %s-locust.log\n' "$prefix"
if (( locust_status == 0 && (parser_status != 0 || (capture_status != 0 && capture_status != 124)) )); then exit 1; fi
exit "$locust_status"
