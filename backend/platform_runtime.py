"""Local runtime discovery and process lifecycle on Windows and POSIX."""
import os
import shutil
import signal
import subprocess
from pathlib import Path


def soffice():
    candidates = [os.environ.get('QUESTION_BANK_SOFFICE'), shutil.which('soffice')]
    for key in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA'):
        if os.environ.get(key):
            candidates.append(str(Path(os.environ[key]) / 'LibreOffice/program/soffice.exe'))
    candidates += ['/Applications/LibreOffice.app/Contents/MacOS/soffice',
                   str(Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/override/soffice')]
    return next((p for p in candidates if p and Path(p).is_file()), None)


def process_options():
    return {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}


def stop_process(proc):
    if proc.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True, timeout=10)
        if proc.poll() is None:
            proc.kill()
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name == 'nt':
            proc.kill()
        else:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        proc.wait(timeout=5)


def opencode_command():
    """Bypass Windows .cmd wrappers so document names never pass through cmd.exe."""
    executable = shutil.which('opencode')
    if not executable:
        return None
    if os.name != 'nt' or Path(executable).suffix.lower() == '.exe':
        return [executable]
    native = Path(executable).with_suffix('.exe')
    if native.is_file():
        return [str(native)]
    node = shutil.which('node')
    launcher = Path(executable).parent / 'node_modules/opencode-ai/bin/opencode'
    if node and launcher.is_file():
        return [node, str(launcher)]
    raise ValueError('无法直接启动 OpenCode。请安装官方 CLI（npm install -g opencode-ai）后重新打开程序。')
