"""Interactive local API setup. No credentials are read or copied by this guide."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.platform_runtime import process_options, stop_process, opencode_command


def command(exe, *args):
    return subprocess.run([*exe, *args], capture_output=True, text=True,
                          encoding='utf-8', errors='replace', timeout=40)


def save(model):
    folder = Path(os.environ.get('QUESTION_BANK_DATA', ROOT / 'data'))
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / 'deepseek.private.json'
    data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'model': 'deepseek-flash'}
    data.update(provider='opencode', import_provider='opencode', opencode_model=model, opencode_reasoning='low')
    if path.exists():
        backup = path.with_suffix('.json.backup')
        backup.write_bytes(path.read_bytes())
        backup.chmod(0o600)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w', encoding='utf-8') as out:
        json.dump(data, out, ensure_ascii=False, indent=2)
    return path


def main():
    print('题库 · OpenCode API 接入引导\n无需 Codex。登录密钥由 OpenCode 自己保存。')
    exe = opencode_command()
    if not exe:
        print('未找到 OpenCode 命令行。请安装 OpenCode CLI，并重新打开本窗口。\nhttps://opencode.ai/docs/')
        return 1
    result = command(exe, '--version')
    if result.returncode:
        print('OpenCode 无法启动，请先在终端确认 opencode --version 可以运行。')
        return 1
    print('已检测到 OpenCode：' + result.stdout.strip()[:80])
    help_result = command(exe, 'run', '--help')
    if help_result.returncode or not all(flag in help_result.stdout for flag in ('--pure', '--format', '--dir')):
        print('此 OpenCode 版本缺少题库需要的调用参数。请更新 OpenCode CLI 后重试。')
        return 1
    if input('是否打开 OpenCode 官方登录引导，连接你的 API 账户？[y/N] ').strip().lower() == 'y':
        if subprocess.call([*exe, 'auth', 'login']):
            print('登录未完成，可稍后重试。')
            return 1
    result = command(exe, 'models')
    if result.returncode:
        print('无法读取模型列表，请运行 opencode auth login 检查账户配置。')
        return 1
    models = sorted(set(re.findall(r'^[\w.-]+/[\w./:-]+$', result.stdout, re.M)))
    print('模型列表可用；这不代表 API 已连接或模型支持图片。')
    for model in models:
        if 'deepseek' in model.lower():
            print('  ' + model)
    model = input('输入题库模型完整名称（provider/model）：').strip()
    supported = {'deepseek/deepseek-flash', 'deepseek/deepseek-v4-flash', 'deepseek/deepseek-v4-flash-vision-exp'}
    if model not in models or model not in supported:
        print('该模型未列出，或尚未通过题库图片流程适配。未保存。请勿把纯文字模型用于图片识别。')
        return 1
    if input('发送一次简短 API 请求验证连接？会产生少量费用。[y/N] ').strip().lower() != 'y':
        print('未调用 API，也未更改题库配置。')
        return 0
    env = dict(os.environ, OPENCODE_CONFIG_CONTENT=json.dumps({'permission': {'*': 'deny'}}),
               OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX='256', PYTHONUTF8='1')
    import tempfile
    with tempfile.TemporaryDirectory(prefix='question-bank-connect-') as directory:
        proc = subprocess.Popen([*exe, 'run', '--pure', '--format', 'json', '--dir', directory,
                                 '--model', model], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace',
                                env=env, **process_options())
        try:
            output, _ = proc.communicate('仅回复 QB_CONNECTION_OK，不调用工具。', timeout=60)
        except subprocess.TimeoutExpired:
            stop_process(proc)
            print('连接测试超时，已停止；未自动重试，未保存配置。')
            return 1
    events = []
    for line in output.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    events = [e for e in events if isinstance(e, dict) and isinstance(e.get('part', {}), dict)]
    text = ''.join(e.get('part', {}).get('text', '') for e in events if e.get('type') == 'text')
    if proc.returncode or any(e.get('type') == 'error' for e in events) or 'QB_CONNECTION_OK' not in text:
        print('API 测试未通过。请检查账户余额、模型权限和网络；未保存配置。')
        return 1
    save(model)
    print('连接成功，题库已设为 OpenCode。此测试仅验证文字连接；图片识别仍需导入样例验证。')
    print('用量：' + json.dumps([e.get('part', {}).get('tokens') for e in events if e.get('type') == 'step_finish'], ensure_ascii=False))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, subprocess.SubprocessError, ValueError):
        print('引导未完成。请确认 OpenCode 能运行、配置文件有效且目录可写。')
        sys.exit(1)
