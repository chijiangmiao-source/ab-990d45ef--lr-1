"""规范 LR(1) 文法解析、校验与项目集/动作表构造。

输入分隔规则（明确约定）：
- 终结符、非终结符列表：以空白、逗号或分号分隔的记号序列，支持多字符符号。
- 产生式：每行一条，形如 ``A -> α`` 或 ``A → α``；不支持 ``|`` 合并书写。
- 空产生式：右部留空，或右部仅书写 ε / epsilon / empty。
- 递归（左递归/右递归）按普通产生式处理，无特殊限制。
- 保留符号：``$`` 为文末展望符，``S′`` 为增文法起始符，均不得由用户声明。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

EOF = "$"
AUG = "S′"
EPSILON_TOKENS = {"ε", "epsilon", "EPSILON", "empty", "ε"}
_ARROW_RE = re.compile(r"->|→")
_SPLIT_RE = re.compile(r"[\s,;]+")
# 合法符号：非空白，且不含箭头、竖线、#、$ 等保留成分
_LEGAL_RE = re.compile(r"^[^\s|#→$]+$")
RESERVED_SYMBOLS = {EOF, AUG}


# ---------------------------------------------------------------- 数据结构


@dataclass(frozen=True)
class Rule:
    index: int  # 1 基编号，与对外展示一致；0 保留给增广产生式
    lhs: str
    rhs: tuple[str, ...]
    line: int


@dataclass(frozen=True)
class Item:
    """LR(1) 项目 [lhs -> rhs, dot 位置, lookahead]。"""

    lhs: str
    rhs: tuple[str, ...]
    dot: int
    lookahead: str
    rule_index: int

    def key(self) -> tuple:
        return (self.rule_index, self.dot, self.lookahead)

    def to_json(self) -> dict:
        return {
            "lhs": self.lhs,
            "body": list(self.rhs),
            "dot": self.dot,
            "lookahead": self.lookahead,
            "ruleIndex": self.rule_index,
            "text": _format_item(self.lhs, self.rhs, self.dot, self.lookahead),
        }


@dataclass
class ReviewError:
    code: str
    message: str
    line: Optional[int] = None
    symbol: Optional[str] = None

    def to_json(self) -> dict:
        out = {"code": self.code, "message": self.message}
        if self.line is not None:
            out["line"] = self.line
        if self.symbol is not None:
            out["symbol"] = self.symbol
        return out


@dataclass
class Grammar:
    terminals: list[str]
    nonterminals: list[str]
    start: str
    rules: list[Rule]
    symbols: list[str] = field(default_factory=list)


def _format_item(lhs: str, rhs: tuple[str, ...], dot: int, la: str) -> str:
    seq = list(rhs[:dot]) + ["·"] + list(rhs[dot:])
    if dot == len(rhs):
        seq = list(rhs) + ["·"]
    body = " ".join(seq) if seq else "·"
    return f"[{lhs} -> {body}, {la}]"


# ---------------------------------------------------------------- 解析


def _split_symbols(text: str) -> list[str]:
    return [t for t in _SPLIT_RE.split(text.strip()) if t]


def _is_legal_token(tok: str) -> bool:
    if tok in EPSILON_TOKENS or tok in RESERVED_SYMBOLS:
        return False
    if "->" in tok:
        return False
    return bool(_LEGAL_RE.match(tok))


def parse_input(raw: dict) -> tuple[Optional[Grammar], list[ReviewError], list[ReviewError]]:
    """解析原始文本输入；返回 (grammar|None, errors, warnings)。"""
    errors: list[ReviewError] = []
    warnings: list[ReviewError] = []

    terminals = _split_symbols(str(raw.get("terminals", "")))
    nonterminals = _split_symbols(str(raw.get("nonterminals", "")))
    start = str(raw.get("start", "")).strip()
    prod_text = str(raw.get("productions", ""))

    # 声明区词法检查
    for group_name, toks in (("终结符", terminals), ("非终结符", nonterminals)):
        for tok in toks:
            if not _is_legal_token(tok):
                errors.append(ReviewError(
                    "ILLEGAL_SYMBOL",
                    f"{group_name}声明中存在非法符号 {tok!r}：保留符号或含非法字符",
                    symbol=tok,
                ))

    # 声明重复
    for group_name, toks in (("终结符", terminals), ("非终结符", nonterminals)):
        seen: set[str] = set()
        for tok in toks:
            if tok in seen:
                warnings.append(ReviewError(
                    "DUPLICATE_DECLARATION", f"{group_name} {tok!r} 重复声明", symbol=tok
                ))
            seen.add(tok)

    overlap = set(terminals) & set(nonterminals)
    for tok in sorted(overlap):
        errors.append(ReviewError(
            "ILLEGAL_SYMBOL", f"符号 {tok!r} 同时被声明为终结符与非终结符", symbol=tok
        ))

    if not start:
        errors.append(ReviewError("INVALID_START", "未提供起始符"))
    elif not _is_legal_token(start):
        errors.append(ReviewError("ILLEGAL_SYMBOL", f"起始符 {start!r} 为非法符号", symbol=start))
    elif start not in nonterminals:
        errors.append(ReviewError(
            "UNDEFINED_REFERENCE", f"起始符 {start!r} 不是已声明的非终结符", symbol=start
        ))

    declared = set(terminals) | set(nonterminals)
    rules: list[Rule] = []
    seen_rules: dict[tuple[str, tuple[str, ...]], int] = {}

    for lineno, raw_line in enumerate(prod_text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = _ARROW_RE.split(line, maxsplit=1)
        if len(parts) != 2:
            errors.append(ReviewError(
                "ILLEGAL_SYMBOL",
                f"第 {lineno} 行缺少产生式分隔符 '->'：{raw_line!r}",
                line=lineno,
            ))
            continue
        lhs_toks = _split_symbols(parts[0])
        if len(lhs_toks) != 1:
            errors.append(ReviewError(
                "ILLEGAL_SYMBOL",
                f"第 {lineno} 行左部必须恰有一个符号，实际为 {lhs_toks}",
                line=lineno,
            ))
            continue
        lhs = lhs_toks[0]
        if not _is_legal_token(lhs):
            errors.append(ReviewError(
                "ILLEGAL_SYMBOL", f"第 {lineno} 行左部符号 {lhs!r} 非法", line=lineno, symbol=lhs
            ))
            continue

        rhs_toks = _split_symbols(parts[1])
        if rhs_toks and rhs_toks[0] in EPSILON_TOKENS:
            if len(rhs_toks) != 1:
                errors.append(ReviewError(
                    "ILLEGAL_SYMBOL",
                    f"第 {lineno} 行空产生式标记 ε 不能与其他符号混用",
                    line=lineno,
                ))
                continue
            rhs_toks = []
        for tok in rhs_toks:
            if not _is_legal_token(tok):
                hint = "（竖线合并书写不受支持，请拆成多行）" if tok == "|" else ""
                errors.append(ReviewError(
                    "ILLEGAL_SYMBOL",
                    f"第 {lineno} 行存在非法符号 {tok!r}{hint}",
                    line=lineno,
                    symbol=tok,
                ))

        if errors and errors[-1].line == lineno and errors[-1].code == "ILLEGAL_SYMBOL":
            continue

        if lhs in terminals:
            errors.append(ReviewError(
                "UNDEFINED_REFERENCE",
                f"第 {lineno} 行左部 {lhs!r} 是终结符，不能作为产生式左部",
                line=lineno,
                symbol=lhs,
            ))
        elif lhs not in nonterminals:
            errors.append(ReviewError(
                "UNDEFINED_REFERENCE",
                f"第 {lineno} 行左部 {lhs!r} 未在非终结符列表中声明",
                line=lineno,
                symbol=lhs,
            ))
        for tok in rhs_toks:
            if tok not in declared:
                errors.append(ReviewError(
                    "UNDEFINED_REFERENCE",
                    f"第 {lineno} 行符号 {tok!r} 未在终结符或非终结符中声明",
                    line=lineno,
                    symbol=tok,
                ))

        sig = (lhs, tuple(rhs_toks))
        if sig in seen_rules:
            errors.append(ReviewError(
                "DUPLICATE_PRODUCTION",
                f"第 {lineno} 行产生式 {lhs} -> {' '.join(rhs_toks) or 'ε'} "
                f"与第 {seen_rules[sig]} 行完全重复",
                line=lineno,
                symbol=lhs,
            ))
            continue
        seen_rules[sig] = lineno
        rules.append(Rule(len(rules) + 1, lhs, tuple(rhs_toks), lineno))

    # 起始规则可达性
    if start and start in nonterminals:
        if not any(r.lhs == start for r in rules):
            errors.append(ReviewError(
                "UNREACHABLE_START",
                f"起始符 {start!r} 没有任何产生式，起始规则不可达",
                symbol=start,
            ))

    # 不可达非终结符 / 未使用终结符（警告，不阻断）
    if rules and start in {r.lhs for r in rules}:
        reachable: set[str] = {start}
        changed = True
        by_lhs: dict[str, list[Rule]] = {}
        for r in rules:
            by_lhs.setdefault(r.lhs, []).append(r)
        while changed:
            changed = False
            for nt in list(reachable):
                for r in by_lhs.get(nt, []):
                    for s in r.rhs:
                        if s in nonterminals and s not in reachable:
                            reachable.add(s)
                            changed = True
        for nt in nonterminals:
            if nt not in reachable:
                warnings.append(ReviewError(
                    "UNREACHABLE_NONTERMINAL", f"非终结符 {nt!r} 从起始符不可达", symbol=nt
                ))
        used = {s for r in rules for s in r.rhs}
        for t in terminals:
            if t not in used:
                warnings.append(ReviewError("UNUSED_TERMINAL", f"终结符 {t!r} 未在任何产生式中出现", symbol=t))

    if errors:
        return None, errors, warnings

    symbols = terminals + [nt for nt in nonterminals]
    return Grammar(terminals, nonterminals, start, rules, symbols), errors, warnings


# ---------------------------------------------------------------- FIRST / nullable


def compute_nullable_first(g: Grammar) -> tuple[set[str], dict[str, frozenset[str]]]:
    nullable: set[str] = set()
    first: dict[str, set[str]] = {t: {t} for t in g.terminals}
    first[EOF] = {EOF}
    for nt in g.nonterminals:
        first.setdefault(nt, set())

    by_lhs: dict[str, list[Rule]] = {}
    for r in g.rules:
        by_lhs.setdefault(r.lhs, []).append(r)

    changed = True
    while changed:
        changed = False
        for nt in g.nonterminals:
            for r in by_lhs.get(nt, []):
                if not r.rhs:
                    if nt not in nullable:
                        nullable.add(nt)
                        changed = True
                    continue
                all_null_prefix = True
                for sym in r.rhs:
                    add = first.get(sym, set()) - nullable
                    if not add <= first[nt]:
                        first[nt] |= add
                        changed = True
                    if sym not in nullable:
                        all_null_prefix = False
                        break
                if all_null_prefix and nt not in nullable:
                    nullable.add(nt)
                    changed = True
    return nullable, {k: frozenset(v) for k, v in first.items()}


def first_sequence(seq: tuple[str, ...], first: dict[str, frozenset], nullable: set[str]) -> frozenset[str]:
    out: set[str] = set()
    for sym in seq:
        out |= first.get(sym, frozenset()) - nullable
        if sym not in nullable:
            return frozenset(out)
    return frozenset(out)  # 全可空：不含 ε，调用方自行追加后继展望符


# ---------------------------------------------------------------- LR(1) 项目集


def _closure(
    kernel: frozenset[Item],
    by_lhs: dict[str, list[Rule]],
    first: dict[str, frozenset],
    nullable: set[str],
) -> frozenset[Item]:
    items: set[Item] = set(kernel)
    pending = list(kernel)
    while pending:
        it = pending.pop()
        if it.dot >= len(it.rhs):
            continue
        b = it.rhs[it.dot]
        if b not in by_lhs:
            continue
        beta_a = it.rhs[it.dot + 1 :] + (it.lookahead,)
        lookaheads = set(first_sequence(beta_a, first, nullable))
        # 若 βa 整体可空（β 全可空且末尾展望符…… 末尾是终结符，故 β 全可空时补 a）
        if all(s in nullable for s in it.rhs[it.dot + 1 :]):
            lookaheads.add(it.lookahead)
        for r in by_lhs[b]:
            for la in sorted(lookaheads):
                ni = Item(b, r.rhs, 0, la, r.index)
                if ni not in items:
                    items.add(ni)
                    pending.append(ni)
    return frozenset(items)


def _goto(
    state: frozenset[Item],
    sym: str,
    by_lhs: dict[str, list[Rule]],
    first: dict[str, frozenset],
    nullable: set[str],
) -> frozenset[Item]:
    kernel = {Item(it.lhs, it.rhs, it.dot + 1, it.lookahead, it.rule_index)
              for it in state if it.dot < len(it.rhs) and it.rhs[it.dot] == sym}
    if not kernel:
        return frozenset()
    return _closure(frozenset(kernel), by_lhs, first, nullable)


@dataclass
class Conflict:
    state: int
    lookahead: str
    kind: str
    items: list[Item]
    actions: list[str]
    prefix: list[str]

    def to_json(self) -> dict:
        return {
            "state": self.state,
            "lookahead": self.lookahead,
            "kind": self.kind,
            "kindText": "移进/归约" if self.kind == "shift_reduce" else "归约/归约",
            "items": [it.to_json() for it in self.items],
            "actions": self.actions,
            "prefix": self.prefix,
            "evidence": (
                f"状态 {self.state} 可由活前缀 {(' '.join(self.prefix) or 'ε')!r} 到达；"
                f"读入展望符 {self.lookahead!r} 时同时要求 "
                f"{' 与 '.join(self.actions)}，动作互斥。"
            ),
        }


def build_canonical(g: Grammar) -> dict:
    nullable, first = compute_nullable_first(g)
    by_lhs: dict[str, list[Rule]] = {}
    for r in g.rules:
        by_lhs.setdefault(r.lhs, []).append(r)

    aug_rule = Rule(0, AUG, (g.start,), 0)
    start_kernel = frozenset({Item(AUG, (g.start,), 0, EOF, 0)})
    i0 = _closure(start_kernel, {**by_lhs, AUG: [aug_rule]}, first, nullable)

    # BFS 构造，符号按声明序处理，保证编号稳定
    states: list[frozenset[Item]] = [i0]
    index: dict[frozenset[Item], int] = {i0: 0}
    gotos: list[dict[str, int]] = [{}]
    prefixes: list[list[str]] = [[]]
    queue = [0]
    head = 0
    while head < len(queue):
        sid = queue[head]
        head += 1
        for sym in g.symbols:
            target = _goto(states[sid], sym, {**by_lhs, AUG: [aug_rule]}, first, nullable)
            if not target:
                continue
            if target not in index:
                index[target] = len(states)
                states.append(target)
                gotos.append({})
                prefixes.append(prefixes[sid] + [sym])
                queue.append(index[target])
            gotos[sid][sym] = index[target]

    # 动作表 + 首个冲突（状态编号 -> 展望符声明序 -> 项目稳定序）
    la_order = g.terminals + [EOF]
    la_rank = {s: i for i, s in enumerate(la_order)}
    rule_text = {0: f"{AUG} -> {g.start}"}
    for r in g.rules:
        rule_text[r.index] = f"{r.lhs} -> {' '.join(r.rhs) or 'ε'}"

    action_rows: list[dict[str, dict]] = []
    first_conflict: Optional[Conflict] = None
    for sid, state in enumerate(states):
        cells: dict[str, list[tuple[str, Item]]] = {}
        ordered = sorted(state, key=lambda it: (it.rule_index, it.dot, la_rank.get(it.lookahead, 999)))
        for it in ordered:
            if it.dot < len(it.rhs):
                sym = it.rhs[it.dot]
                if sym in g.terminals and sym in gotos[sid]:
                    label = f"s{gotos[sid][sym]}"
                    cells.setdefault(sym, []).append((label, it))
            else:
                if it.lhs == AUG and it.lookahead == EOF:
                    label = "acc"
                else:
                    label = f"r{it.rule_index}"
                cells.setdefault(it.lookahead, []).append((label, it))

        row: dict[str, dict] = {}
        for sym in la_order:
            if sym not in cells:
                continue
            uniq: list[tuple[str, Item]] = []
            for label, it in cells[sym]:
                if not any(u[0] == label for u in uniq):
                    uniq.append((label, it))
            if len(uniq) >= 2:
                kinds = {("s" if u[0].startswith("s") else "r" if u[0].startswith("r") else "a") for u in uniq}
                kind = "shift_reduce" if "s" in kinds else "reduce_reduce"
                row[sym] = {"conflict": True, "actions": [u[0] for u in uniq]}
                if first_conflict is None:
                    first_conflict = Conflict(
                        state=sid,
                        lookahead=sym,
                        kind=kind,
                        items=[u[1] for u in uniq[:2]],
                        actions=[f"{u[0]}（{_action_hint(u[0], rule_text)}）" for u in uniq[:2]],
                        prefix=prefixes[sid],
                    )
            else:
                row[sym] = {"action": uniq[0][0]}
        action_rows.append(row)

    return {
        "nullable": [nt for nt in g.nonterminals if nt in nullable],
        "first": {
            s: sorted(first.get(s, frozenset()), key=lambda x: la_rank.get(x, 999))
            for s in g.nonterminals
        },
        "states": [
            {
                "id": sid,
                "prefix": prefixes[sid],
                "items": [it.to_json() for it in sorted(states[sid], key=lambda i: i.key())],
                "goto": gotos[sid],
            }
            for sid in range(len(states))
        ],
        "actionTable": {
            "lookaheads": la_order,
            "rows": action_rows,
        },
        "rules": [
            {"index": r.index, "lhs": r.lhs, "body": list(r.rhs), "line": r.line,
             "text": f"{r.lhs} -> {' '.join(r.rhs) or 'ε'}"}
            for r in g.rules
        ],
        "conflict": first_conflict.to_json() if first_conflict else None,
        "isLalrSafe": True,  # 规范 LR(1) 无冲突即文法可用
    }


def _action_hint(label: str, rule_text: dict[int, str]) -> str:
    if label.startswith("r"):
        return f"归约于 {rule_text[int(label[1:])]}"
    if label == "acc":
        return "接受"
    return f"移进至状态 {label[1:]}"


# ---------------------------------------------------------------- 对外入口


def review(raw: dict) -> dict:
    grammar, errors, warnings = parse_input(raw)
    result = {
        "ok": not errors,
        "errors": [e.to_json() for e in errors],
        "warnings": [w.to_json() for w in warnings],
        "grammar": None,
        "analysis": None,
    }
    if grammar is None:
        return result
    result["grammar"] = {
        "terminals": grammar.terminals,
        "nonterminals": grammar.nonterminals,
        "start": grammar.start,
    }
    analysis = build_canonical(grammar)
    result["analysis"] = analysis
    if analysis["conflict"] is not None:
        result["ok"] = False
    return result
