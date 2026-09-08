"""
밤새 이어 돌린다: 절제 실험이 끝나기를 기다렸다가 -> 서버를 새 코드로 갈아끼우고 ->
v1.4(동명이인 63개)를 돌린다.

왜 기다리나: 지금 :8100 서버는 --no-bypass 절제 실험이 붙잡고 있고, 그 프로세스는
**옛 코드**를 메모리에 올린 채로 돈다. 중간에 갈아끼우면 앞뒤 절반이 다른 코드로
측정되어 그 실행이 통째로 못 쓰게 된다.
"""
import json
import os
import socket
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

SP = os.path.dirname(os.path.abspath(__file__))
REPO = r"c:/Users/babie/OneDrive/Desktop/HJP_limitededition-main/ymj-hybrid-search-rag-db-aligned"
ABLATION_OUT = os.path.join(SP, "v13_nobypass.out")
DONE_MARK = "=== 통합 벤치 채점"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ── 1) 절제 실험이 끝나기를 기다린다 ────────────────────────────────────────
log("절제 실험이 끝나기를 기다린다")
deadline = time.time() + 4 * 3600
last_size, last_change = -1, time.time()
while time.time() < deadline:
    try:
        text = open(ABLATION_OUT, encoding="utf-8", errors="replace").read()
    except OSError:
        text = ""
    if DONE_MARK in text:
        log("절제 실험 보고가 찍혔다 — 끝났다")
        break
    size = len(text)
    if size != last_size:
        last_size, last_change = size, time.time()
    elif time.time() - last_change > 20 * 60:
        # 20분째 한 줄도 안 늘었다 = 죽었다. 계속 기다리면 밤을 통째로 버린다.
        log("출력이 20분간 멈췄다 — 죽은 것으로 보고 넘어간다")
        break
    time.sleep(30)
else:
    log("4시간이 지났다 — 기다리기를 그만두고 넘어간다")

# ── 2) 서버를 새 코드로 갈아끼운다 ──────────────────────────────────────────
log("옛 코드로 도는 hybrid_server 들을 내린다(:8100, :8101)")
subprocess.run(
    ["powershell", "-NoProfile", "-Command",
     "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | "
     "Where-Object { $_.CommandLine -like '*hybrid_server.py*' } | "
     "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
    capture_output=True)
time.sleep(3)

log("새 코드로 :8100 을 띄운다")
env = dict(os.environ, HJP_HYBRID_PORT="8100")
server_log = open(os.path.join(SP, "hybrid_v14.log"), "w", encoding="utf-8")
subprocess.Popen([sys.executable, "-u", "scripts/hybrid_server.py"],
                 cwd=REPO, env=env, stdout=server_log, stderr=subprocess.STDOUT)

for _ in range(180):
    s = socket.socket()
    s.settimeout(1)
    try:
        s.connect(("127.0.0.1", 8100))
        log("서버 준비됨")
        break
    except OSError:
        time.sleep(2)
    finally:
        s.close()
else:
    log("서버가 안 떴다 — 중단")
    raise SystemExit(1)

# ── 3) v1.4 를 돌린다 ───────────────────────────────────────────────────────
dump = os.path.join(SP, "bench_v14.jsonl")
out = os.path.join(SP, "v14.out")
log("v1.4 공개셋 채점 시작")
with open(out, "w", encoding="utf-8") as fh:
    code = subprocess.call(
        [sys.executable, "-u", "scripts/run_bench.py",
         "--bench", "bench/hjp_multiturn_v1.4.json", "--split", "public",
         "--dump", dump],
        cwd=REPO, stdout=fh, stderr=subprocess.STDOUT)
log(f"v1.4 종료 (exit {code})")

text = open(out, encoding="utf-8", errors="replace").read()
if DONE_MARK in text:
    print(text[text.index(DONE_MARK):][:3000])
else:
    print(text[-2000:])
