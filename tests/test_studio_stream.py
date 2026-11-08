"""'Draft a lesson' really streams (final judges 08.11 P0-2): the studio cell shows each model token as it arrives,
not a typewriter replay of the finished text. studio/src/lessonStream.ts (what StuckWidget uses) runs in node."""
import json
import shutil
import subprocess

import pytest

from opencounter import shop

ROOT = shop.ROOT


def run(mode=""):
    node = shutil.which("node")
    if not node:
        pytest.skip("node isn't installed")
    out = subprocess.run([node, str(ROOT / "tests" / "js" / "lesson_stream.mjs"), str(ROOT / "studio" / "src" / "lessonStream.ts"), mode],
                         capture_output=True, text=True, timeout=20)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])["log"]


def test_each_token_is_shown_while_the_model_is_still_writing():
    log = run()
    texts = [x for x in log if x["kind"] == "text"]
    assert [x["deltas_sent"] for x in texts] == [1, 2, 3, 4]       # drawn as each delta lands, before the next is sent
    assert texts[0]["text"] == "If someone asks" and texts[-1]["text"].endswith("takes cards too.")
    assert log[-1]["kind"] == "done" and log[-1]["usable"] is True
    assert sum(x["kind"] == "text" for x in log[log.index(log[-1]):]) == 0   # nothing is typed out after RUN_FINISHED


def test_a_budget_error_or_a_cut_stream_says_so():
    last = run("error")[-1]
    assert last["kind"] == "error" and last["message"] == "Today's AI budget is used up."
    assert run("cut")[-1]["kind"] == "error"


def test_the_widget_uses_the_stream_reader_and_no_replay_loop():
    src = (ROOT / "studio" / "src" / "StuckWidget.tsx").read_text()
    assert "readLessonStream" in src and "setTimeout" not in src
    assert "Lena's assistant is writing" in src and "shop analyst is writing" not in src
