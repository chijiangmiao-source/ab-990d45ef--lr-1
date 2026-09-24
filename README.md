# 束线控制文法 LR(1) 复核服务

运行组在上线前粘贴文法（终结符、非终结符、起始符、产生式）发起复核，
服务构造规范 LR(1) 项目集，判定是否存在移进/归约、归约/归约冲突，并给出
可核查的首个冲突证据。

## 分隔规则

- 终结符 / 非终结符列表：以空白、逗号或分号分隔，**支持多字符符号**（如 `int`、`float`）。
- 产生式：每行一条，形如 `A -> α`（也支持 Unicode 箭头 `→`），不支持 `|` 合并书写。
- **空产生式**：右部留空，或仅书写 `ε` / `epsilon`。
- **递归**（左递归、右递归）按普通产生式处理，无限制。
- 保留符号：`$`（文末展望符）、`S′`（增广起始符）不可声明。

## 复核内容

- 输入定位：非法符号、未定义引用、重复产生式、起始规则不可达（另有不可达非终结符、
  未使用终结符等非阻断提示）。
- 精确计算 nullable、FIRST、LR(1) 闭包与 goto，BFS 构造**稳定编号**的规范项目集。
- 无冲突：展示项目集与 LR(1) 动作表（移进 `sN`、归约 `rN`、接受 `acc`）。
- 有冲突：按状态编号、展望符、动作顺序给出**首个冲突**——状态、竞争项目、
  两项动作与活前缀证据。
- 页面草稿自动保留在浏览器本地；修改草稿或取消计算后，过期结果明确标注，
  不会改写当前结论。

## 本地运行（仅需 Python 3.11 标准库）

```bash
python3 -m app.server
# 复核页 http://localhost:8080/
# 健康路径 http://localhost:8080/healthz
```

## Compose 运行

```bash
docker compose up --build -d web          # 复核页与 API
docker compose run --rm verify            # 一次性验收，退出码即结果
```

`verify` 为一次性服务：等待 `web` 健康后执行代码测试、页面构建检查与
API/HTTP 冒烟，执行完毕退出，`0` 通过 / `非 0` 失败。

## 一次性验收（不依赖 Docker）

```bash
./verify                    # 本地临时端口起服务，跑完即收
./verify --base-url URL     # 对指定地址冒烟
echo $?                     # 查看验收退出码
```

## API

`POST /api/review`

```json
{
  "terminals": "if then else expr",
  "nonterminals": "S E",
  "start": "S",
  "productions": "S -> if E then S\nS -> if E then S else S\nS -> expr\nE -> expr"
}
```

返回 `ok`、`errors`、`warnings`、`grammar` 与 `analysis`
（nullable / FIRST / 稳定编号项目集 / 动作表 / 首个冲突证据）。

## 代码布局

- `app/grammar.py`：解析、校验、nullable/FIRST、规范 LR(1) 项目集与动作表。
- `app/server.py`：标准库 HTTP 服务（`/`、`/healthz`、`/api/review`）。
- `app/static/`：可访问复核页（跳转链接、aria-live、焦点样式、草稿留存）。
- `tests/`：引擎与 HTTP/页面测试（`python3 -m unittest discover -s tests`）。
- `scripts/smoke_http.py`：API/HTTP 冒烟。
- `verify`：一次性验收入口。
