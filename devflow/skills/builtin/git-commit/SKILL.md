---
name: git-commit
description: 基于真实差异生成规范的提交说明
---

获准执行命令后先查看 git status、git diff 和已有提交风格，确认变更范围。
依据实际差异选择 feat/fix/refactor/test/docs/chore，格式为 type(scope): 简洁动词描述。
正文说明问题、行为变化、验证结果与必要风险。未运行验证必须注明。
默认只生成提交说明；只有用户明确要求提交时才执行 git add 和 git commit。
不提交 .env、密钥、会话正文或巨量输出；不自动 push、不 reset --hard、不覆盖用户改动。
