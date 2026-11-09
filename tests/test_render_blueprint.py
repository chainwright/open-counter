"""render.yaml describes the live service (judge panel 09.11, F-04: the persistent disk was only in Render's dashboard):
a Docker web service with a disk at the data folder, and no key values in the file."""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SECRETS = {"PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_WEBHOOK_ID", "NEBIUS_API_KEY", "AG_STUDIO_LICENSE",
           "MAKER_KEY", "OPEN_COUNTER_SAMPLE_PAYEE"}


def blueprint():
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load((ROOT / "render.yaml").read_text())["services"][0]


def test_the_service_has_a_persistent_disk_at_the_data_folder():
    s = blueprint()
    assert s["type"] == "web" and s["runtime"] == "docker" and s["plan"] != "free"
    env = {e["key"]: e for e in s["envVars"]}
    assert s["disk"]["mountPath"] == env["OPENCOUNTER_DATA"]["value"] == "/var/data"
    # the image's own default is the same folder, so a forgotten env var still writes to the disk
    assert re.search(r"^ENV OPENCOUNTER_DATA=/var/data$", (ROOT / "Dockerfile").read_text(), re.M)


def test_no_key_has_a_value_in_the_file():
    env = {e["key"]: e for e in blueprint()["envVars"]}
    for k in SECRETS & env.keys():
        assert env[k] == {"key": k, "sync": False}
    assert {"PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "NEBIUS_API_KEY"} <= env.keys()


def test_every_variable_in_the_blueprint_is_one_the_code_reads():
    code = " ".join(p.read_text() for p in (ROOT / "opencounter").glob("*.py"))
    for e in blueprint()["envVars"]:
        assert e["key"] in code, e["key"]


def test_an_empty_cap_left_by_the_blueprint_form_falls_back_to_the_default():
    env = {**os.environ, **{k: "" for k in ("SHOPPER_DAILY_CAP_USD", "SHOPPER_VISITOR_CAP_USD", "SHOPPER_IP_CAP_USD",
                                            "STUDIO_DAILY_CAP_USD")}}
    out = subprocess.run([sys.executable, "-c", "from opencounter import shopper as s; "
                          "print(s.DAILY_CAP_USD, s.VISITOR_CAP_USD, s.IP_CAP_USD, s.STUDIO_CAP_USD)"],
                         cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == ["1.0", "0.15", "0.3", "0.5"]


def test_the_readme_has_the_deploy_button():
    assert "https://render.com/deploy?repo=https://github.com/chainwright/open-counter" in (ROOT / "README.md").read_text()
