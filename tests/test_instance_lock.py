import subprocess
import sys
import time

import pytest

from bot.instance_lock import single_instance_lock


def test_single_instance_lock_rejects_when_already_locked(tmp_path):
    lock_path = tmp_path / "bot.lock"
    child_code = """
import sys
import time
from pathlib import Path
from bot.instance_lock import single_instance_lock

lock_path = Path(sys.argv[1])
with single_instance_lock(lock_path):
    time.sleep(2)
"""

    proc = subprocess.Popen([sys.executable, "-c", child_code, str(lock_path)])
    try:
        time.sleep(0.5)
        with pytest.raises(RuntimeError):
            with single_instance_lock(lock_path):
                pass
    finally:
        proc.wait(timeout=5)
