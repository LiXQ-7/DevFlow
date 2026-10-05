from pathlib import Path

CATALOG = {
    "debug": (
        "复现异常、收集证据、最小修复与回归",
        ("bug", "debug", "异常", "报错", "失败", "排查", "修复"),
    ),
    "code-review": ("检查正确性、边界、并发和资源风险", ("review", "审查", "审阅", "风险")),
    "unit-test": ("生成覆盖正常、边界和异常的可重复单元测试", ("test", "测试", "用例")),
    "git-commit": ("基于真实差异生成规范的提交说明", ("commit", "提交", "git diff")),
}


class SkillsLoader:
    def __init__(self):
        self.directory = Path(__file__).parent / "builtin"

    def metadata(self):
        return "\n".join(f"{name}: {description}" for name, (description, _) in CATALOG.items())

    def match(self, text):
        text = text.casefold()
        return [name for name, (_, keys) in CATALOG.items() if any(key in text for key in keys)]

    def load(self, name):
        if name not in CATALOG:
            raise ValueError("Unknown skill")
        return (self.directory / name / "SKILL.md").read_text(encoding="utf-8")
