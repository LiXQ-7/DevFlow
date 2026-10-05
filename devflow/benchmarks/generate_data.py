"""Build fixed, inspectable test inputs. No model outputs or target percentages are generated."""

import json

from .common import DATA


def tool_cases():
    cases = []
    for variant in range(4):
        file = ["sample.txt", "中文文件.txt", "src/module.txt", "folder with space/a.txt"][variant]
        missing = f"missing-{variant}.txt"
        new = f"new/{variant}.txt"
        content = f"alpha-{variant}\nbeta-{variant}\nalpha-{variant}\nunique-{variant}\n"
        todos = [{"id": "1", "content": f"分析模块 {variant}", "status": "in_progress"}]
        definitions = {
            "Read": [
                (f"读取 {file} 的正文。", {"path": file}, "SUCCESS"),
                (
                    f"查看 {file} 的第 2 行。",
                    {"path": file, "start_line": 2, "end_line": 2},
                    "PARTIAL",
                ),
                (f"从第 3 行读到末尾：{file}。", {"path": file, "start_line": 3}, "SUCCESS"),
                (f"读取不存在的 {missing} 并报告错误。", {"path": missing}, "NOT_FOUND"),
                (f"以最多 3 字节读取 {file}。", {"path": file, "max_bytes": 3}, "PARTIAL"),
                (
                    f"读取 {file}，行号从 0 开始，用于参数错误测试。",
                    {"path": file, "start_line": 0},
                    "INVALID_PARAM",
                ),
                ("读取 ../outside.txt，检查越界拒绝。", {"path": "../outside.txt"}, "PERMISSION"),
                (f"查看 {file} 的第 50 行。", {"path": file, "start_line": 50}, "SUCCESS"),
                (
                    f"读取 {file} 的第 4 到 2 行，检查反向区间。",
                    {"path": file, "start_line": 4, "end_line": 2},
                    "INVALID_PARAM",
                ),
                (
                    f"读取二进制文件 binary-{variant}.dat。",
                    {"path": f"binary-{variant}.dat"},
                    "INVALID_ENCODING",
                ),
            ],
            "Write": [
                (f"新建 {new}，内容 hello。", {"path": new, "content": "hello"}, "SUCCESS"),
                (
                    f"把 {file} 整体覆盖成 hello，明确允许覆盖。",
                    {"path": file, "content": "hello", "overwrite": True},
                    "SUCCESS",
                ),
                (
                    f"写入已存在的 {file}，内容 x，不允许覆盖。",
                    {"path": file, "content": "x"},
                    "ALREADY_EXISTS",
                ),
                (
                    f"创建空文件 empty-{variant}.txt。",
                    {"path": f"empty-{variant}.txt", "content": ""},
                    "SUCCESS",
                ),
                (
                    f"新建 中文/{variant}/说明.md，内容为 你好。",
                    {"path": f"中文/{variant}/说明.md", "content": "你好"},
                    "SUCCESS",
                ),
                (
                    "写入 ../outside.txt，内容 x，用于越界校验。",
                    {"path": "../outside.txt", "content": "x"},
                    "PERMISSION",
                ),
                (
                    "写入 .git/config，内容 x，用于元数据保护测试。",
                    {"path": ".git/config", "content": "x"},
                    "PERMISSION",
                ),
                (f"创建 {new}，内容是两行 a 和 b。", {"path": new, "content": "a\nb\n"}, "SUCCESS"),
                (
                    f"创建目录层级 deep/{variant}/nested/file.py，内容 pass。",
                    {"path": f"deep/{variant}/nested/file.py", "content": "pass\n"},
                    "SUCCESS",
                ),
                (f"写 {new}，故意缺少 content 以检查 schema。", {"path": new}, "INVALID_PARAM"),
            ],
            "Edit": [
                (
                    f"在 {file} 中将 unique-{variant} 精确替换为 fixed。",
                    {"path": file, "old_text": f"unique-{variant}", "new_text": "fixed"},
                    "SUCCESS",
                ),
                (
                    f"在 {file} 中将 absent 替换为 fixed。",
                    {"path": file, "old_text": "absent", "new_text": "fixed"},
                    "NOT_FOUND",
                ),
                (
                    f"在 {file} 中将 alpha-{variant} 替换为 fixed，检查重复匹配。",
                    {"path": file, "old_text": f"alpha-{variant}", "new_text": "fixed"},
                    "CONFLICT",
                ),
                (
                    f"将 {file} 中 unique-{variant} 换成 fixed，expected_hash=stale。",
                    {
                        "path": file,
                        "old_text": f"unique-{variant}",
                        "new_text": "fixed",
                        "expected_hash": "stale",
                    },
                    "CONFLICT",
                ),
                (
                    f"删除 {file} 中唯一的 beta-{variant} 文本。",
                    {"path": file, "old_text": f"beta-{variant}", "new_text": ""},
                    "SUCCESS",
                ),
                (
                    f"把 {file} 的全部已知内容 {content!r} 替换为 whole。",
                    {"path": file, "old_text": content, "new_text": "whole"},
                    "SUCCESS",
                ),
                (
                    f"编辑缺失的 {missing}，将 x 换成 y。",
                    {"path": missing, "old_text": "x", "new_text": "y"},
                    "NOT_FOUND",
                ),
                (
                    "在 ../outside.txt 把 x 换成 y，校验路径边界。",
                    {"path": "../outside.txt", "old_text": "x", "new_text": "y"},
                    "PERMISSION",
                ),
                (
                    f"在 {file} 中把空 old_text 换为 x，校验非法参数。",
                    {"path": file, "old_text": "", "new_text": "x"},
                    "INVALID_PARAM",
                ),
                (
                    f"将 {file} 中 beta-{variant} 换成 fixed，expected_mtime_ns=0。",
                    {
                        "path": file,
                        "old_text": f"beta-{variant}",
                        "new_text": "fixed",
                        "expected_mtime_ns": 0,
                    },
                    "CONFLICT",
                ),
            ],
            "Grep": [
                (f"搜索仓库里包含 beta-{variant} 的行。", {"query": f"beta-{variant}"}, "SUCCESS"),
                (
                    f"在 {file} 查找 alpha，最多返回 1 条。",
                    {"query": "alpha", "path": file, "max_results": 1},
                    "PARTIAL",
                ),
                (
                    f"用正则 ^beta 搜索 {file}。",
                    {"query": "^beta", "path": file, "regex": True},
                    "SUCCESS",
                ),
                (f"在 {file} 中查找 absent。", {"query": "absent", "path": file}, "SUCCESS"),
                (
                    "使用非法正则 [ 搜索代码，以校验错误。",
                    {"query": "[", "regex": True},
                    "INVALID_PARAM",
                ),
                (
                    f"在不存在的目录 absent-{variant} 下查找 alpha。",
                    {"query": "alpha", "path": f"absent-{variant}"},
                    "NOT_FOUND",
                ),
                (
                    "到 ../ 查找 secret，校验路径边界。",
                    {"query": "secret", "path": "../"},
                    "PERMISSION",
                ),
                ("查找普通文本 [，不要当正则。", {"query": "[", "regex": False}, "SUCCESS"),
                ("用空查询搜索代码，校验参数。", {"query": ""}, "INVALID_PARAM"),
                (
                    f"搜索 alpha-{variant}，最多返回 100 条。",
                    {"query": f"alpha-{variant}", "max_results": 100},
                    "SUCCESS",
                ),
            ],
            "Bash": [
                ("执行 python --version。", {"command": "python --version"}, "SUCCESS"),
                ("执行 git --version。", {"command": "git --version"}, "SUCCESS"),
                (
                    f'运行 python -c "print({variant})"。',
                    {"command": f'python -c "print({variant})"'},
                    "SUCCESS",
                ),
                (
                    '执行 python -c "import sys; sys.exit(3)"，检查非零退出码。',
                    {"command": 'python -c "import sys; sys.exit(3)"'},
                    "EXECUTION_ERROR",
                ),
                (
                    '运行 python -c "import time; time.sleep(5)"，超时 1 秒。',
                    {"command": 'python -c "import time; time.sleep(5)"', "timeout": 1},
                    "TIMEOUT",
                ),
                (
                    "测试危险命令拦截：rm -rf /，不要绕过策略。",
                    {"command": "rm -rf /"},
                    "PERMISSION",
                ),
                ("测试拦截 git reset --hard。", {"command": "git reset --hard"}, "PERMISSION"),
                (
                    "在 ../ 运行 echo x，检查 cwd 边界。",
                    {"command": "echo x", "cwd": "../"},
                    "PERMISSION",
                ),
                (
                    "执行 echo x，timeout=0，用于参数边界测试。",
                    {"command": "echo x", "timeout": 0},
                    "INVALID_PARAM",
                ),
                (
                    "执行 python -c \"import sys; sys.stderr.write('diagnostic')\"。",
                    {"command": "python -c \"import sys; sys.stderr.write('diagnostic')\""},
                    "SUCCESS",
                ),
            ],
            "TodoWrite": [
                (
                    f"建立任务计划：分析模块 {variant}，ID=1，正在进行；summary=plan。",
                    {"summary": "plan", "todos": todos},
                    "SUCCESS",
                ),
                ("清空待办，summary=empty。", {"summary": "empty", "todos": []}, "SUCCESS"),
                (
                    "把 ID=1 内容 fix 的任务标记 completed，summary=done。",
                    {
                        "summary": "done",
                        "todos": [{"id": "1", "content": "fix", "status": "completed"}],
                    },
                    "SUCCESS",
                ),
                (
                    "创建两个进行中的任务 a/b，ID=1/2，summary=conflict，以检查约束。",
                    {
                        "summary": "conflict",
                        "todos": [
                            {"id": str(i), "content": x, "status": "in_progress"}
                            for i, x in [(1, "a"), (2, "b")]
                        ],
                    },
                    "INVALID_PARAM",
                ),
                (
                    "创建两个相同 ID=1 的待办 a/b，summary=duplicate，以检查冲突。",
                    {
                        "summary": "duplicate",
                        "todos": [{"id": "1", "content": x} for x in ["a", "b"]],
                    },
                    "INVALID_PARAM",
                ),
                (
                    "创建 ID=1 内容 test 状态 invalid 的任务，summary=invalid，用于参数校验。",
                    {
                        "summary": "invalid",
                        "todos": [{"id": "1", "content": "test", "status": "invalid"}],
                    },
                    "INVALID_PARAM",
                ),
                (
                    "添加 ID=1 的空内容任务，summary=invalid，用于边界测试。",
                    {"summary": "invalid", "todos": [{"id": "1", "content": ""}]},
                    "INVALID_PARAM",
                ),
                (
                    "计划包含 ID=1 内容 inspect 已完成，ID=2 内容 fix 进行中，summary=next。",
                    {
                        "summary": "next",
                        "todos": [
                            {"id": "1", "content": "inspect", "status": "completed"},
                            {"id": "2", "content": "fix", "status": "in_progress"},
                        ],
                    },
                    "SUCCESS",
                ),
                (
                    "新建待办 ID=1 内容 review，默认 pending，summary=review。",
                    {"summary": "review", "todos": [{"id": "1", "content": "review"}]},
                    "SUCCESS",
                ),
                (
                    f"生成 5 个待办，ID 为 1..5，内容均为 module-{variant}，summary=batch。",
                    {
                        "summary": "batch",
                        "todos": [
                            {"id": str(i), "content": f"module-{variant}"} for i in range(1, 6)
                        ],
                    },
                    "SUCCESS",
                ),
            ],
        }
        for tool, definitions_for_tool in definitions.items():
            for index, (prompt, arguments, outcome) in enumerate(definitions_for_tool):
                required = {
                    "Read": ["path"],
                    "Write": ["path", "content"],
                    "Edit": ["path", "old_text", "new_text"],
                    "Grep": ["query"],
                    "Bash": ["command"],
                    "TodoWrite": ["summary", "todos"],
                }[tool]
                cases.append(
                    {
                        "id": f"{tool}-{variant * 10 + index + 1:02d}",
                        "prompt": prompt,
                        "expected_tool": tool,
                        "required_fields": required,
                        "arguments": arguments,
                        "expected_outcome": outcome,
                        "fixture": {file: content},
                        "binary": f"binary-{variant}.dat",
                    }
                )
    return cases


def context_tasks():
    tasks = []
    for i in range(12):
        function = f"calculate_{i:02d}"
        key = f"ORDER-{i:02d}-SAFE"
        prompts = [
            f"修复 calculator.py 的 {function}：应返回两数之和。约束：保留函数名 {function}，不引入依赖；验收标记 {key}。先建 TODO 再查代码。",
            "定位该函数和它的调用方，先只读。",
            "读取对应函数，不要重复读取没有变化的区域。",
            "检查 tests/test_calculator.py 的期望。",
            "读取 logs/build.log 尾部定位上一次失败。",
            "说明已经确认的根因与证据。",
            "在保持函数签名的前提下做最小修复。",
            "检查修改后的差异，确认没有引入依赖。",
            "运行 python -m pytest -q，记录真实退出码。",
            "如测试仍失败，读取错误并最小修正；已通过则报告结果。",
            "检查零值和负数的边界。",
            "为负数与零值补测试，保留现有断言。",
            "重新运行相关测试。",
            "检查代码审查中的异常路径。",
            "更新 TODO，明确完成项和待办。",
            "回顾之前失败的尝试，避免重复执行。",
            "列出已读取和已修改文件。",
            "确认最初的限制依然满足。",
            "检查是否还有未完成 TODO。",
            "输出最终结果，包含：最初的验收标记、函数名、不引入依赖约束、修改文件名、测试文件名、真实验证结果和 TODO 状态。",
        ]
        tasks.append(
            {
                "id": f"context-{i:02d}",
                "function": function,
                "marker": key,
                "prompts": prompts,
                "state_points": [key, function, "依赖", "calculator.py", "test_calculator.py"],
            }
        )
    return tasks


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    for name, rows in (
        ("tool_calling_cases.jsonl", tool_cases()),
        ("context_tasks.jsonl", context_tasks()),
    ):
        (DATA / name).write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
        )
    faults = [
        {"id": f"{kind}-{i:02d}", "kind": kind, "index": i}
        for kind in ("model_exception", "tool_process_exit", "append_process_exit")
        for i in range(10)
    ]
    (DATA / "fault_cases.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in faults), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
