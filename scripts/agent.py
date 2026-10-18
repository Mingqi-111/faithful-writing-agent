#!/usr/bin/env python3
"""Host-driven writing Agent: JSON CLI, local SQLite, no network/API/web server."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys

# Isolated Python removes the script directory from sys.path. Only add this
# package's resolved scripts directory; never import a runtime from the cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from runtime import VERSION
from runtime.benchmark import Benchmark, offline
from runtime.engine import Engine, ROOT, SCENES, scene_id
from runtime.learning import Learning
from runtime.store import Store


def read_text(path, maximum=24000):
    file = Path(path)
    if file.stat().st_size > maximum * 4 + 4:
        raise ValueError("输入文件过大，不会静默截断")
    text = file.read_text(encoding="utf-8-sig")
    if len(text) > maximum:
        raise ValueError(f"输入最多 {maximum} 字符，不会静默截断")
    return text


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"JSON 字段重复：{key}")
            result[key] = value
        return result
    def invalid_constant(value):
        raise ValueError(f"JSON 不允许 {value}")
    return json.loads(read_text(path, 200000), object_pairs_hook=unique, parse_constant=invalid_constant)


def parser():
    p = argparse.ArgumentParser(description="宿主负责推理，本地脚本负责状态、检查、反馈与评测；不需要 API key。")
    p.add_argument("--version", action="version", version=VERSION)
    p.add_argument("--data-dir", default=argparse.SUPPRESS, help="状态目录；默认当前工作目录/.faithful-writing-agent")
    commands = p.add_subparsers(dest="command", required=True)

    def command(name, help_text):
        sub = commands.add_parser(name, help=help_text, description=help_text)
        sub.add_argument("--data-dir", default=argparse.SUPPRESS, help="状态目录，可放在子命令后")
        sub.add_argument("--user", default="local", help="本地用户隔离 ID，默认 local")
        return sub

    def scene(sub):
        sub.add_argument("--scene", type=scene_id, default="general", metavar="SCENE",
                         help=f"当前分类：{', '.join(SCENES)}；兼容历史场景 ID")

    def run(sub):
        sub.add_argument("--run", required=True, help="start 返回的 run ID")

    start = command("start", "创建改写任务，返回给宿主执行的 draft 指令")
    start.add_argument("--text-file", required=True)
    start.add_argument("--host", default="unknown", help="宿主/模型配置标识，请如实填写")
    start.add_argument("--deai", choices=("off", "light", "strong"), default="off",
                       help="用户明确请求时开启去模板；light 只局部调整，strong 需另有语气/结构授权")
    scene(start)
    draft = command("draft", "保存宿主草稿并返回语义审评任务；最多三轮")
    run(draft)
    draft.add_argument("--text-file", required=True)
    review = command("review", "提交绑定当前草稿的严格 JSON 审评；静态硬错不可覆盖")
    run(review)
    review.add_argument("--json-file", required=True)
    run(command("show", "查看改写状态和下一步任务"))
    scene(command("profile", "查看当前场景偏好、候选和反馈数量"))
    feedback = command("feedback", "记录用户明确反馈；不能把复制或使用次数当反馈")
    run(feedback)
    feedback.add_argument("--final-file", required=True)
    feedback.add_argument("--rating", required=True, choices=("accepted", "edited", "rejected"))
    feedback.add_argument("--note", default="")
    feedback.add_argument("--note-file", help="可选 UTF-8 备注文件，代替 --note")
    learn = command("learn", "冻结至少 6 篇确认反馈，返回训练材料，隐藏最后 3 篇留存稿")
    scene(learn)
    learn.add_argument("--learning-mode", choices=("independent", "same_context"), default="same_context",
                       help="仅真实使用未见留存稿的新上下文提取偏好时选 independent；默认 same_context 降级")
    propose = command("propose", "提交白名单偏好及至少三条证据，创建未启用候选")
    scene(propose)
    propose.add_argument("--json-file", required=True)
    benchmark = command("benchmark", "offline 检查器回归；prepare 宿主评测；report 完整率与比较任务")
    benchmark.add_argument("--mode", required=True, choices=("offline", "prepare", "report"))
    benchmark.add_argument("--limit", type=int)
    benchmark.add_argument("--candidate")
    benchmark.add_argument("--case", action="append", dest="case_ids", help="只运行指定公开开发用例，可重复；不能裁剪个人门控")
    benchmark.add_argument("--id", help="report 所需 benchmark ID")
    benchmark.add_argument("--host", default="unknown")
    compare = command("benchmark-review", "提交全部盲 A/B 比较结果，自审降级，不允许漏项")
    compare.add_argument("--id", required=True)
    compare.add_argument("--json-file", required=True)
    activate = command("activate", "显式启用通过冻结评测的候选；保留回退历史")
    activate.add_argument("--candidate", required=True)
    activate.add_argument("--allow-self-reviewed", action="store_true", help="仅在用户明确接受自审降级时使用；不能绕过缺项或失败")
    scene(command("rollback", "回退上一次偏好启用，支持连续回退"))
    command("doctor", "检查当前 Python、资源和状态路径，不调用网络")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    directory = Path(getattr(args, "data_dir", Path.cwd() / ".faithful-writing-agent")).expanduser().resolve()
    store = None
    try:
        if args.command == "doctor":
            result = {"version": VERSION, "python": sys.version.split()[0], "python_supported": sys.version_info >= (3, 11),
                      "root": str(ROOT), "sqlite_version": sqlite3.sqlite_version,
                      "resources_present": all((ROOT / path).is_file() for path in
                          ("SKILL.md", "references/scenes.json", "references/legacy-scenes.json",
                           "benchmarks/agent_cases.jsonl", "benchmarks/evaluator_cases.jsonl")),
                      "network_calls": False, "requires_api_key": False}
        elif args.command == "benchmark" and args.mode == "offline":
            if args.id or args.candidate or args.limit is not None or args.case_ids:
                raise ValueError("offline 不接受 id、candidate、limit 或 case")
            result = offline()
        else:
            store = Store(directory)
            engine, learning, benchmark = Engine(store), Learning(store), Benchmark(store)
            command, user = args.command, args.user
            if command == "start":
                result = engine.start(read_text(args.text_file, 16000), args.scene, user, args.host, deai=args.deai)
            elif command == "draft":
                result = engine.draft(args.run, read_text(args.text_file), user)
            elif command == "review":
                result = engine.review(args.run, read_json(args.json_file), user)
            elif command == "show":
                result = engine.show(args.run, user)
            elif command == "profile":
                result = learning.profile(user, args.scene)
            elif command == "feedback":
                note = read_text(args.note_file, 2000) if args.note_file else args.note
                result = engine.feedback(args.run, read_text(args.final_file), args.rating, note, user)
            elif command == "learn":
                result = learning.learn(user, args.scene, args.learning_mode)
            elif command == "propose":
                result = learning.propose(user, args.scene, read_json(args.json_file))
            elif command == "benchmark":
                if args.mode == "prepare":
                    if args.id:
                        raise ValueError("prepare 不接受 id")
                    result = benchmark.prepare(user, args.limit, args.candidate, args.host, case_ids=args.case_ids)
                else:
                    if not args.id or args.limit is not None or args.candidate or args.case_ids:
                        raise ValueError("report 必须提供 id，且不接受 limit/candidate/case")
                    result = benchmark.report(args.id, user)
            elif command == "benchmark-review":
                result = benchmark.submit_comparisons(args.id, read_json(args.json_file), user)
            elif command == "activate":
                result = learning.activate(args.candidate, user, args.allow_self_reviewed)
            elif command == "rollback":
                result = learning.rollback(user, args.scene)
            else:
                raise ValueError("未知命令")
        result["state_path"] = str(directory / "state.sqlite3")
        result["state_note"] = "包含原文、改稿和反馈的本地私人数据；跨设备延续时只复制你信任的状态文件。"
        if store:
            store.finish(True)
            store = None
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, sqlite3.Error, KeyError, TypeError) as exc:
        if store:
            store.finish(False)
        print(json.dumps({"error": str(exc), "changed": False, "state_path": str(directory / "state.sqlite3")}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
