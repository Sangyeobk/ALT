import json
import os
import subprocess
import sys
from pathlib import Path


def test_plugin_keeps_code_config_separate_from_user_workspace(tmp_path):
    package = Path(__file__).resolve().parents[1] / "alt"
    environment = dict(os.environ, PYTHONPATH=str(package))
    result = subprocess.run([sys.executable, "-c", "import json; from common import PROJECT_DIR, CONFIG_PATH; "
                             "print(json.dumps([str(PROJECT_DIR), str(CONFIG_PATH)]))"],
                            cwd=tmp_path, env=environment, capture_output=True, text=True, check=True)
    workspace, config = json.loads(result.stdout)
    assert Path(workspace) == tmp_path
    assert Path(config) == package / "config.yaml"
