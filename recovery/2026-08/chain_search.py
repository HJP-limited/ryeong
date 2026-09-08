"""시드 회차가 끝나면 동결된 검색 질의셋으로 검색 평가를 돌린다."""
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

SP = os.path.dirname(os.path.abspath(__file__))
REPO = r"c:/Users/babie/OneDrive/Desktop/HJP_limitededition-main/ymj-hybrid-search-rag-db-aligned"
WATCH = os.path.join(os.path.dirname(SP), "tasks", "bwqbw9fel.output")
MARK = "종료 (exit"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


log("시드 회차가 끝나기를 기다린다")
deadline = time.time() + 5 * 3600
last_size, last_change = -1, time.time()
while time.time() < deadline:
    try:
        text = open(WATCH, encoding="utf-8", errors="replace").read()
    except OSError:
        text = ""
    if MARK in text:
        log("시드 회차 끝남")
        break
    if len(text) != last_size:
        last_size, last_change = len(text), time.time()
    elif time.time() - last_change > 40 * 60:
        log("출력이 40분간 멈췄다 — 죽은 것으로 보고 넘어간다")
        break
    time.sleep(30)
else:
    log("5시간이 지났다 — 기다리기를 그만둔다")

out = os.path.join(SP, "eval_search_frozen.out")
log("동결본으로 검색 평가 실행")
with open(out, "w", encoding="utf-8") as fh:
    code = subprocess.call([sys.executable, "-u", "scripts/eval_search.py"],
                           cwd=REPO, stdout=fh, stderr=subprocess.STDOUT)
log(f"검색 평가 종료 (exit {code})")
