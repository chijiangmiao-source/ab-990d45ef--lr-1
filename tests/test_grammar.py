"""LR(1) 引擎单元测试：解析校验、nullable/FIRST、无冲突文法与两类冲突。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.grammar import review, parse_input, compute_nullable_first, EOF  # noqa: E402


def _codes(result):
    return [e["code"] for e in result["errors"]]


def _warn_codes(result):
    return [w["code"] for w in result["warnings"]]


class ParsingTests(unittest.TestCase):
    def test_multichar_symbols_and_separators(self):
        g, errs, _ = parse_input({
            "terminals": "int, float; id  num",
            "nonterminals": "program, stmt",
            "start": "program",
            "productions": "program -> stmt id\nstmt -> ε\n",
        })
        self.assertEqual(errs, [])
        self.assertEqual(g.terminals, ["int", "float", "id", "num"])
        self.assertEqual(g.nonterminals, ["program", "stmt"])
        self.assertEqual(g.rules[1].rhs, ())

    def test_illegal_symbol_reserved(self):
        result = review({
            "terminals": "$ a",
            "nonterminals": "S",
            "start": "S",
            "productions": "S -> a\n",
        })
        self.assertIn("ILLEGAL_SYMBOL", _codes(result))

    def test_undefined_reference_rhs(self):
        result = review({
            "terminals": "a",
            "nonterminals": "S",
            "start": "S",
            "productions": "S -> a b\n",
        })
        self.assertIn("UNDEFINED_REFERENCE", _codes(result))
        self.assertEqual(result["errors"][0]["symbol"], "b")

    def test_duplicate_production(self):
        result = review({
            "terminals": "a",
            "nonterminals": "S",
            "start": "S",
            "productions": "S -> a\nS -> a\n",
        })
        self.assertIn("DUPLICATE_PRODUCTION", _codes(result))
        self.assertEqual(result["errors"][0]["line"], 2)

    def test_unreachable_start(self):
        result = review({
            "terminals": "a",
            "nonterminals": "S A",
            "start": "S",
            "productions": "A -> a\n",
        })
        self.assertIn("UNREACHABLE_START", _codes(result))

    def test_start_missing_production_is_error_not_crash(self):
        result = review({
            "terminals": "a",
            "nonterminals": "S",
            "start": "",
            "productions": "",
        })
        self.assertFalse(result["ok"])

    def test_pipe_is_illegal_no_alt_syntax(self):
        result = review({
            "terminals": "a b",
            "nonterminals": "S",
            "start": "S",
            "productions": "S -> a | b\n",
        })
        self.assertIn("ILLEGAL_SYMBOL", _codes(result))


class NullableFirstTests(unittest.TestCase):
    def test_nullable_and_first_with_epsilon_chain(self):
        g, _, _ = parse_input({
            "terminals": "a b c",
            "nonterminals": "S A B",
            "start": "S",
            "productions": "S -> A a\nA -> B\nB -> ε\n",
        })
        nullable, first = compute_nullable_first(g)
        self.assertEqual(nullable, {"A", "B"})
        self.assertEqual(set(first["S"]), {"a"})
        # A 只能推出 ε：FIRST 终结符集合为空，可空性由 nullable 表示
        self.assertEqual(set(first["A"]), set())
        self.assertEqual(set(first["B"]), set())


class ConflictFreeTests(unittest.TestCase):
    CONFLICT_FREE = {
        "terminals": "int float = + ( ) ;",
        "nonterminals": "S T D L",
        "start": "S",
        "productions": (
            "S -> T ;\n"
            "T -> D\n"
            "D -> L = int\n"
            "L -> L + float\n"
            "L -> float\n"
        ),
    }

    def test_no_conflict_review_ok(self):
        result = review(self.CONFLICT_FREE)
        self.assertTrue(result["ok"], msg=str(result["errors"]))
        self.assertIsNone(result["analysis"]["conflict"])
        self.assertGreater(len(result["analysis"]["states"]), 1)

    def test_action_table_has_shift_reduce_accept_and_goto(self):
        result = review(self.CONFLICT_FREE)
        a = result["analysis"]
        labels = set()
        for row in a["actionTable"]["rows"]:
            for cell in row.values():
                labels.add(cell.get("action") or tuple(cell.get("actions", [])))
        self.assertIn("acc", labels)
        self.assertTrue(any(isinstance(x, str) and x.startswith("s") for x in labels))
        self.assertTrue(any(isinstance(x, str) and x.startswith("r") for x in labels))
        # goto 含非终结符转移
        gotos = [tuple(st["goto"]) for st in a["states"]]
        self.assertTrue(any(g for g in gotos))

    def test_stable_state_numbering(self):
        r1 = review(self.CONFLICT_FREE)
        r2 = review(self.CONFLICT_FREE)
        self.assertEqual(
            [[it["text"] for it in s["items"]] for s in r1["analysis"]["states"]],
            [[it["text"] for it in s["items"]] for s in r2["analysis"]["states"]],
        )

    def test_left_recursion_supported(self):
        result = review({
            "terminals": "a +",
            "nonterminals": "E",
            "start": "E",
            "productions": "E -> E + a\nE -> a\n",
        })
        self.assertTrue(result["ok"], msg=str(result["errors"]))

    def test_epsilon_grammar_lr1(self):
        result = review({
            "terminals": "a",
            "nonterminals": "S A",
            "start": "S",
            "productions": "S -> A a\nA -> ε\n",
        })
        self.assertTrue(result["ok"], msg=str(result["errors"]))


class ShiftReduceConflictTests(unittest.TestCase):
    DANGLING_ELSE = {
        "terminals": "if then else expr",
        "nonterminals": "S E",
        "start": "S",
        "productions": (
            "S -> if E then S\n"
            "S -> if E then S else S\n"
            "S -> expr\n"
            "E -> expr\n"
        ),
    }

    def test_dangling_else_conflict_reported(self):
        result = review(self.DANGLING_ELSE)
        c = result["analysis"]["conflict"]
        self.assertIsNotNone(c)
        self.assertFalse(result["ok"])
        self.assertEqual(c["kind"], "shift_reduce")
        self.assertEqual(c["lookahead"], "else")
        self.assertEqual(len(c["items"]), 2)
        self.assertEqual(len(c["actions"]), 2)
        self.assertTrue(any("移进" in a for a in c["actions"]))
        self.assertTrue(any("归约" in a for a in c["actions"]))
        self.assertTrue(c["prefix"])
        self.assertIn("活前缀", c["evidence"])

    def test_first_conflict_lowest_state_is_stable(self):
        r1 = review(self.DANGLING_ELSE)
        r2 = review(self.DANGLING_ELSE)
        c1, c2 = r1["analysis"]["conflict"], r2["analysis"]["conflict"]
        self.assertEqual((c1["state"], c1["lookahead"]), (c2["state"], c2["lookahead"]))
        self.assertEqual([a for a in c1["actions"]], [a for a in c2["actions"]])


class ReduceReduceConflictTests(unittest.TestCase):
    def test_reduce_reduce_conflict(self):
        # A、B 都可空，S -> A a 与 S -> B a，在状态中展望 a 时双归约
        result = review({
            "terminals": "a",
            "nonterminals": "S A B",
            "start": "S",
            "productions": (
                "S -> A a\n"
                "S -> B a\n"
                "A -> ε\n"
                "B -> ε\n"
            ),
        })
        c = result["analysis"]["conflict"]
        self.assertIsNotNone(c)
        self.assertEqual(c["kind"], "reduce_reduce")
        self.assertEqual(c["lookahead"], "a")
        rule_ids = sorted(
            int(a.split("r")[1].split("（")[0])
            for a in c["actions"]
        )
        self.assertEqual(len(rule_ids), 2)
        self.assertIn("归约", c["actions"][0])
        self.assertTrue(c["evidence"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
