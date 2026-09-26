import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from backend import platform_runtime as runtime


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_windows_cancellation_terminates_children(monkeypatch):
    monkeypatch.setattr(runtime, 'os', SimpleNamespace(name='nt'))
    run = Mock()
    monkeypatch.setattr(runtime.subprocess, 'run', run)
    proc = Mock(pid=123)
    proc.poll.return_value = None
    runtime.stop_process(proc)
    assert run.call_args.args[0] == ['taskkill', '/PID', '123', '/T', '/F']
    proc.wait.assert_called_once_with(timeout=5)


def test_windows_soffice_standard_location(tmp_path, monkeypatch):
    executable = tmp_path / 'LibreOffice/program/soffice.exe'
    executable.parent.mkdir(parents=True)
    executable.touch()
    monkeypatch.delenv('QUESTION_BANK_SOFFICE', raising=False)
    monkeypatch.setenv('ProgramFiles', str(tmp_path))
    monkeypatch.setattr(runtime.shutil, 'which', lambda _: None)
    assert runtime.soffice() == str(executable)


def test_opencode_npm_does_not_use_shell(tmp_path, monkeypatch):
    wrapper = tmp_path / 'opencode.cmd'
    js = tmp_path / 'node_modules/opencode-ai/bin/opencode'
    js.parent.mkdir(parents=True)
    js.touch()
    monkeypatch.setattr(runtime, 'os', SimpleNamespace(name='nt'))
    monkeypatch.setattr(runtime.shutil, 'which', lambda name: str(wrapper) if name == 'opencode' else 'node.exe')
    assert runtime.opencode_command() == ['node.exe', str(js)]


def test_unknown_windows_wrapper_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, 'os', SimpleNamespace(name='nt'))
    monkeypatch.setattr(runtime.shutil, 'which', lambda _: str(tmp_path / 'opencode.cmd'))
    with pytest.raises(ValueError):
        runtime.opencode_command()


def test_saved_config_preserves_existing_values(tmp_path, monkeypatch):
    guide = load('setup_opencode')
    monkeypatch.setenv('QUESTION_BANK_DATA', str(tmp_path))
    path = tmp_path / 'deepseek.private.json'
    original = {'model': 'existing', 'provider': 'deepseek', 'custom': '保留'}
    path.write_text(json.dumps(original), encoding='utf-8')
    guide.save('deepseek/deepseek-flash')
    saved = json.loads(path.read_text(encoding='utf-8'))
    assert saved['custom'] == '保留'
    assert saved['provider'] == saved['import_provider'] == 'opencode'
    assert json.loads(path.with_suffix('.json.backup').read_text()) == original


@pytest.mark.parametrize('version,expected', [('v18.20.0', False), ('v20.18.0', False), ('v20.19.0', True), ('v22.11.0', False), ('v22.12.0', True), ('v24.0.0', True)])
def test_node_versions(version, expected):
    assert load('windows_setup').node_compatible(version) is expected


def test_refusing_paid_test_does_not_save_or_call_model(monkeypatch):
    guide = load('setup_opencode')
    monkeypatch.setattr(guide, 'opencode_command', lambda: ['opencode'])
    replies = iter(['1.0', '--pure --format --dir', 'deepseek/deepseek-flash'])
    monkeypatch.setattr(guide, 'command', lambda *a: SimpleNamespace(returncode=0, stdout=next(replies)))
    answers = iter(['n', 'deepseek/deepseek-flash', 'n'])
    monkeypatch.setattr('builtins.input', lambda _: next(answers))
    save = Mock()
    popen = Mock(side_effect=AssertionError('Must not call API'))
    monkeypatch.setattr(guide, 'save', save)
    monkeypatch.setattr(guide.subprocess, 'Popen', popen)
    assert guide.main() == 0
    save.assert_not_called()
    popen.assert_not_called()


def test_failed_paid_test_does_not_change_config(monkeypatch):
    guide = load('setup_opencode')
    monkeypatch.setattr(guide, 'opencode_command', lambda: ['opencode'])
    replies = iter(['1.0', '--pure --format --dir', 'deepseek/deepseek-flash'])
    monkeypatch.setattr(guide, 'command', lambda *a: SimpleNamespace(returncode=0, stdout=next(replies)))
    answers = iter(['n', 'deepseek/deepseek-flash', 'y'])
    monkeypatch.setattr('builtins.input', lambda _: next(answers))
    proc = Mock(returncode=1)
    proc.communicate.return_value = ('{"type":"error","part":{}}', '')
    monkeypatch.setattr(guide.subprocess, 'Popen', Mock(return_value=proc))
    save = Mock()
    monkeypatch.setattr(guide, 'save', save)
    assert guide.main() == 1
    save.assert_not_called()
    proc.communicate.assert_called_once()
