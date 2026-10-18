"""Copy this skill into a selected project's native skill directory. No network."""
import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parent.parent
SKILL_NAME = 'faithful-writing-agent'
LOCATIONS = {'codex': '.agents/skills', 'claude-code': '.claude/skills', 'workbuddy': '.codebuddy/skills'}
EXCLUDE = {'.faithful-writing-agent', '__pycache__', '.DS_Store', '.git', '.env'}


def install(host, project):
    project = Path(project).expanduser().resolve()
    if not project.is_dir():
        raise ValueError('项目目录不存在，请选择实际的写作工作目录')
    if host not in LOCATIONS:
        raise ValueError('该宿主请使用其技能导入界面')
    destination = project / LOCATIONS[host] / SKILL_NAME
    if destination == ROOT or ROOT in destination.parents or destination in ROOT.parents:
        raise ValueError('安装目标不能位于当前技能包内部或覆盖它的父目录')
    if destination.exists():
        raise ValueError('目标技能已存在，未覆盖：' + str(destination))
    if not destination.parent.resolve().is_relative_to(project):
        raise ValueError('技能父目录指向项目外部；未安装')
    for p in ROOT.rglob('*'):
        if p.is_symlink():
            raise ValueError('分发包不能含符号链接')
    destination.parent.mkdir(parents=True, exist_ok=True)
    # No global app configuration, global HOME path or stored user state changes.
    shutil.copytree(ROOT, destination, ignore=lambda _path, names: [name for name in names if name in EXCLUDE or name.endswith('.pyc')])
    return {'installed': True, 'host': host, 'path': str(destination), 'scope': 'project',
            'next': '在这个项目中调用 faithful-writing-agent；若未出现，刷新技能列表或重新打开任务。'}


def main():
    parser = argparse.ArgumentParser(description='安装到当前写作项目，不修改全局配置或覆盖已有技能')
    parser.add_argument('--host', choices=LOCATIONS, required=True)
    parser.add_argument('--project', required=True, help='已有写作工作目录')
    args = parser.parse_args()
    try:
        print(json.dumps(install(args.host, args.project), ensure_ascii=False))
    except (ValueError, OSError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False))
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
