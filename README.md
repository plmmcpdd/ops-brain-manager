# 运营大脑工作区管理器

这是一个本地、命令行式的薄层客户工作区登记器。它不介入 `cheat-on-content` 的任何内容判断或运行逻辑。

## 边界

- `.ops-brain/clients.json` 只保存客户显示名、稳定 ID、工作区路径、状态与来源等管理元数据，不保存内容业务数据。
- 每个客户工作区继续保存并运行原版 Cheat 数据；本工具不会读取或生成选题、评分、预测、Script、Hook、Rubric、Persona、Benchmark 或复盘数据。
- `/home/rong/tools/cheat-on-content` 是唯一的只读全局 Skill Runtime，不会被复制、克隆或绑定到任何客户。
- 不提供数据库、Web UI、RBAC、自动发布或跨客户学习。

## WSL Ubuntu-E 使用

在本项目目录中运行：

```bash
python3 ops_brain.py create --name "客户 A" --workspace /home/rong/workspaces/client-a
python3 ops_brain.py attach --name "客户 B" --workspace /home/rong/workspaces/client-b
python3 ops_brain.py list
python3 ops_brain.py list --all
python3 ops_brain.py show --client client-a
python3 ops_brain.py open --client client-a
python3 ops_brain.py archive --client client-a
python3 ops_brain.py restore --client client-a
python3 ops_brain.py doctor
```

`create` 只创建新的空目录并登记；如果目标目录已经存在，必须为空。它不会执行 Git clone、不会运行 `cheat-init`、不会创建 `.cheat-state.json`，也不会生成任何 Cheat 文件。

`attach` 只登记一个已经存在的目录，绝不向该目录写入标记或内容。`archive` 只更新 Registry 状态，不移动或删除工作区；归档路径仍被保留，不能分配给其他客户。

客户工作区必须彼此独立：两个客户不能使用同一路径，也不能让任一路径成为另一工作区的父目录或子目录（包括符号链接解析后的真实路径）。`list --all` 用于同时查看 active 与 archived 客户。

进入客户工作区后，由用户自行手动初始化全局 Runtime：

```bash
cd /home/rong/workspaces/client-a
# 在此处按 cheat-on-content 的原始方式手工初始化和运行。
```

`open` 默认不会启动任何程序，只输出客户、绝对路径以及可复制的 `cd`、`code`、`claude-deepseek` 命令。只有显式指定时才启动程序：

```bash
python3 ops_brain.py open --client client-a --app code
```

`doctor` 完全只读。退出码为：`0` 无问题、`1` 发现问题、`2` 无法安全读取 Registry。旧 Registry 中没有 `origin` 的客户会被标为 `legacy`，只提示人工确认，不会擅自推断或改写。

## Windows（次要示例）

在 PowerShell 中可使用：

```powershell
python .\ops_brain.py list
python .\ops_brain.py doctor
```

请优先在 WSL Ubuntu-E 中管理 WSL 路径。

`--registry <path>` 可用于测试或高级的本地登记册隔离；日常使用默认的 `.ops-brain/clients.json` 即可。

## 验证

```bash
python3 -m unittest discover -s tests -v
```
