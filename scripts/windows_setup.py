"""Interactive installer/launcher; only dependencies are downloaded, never user data."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / '.venv/Scripts/python.exe'


def run(args, cwd=ROOT):
    subprocess.run([str(a) for a in args], cwd=cwd, check=True)


def node_compatible(version):
    parts = tuple(int(x) for x in version.strip().lstrip('v').split('.')[:3])
    return (parts[0] == 20 and parts >= (20, 19, 0)) or parts >= (22, 12, 0)


def npm_command():
    node = shutil.which('node')
    npm = shutil.which('npm')
    if not node or not npm:
        raise ValueError('未找到 Node.js。请先安装 Node.js 22.12+ 的 LTS 版，关闭并重新打开安装窗口。')
    version = subprocess.check_output([node, '--version'], text=True).strip()
    if not node_compatible(version):
        raise ValueError('Node.js 版本不满足要求，请安装 22.12+ 的 LTS 版。')
    # Run the official JS entry point directly, preserving Chinese paths/spaces.
    for path in [Path(node).parent / 'node_modules/npm/bin/npm-cli.js',
                 Path(npm).parent / 'node_modules/npm/bin/npm-cli.js']:
        if path.is_file():
            return [node, str(path)]
    raise ValueError('未找到 npm。请修复或重新安装 Node.js，并保留 npm 组件。')


def install():
    if sys.version_info[:2] != (3, 11):
        raise ValueError('请安装 Python 3.11 x64，并勾选 Python Launcher。')
    npm = npm_command()
    print('准备安装：只在此目录创建运行环境，不修改你的题库和 API 配置。')
    print('需要联网下载 Python/npm 依赖，不会自动更换下载源。')
    if input('继续安装？[Y/n] ').strip().lower() == 'n':
        return
    if not PYTHON.exists():
        run([sys.executable, '-m', 'venv', ROOT / '.venv'])
    run([PYTHON, '-m', 'pip', 'install', '-r', 'requirements.lock', '-r', 'requirements-d-shadow.lock'])
    run([*npm, 'ci', '--cache', str(ROOT / '.setup-cache/npm')], ROOT / 'frontend')
    run([*npm, 'run', 'build'], ROOT / 'frontend')
    (ROOT / 'materials').mkdir(exist_ok=True)
    print('安装完成。下一步双击 02-setup-api.cmd 配置 API，再双击 03-start.cmd。')


def start():
    if not PYTHON.exists() or not (ROOT / 'frontend/dist/index.html').is_file():
        raise ValueError('安装尚未完成，请先运行 01-install.cmd。')
    port = int(os.environ.get('QUESTION_BANK_PORT', '8765'))
    if not 1024 <= port <= 65535:
        raise ValueError('端口必须在 1024–65535 之间。')
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1', port))
        except OSError:
            raise ValueError('端口已被占用。若题库已启动，请打开原窗口；否则关闭占用程序后重试。') from None
    data = Path(os.environ.get('QUESTION_BANK_DATA', ROOT / 'data')).resolve()
    materials = Path(os.environ.get('QUESTION_BANK_MATERIALS_DIR', ROOT / 'materials')).resolve()
    data.mkdir(parents=True, exist_ok=True)
    materials.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONUTF8='1', QUESTION_BANK_DATA=str(data),
               QUESTION_BANK_MATERIALS_DIR=str(materials),
               QUESTION_BANK_NO_BACKGROUND_DB_WRITES='1' if (data / 'bank.sqlite').exists() else '0',
               QUESTION_BANK_PDF_IMPORT_PROFILE='pure_d_light_review_v1')
    proc = subprocess.Popen([str(PYTHON), '-X', 'utf8', '-m', 'uvicorn', 'backend.app:app',
                             '--host', '127.0.0.1', '--port', str(port), '--no-access-log'], cwd=ROOT, env=env)
    url = 'http://127.0.0.1:' + str(port) + '/'
    def open_when_ready():
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(60):
            if proc.poll() is not None:
                return
            try:
                with opener.open(url, timeout=1) as response:
                    if response.status == 200:
                        webbrowser.open(url)
                        return
            except OSError:
                time.sleep(.5)
        print('启动较慢，请查看窗口中的信息；尚未自动打开浏览器。')
    threading.Thread(target=open_when_ready, daemon=True).start()
    print('题库启动中。请保留此窗口；停止时按 Ctrl+C。地址：' + url)
    try:
        code = proc.wait()
        if code:
            raise ValueError('题库启动失败，请查看上方错误信息。')
    except KeyboardInterrupt:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            sys.path.insert(0, str(ROOT))
            from backend.platform_runtime import stop_process
            stop_process(proc)


if __name__ == '__main__':
    os.environ['PYTHONUTF8'] = '1'
    try:
        if sys.argv[1:] == ['install']:
            install()
        elif sys.argv[1:] == ['start']:
            start()
        else:
            raise ValueError('请选择安装或启动入口。')
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print('\n未完成：' + str(exc))
        print('不会自动重试或删除已有数据。请查看 INSTALL.md 后再运行。')
        sys.exit(1)
