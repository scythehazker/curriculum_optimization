from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple, Union


class CourseConstraintsTokenType(Enum):
    CODE = 1
    NAME = 2
    LPAR = 3
    RPAR = 4
    A = 5
    ALEBO = 6
    BEGIN = 7
    END = 8
    DASH = 9


Clause = Set[str]
CNF = List[Clause]


@dataclass(frozen=True)
class Node:
    pass


@dataclass(frozen=True)
class Var(Node):
    name: str


@dataclass(frozen=True)
class And(Node):
    left: Node
    right: Node


@dataclass(frozen=True)
class Or(Node):
    left: Node
    right: Node


class CourseConstraintsCNFBuilder:
    """Prekladá vyčistenú postupnosť tokenov ohraničení do AST a následne do CNF."""

    OP_AND = "AND"
    OP_OR = "OR"

    def __init__(self, tokens: List[Tuple[str, CourseConstraintsTokenType]]) -> None:
        self.tokens = tokens

    def to_cnf(self) -> CNF:
        ast = self.to_ast()
        if ast is None:
            return []
        return self.ast_to_cnf(ast)

    def to_ast(self) -> Optional[Node]:
        """
        Pomocou postfixneho zapisu zbavi sa zatvoriek a vytvori AST strom.
        Ak sa to neda, zavola ValueError.
        """
        if not self.tokens:
            return None

        output: List[Union[str, Var]] = []
        ops: List[str] = []

        def push_op(op: str) -> None:
            while ops:
                top = ops[-1]
                if top == "(":
                    break
                output.append(ops.pop())
            ops.append(op)

        for symbol, token_type in self.tokens:
            if token_type == CourseConstraintsTokenType.CODE:
                output.append(Var(symbol))
            elif token_type == CourseConstraintsTokenType.A:
                push_op(self.OP_AND)
            elif token_type == CourseConstraintsTokenType.ALEBO:
                push_op(self.OP_OR)
            elif token_type == CourseConstraintsTokenType.LPAR:
                ops.append("(")
            elif token_type == CourseConstraintsTokenType.RPAR:
                while ops and ops[-1] != "(":
                    output.append(ops.pop())
                if not ops:
                    raise ValueError("Nesprávne spárované zátvorky.")
                ops.pop()
            else:
                raise ValueError(f"Neočakávaný typ tokenu v to_ast: {token_type}")

        while ops:
            op = ops.pop()
            if op == "(":
                raise ValueError("Nesprávne spárované zátvorky na konci.")
            output.append(op)

        stack: List[Node] = []
        for item in output:
            if isinstance(item, Var):
                stack.append(item)
                continue

            if len(stack) < 2:
                raise ValueError(f"{item} bez dvoch operandov.")
            right = stack.pop()
            left = stack.pop()
            stack.append(And(left, right) if item == self.OP_AND else Or(left, right))

        if len(stack) != 1:
            raise ValueError("Neplatný výraz: zostali nespracované operandy.")
        return stack[0]

    def ast_to_cnf(self, node: Node) -> CNF:
        if isinstance(node, Var):
            return [{node.name}]
        if isinstance(node, And):
            return self.ast_to_cnf(node.left) + self.ast_to_cnf(node.right)
        if isinstance(node, Or):
            return self._distribute(self.ast_to_cnf(node.left), self.ast_to_cnf(node.right))
        raise TypeError(f"Neznámy typ uzla: {type(node)}")

    def _distribute(self, a: CNF, b: CNF) -> CNF:
        out: CNF = []
        for clause_a in a:
            for clause_b in b:
                out.append(set(clause_a) | set(clause_b))
        return out


class CourseConstraints:
    """
    Obsahuje prerekvizity a antirekvizity predmetu, vratane prace po ich spracovaniu do CNF tvaru.
    """

    def __init__(self, prerequisites: str, antirequisites: str) -> None:
        self.prerequisites = prerequisites.strip()
        self.antirequisites = antirequisites.strip()

        prereq_tokens, antireq_tokens = self.clear_course_constraints()
        self._prerequisite_cnf: CNF = self._build_prerequisite_cnf(prereq_tokens)
        self._antirequisites: Set[str] = self._tokens_to_antirequisites(antireq_tokens)

    def assign_tokens(
        self,
        splitted: List[str],
        tokens: List[CourseConstraintsTokenType],
        idx: int = 0,
    ) -> List[CourseConstraintsTokenType]:
        """
        Pomocou skusania roznych moznosti priradi tokeny pre retazec prerekvizit a vylucujucich predmetov.
        Ak ziadne priradenie sa nenaslo, vracia ValueError, inak najdene priradenie - postupnost tokenov.
        """

        class S(Enum):
            """Stavy backtracking-automata"""

            BEGIN = 1  # zaciatocny stav
            AFTER_LPAR = 2  # stav po lavej zatvorke (
            AFTER_CONJ = 3  # stav po spojke a/alebo
            AFTER_CODE = 4  # stav po kode predmeta
            AFTER_SEP_DASH = 5  # stav po pomlcke po kode predmeta
            IN_NAME = 6  # stav nazvu predmeta
            AFTER_RPAR = 7  # stav po pravej zatvorke )

        def doesnt_look_like_conj_in_name(pos: int) -> bool:
            """
            Vracia True, ak spojka na indexe `pos` nevyzera ako spojka vnutri nazvu predmetu.
            Predpokladame, ze kod predmetu vzdy obsahuje sluzobne symboly alebo cisla.
            """
            if pos + 1 >= len(splitted):
                return False
            nxt = splitted[pos + 1]
            if nxt == "(":
                return True
            return any(ch.isdigit() for ch in nxt) or any(ch in "/._-" for ch in nxt)

        def try_parse(require_dash: bool) -> Optional[List[CourseConstraintsTokenType]]:
            """
            Rekurzivne skusa priradit tokeny zoznamu objektov z prerekvizit a antirekvizit.
            Ak ziadne priradenie sa nenajde, vrati None, inak vrati najdenu postupnost tokenov.
            """
            memo: Dict[Tuple[int, S, int], Optional[List[CourseConstraintsTokenType]]] = {}

            def cand(i: int, state: S) -> List[Tuple[CourseConstraintsTokenType, S]]:
                """
                Na zaklade daneho tokenu a stavu automatu vracia tokeny a stavy, ktore mozu ist po ne.
                """
                raw = splitted[i]
                lower_word = raw.lower()

                if raw == "(":
                    if state in (S.BEGIN, S.AFTER_CONJ, S.AFTER_LPAR):
                        return [(CourseConstraintsTokenType.LPAR, S.AFTER_LPAR)]
                    return []

                if raw == ")":
                    if state in (S.IN_NAME, S.AFTER_RPAR):
                        return [(CourseConstraintsTokenType.RPAR, S.AFTER_RPAR)]
                    return []

                if raw == "-":
                    if state == S.AFTER_CODE:
                        return (
                            [(CourseConstraintsTokenType.DASH, S.AFTER_SEP_DASH)]
                            if require_dash
                            else []
                        )
                    if state == S.IN_NAME:
                        return [(CourseConstraintsTokenType.DASH, S.IN_NAME)]
                    return []

                if lower_word in {"alebo", "or"}:
                    if state == S.IN_NAME:
                        if doesnt_look_like_conj_in_name(i):
                            return [
                                (CourseConstraintsTokenType.ALEBO, S.AFTER_CONJ),
                                (CourseConstraintsTokenType.NAME, S.IN_NAME),
                            ]
                        return []
                    if state == S.AFTER_RPAR:
                        if doesnt_look_like_conj_in_name(i):
                            return [(CourseConstraintsTokenType.ALEBO, S.AFTER_CONJ)]
                        return []
                    return []

                if lower_word in {"a", "and"}:
                    if state == S.IN_NAME:
                        if doesnt_look_like_conj_in_name(i):
                            return [
                                (CourseConstraintsTokenType.A, S.AFTER_CONJ),
                                (CourseConstraintsTokenType.NAME, S.IN_NAME),
                            ]
                        return [(CourseConstraintsTokenType.NAME, S.IN_NAME)]
                    if state == S.AFTER_RPAR:
                        if doesnt_look_like_conj_in_name(i):
                            return [(CourseConstraintsTokenType.A, S.AFTER_CONJ)]
                        return []
                    return []

                if state in (S.BEGIN, S.AFTER_LPAR, S.AFTER_CONJ):
                    return [(CourseConstraintsTokenType.CODE, S.AFTER_CODE)]

                if state == S.AFTER_CODE:
                    if require_dash:
                        return []
                    return [(CourseConstraintsTokenType.NAME, S.IN_NAME)]

                if state in (S.AFTER_SEP_DASH, S.IN_NAME):
                    return [(CourseConstraintsTokenType.NAME, S.IN_NAME)]

                return []

            def parse(i: int, state: S, balance: int) -> Optional[List[CourseConstraintsTokenType]]:
                """Rekurzia s backtrackingom na skusanie moznosti priradenia na zaklade kandidatov z `cand()`"""
                key = (i, state, balance)
                if key in memo:
                    return memo[key]

                if i >= len(splitted):
                    if balance != 0:
                        memo[key] = None
                        return None
                    if state in (S.IN_NAME, S.AFTER_RPAR):
                        memo[key] = [CourseConstraintsTokenType.END]
                        return memo[key]
                    memo[key] = None
                    return None

                for token_type, next_state in cand(i, state):
                    next_balance = balance
                    if token_type == CourseConstraintsTokenType.LPAR:
                        next_balance += 1
                    elif token_type == CourseConstraintsTokenType.RPAR:
                        next_balance -= 1
                    if next_balance < 0:
                        continue

                    tail = parse(i + 1, next_state, next_balance)
                    if tail is not None:
                        memo[key] = [token_type] + tail
                        return memo[key]

                memo[key] = None
                return None

            return parse(idx, S.BEGIN, 0)

        result = try_parse(require_dash=True)
        if result is not None:
            return tokens + result

        result = try_parse(require_dash=False)
        if result is not None:
            return tokens + result

        raise ValueError(
            "Nie je možné rozdeliť výraz na tokeny: neplatný výraz, nespárované zátvorky "
            "alebo zmiešané formáty s pomlčkou a bez pomlčky."
        )

    def tokenize(self, string: str) -> Tuple[List[str], List[CourseConstraintsTokenType]]:
        """
        Metóda rozdelí reťazec ohraničení na objekty a skúsi priradiť každému objektu to, akú
        rolu hrá v reťazci ohraničenia, konkrétne priradí token typu `CourseConstraintsTokenType`.
        """
        string = re.sub(r"\(\d+\)", "", string)  # zbavit sa cisel v zatvorkach
        string = re.sub(r"([()])", r" \1 ", string)  # vlozit medzery okolo zatvoriek
        string = re.sub(r"\s+", " ", string).strip()  # zbavit sa nasobnych medzier

        if not string:
            return [], [
                CourseConstraintsTokenType.BEGIN,
                CourseConstraintsTokenType.END,
            ]

        splitted: List[str] = string.split()
        tokens: List[CourseConstraintsTokenType] = [CourseConstraintsTokenType.BEGIN]
        tokens = self.assign_tokens(splitted, tokens, 0)
        return splitted, tokens

    def clear_course_constraints(
        self,
    ) -> Tuple[
        List[Tuple[str, CourseConstraintsTokenType]],
        List[Tuple[str, CourseConstraintsTokenType]],
    ]:
        """
        Pomocou tokenizacie vyberie z retazcov prerekvizit a antirekvizit len kody premetov,
        spojky medzi predmetami a zatvorky. Vrati vycistene prerekvizity a antirekvizity ako
        dvojice kod-token.
        """
        splitted_prereq, tokens_prereq = self.tokenize(self.prerequisites)
        splitted_antireq, tokens_antireq = self.tokenize(self.antirequisites)

        tokens_prereq = tokens_prereq[1:-1]
        tokens_antireq = tokens_antireq[1:-1]

        allowed_token_types = {
            CourseConstraintsTokenType.CODE,
            CourseConstraintsTokenType.LPAR,
            CourseConstraintsTokenType.RPAR,
            CourseConstraintsTokenType.A,
            CourseConstraintsTokenType.ALEBO,
        }

        prereq = [
            (symbol, token_type)
            for symbol, token_type in zip(splitted_prereq, tokens_prereq)
            if token_type in allowed_token_types
        ]
        antireq = [
            (symbol, token_type)
            for symbol, token_type in zip(splitted_antireq, tokens_antireq)
            if token_type in allowed_token_types
        ]
        return prereq, antireq

    def _build_prerequisite_cnf(
        self, prereq_tokens: List[Tuple[str, CourseConstraintsTokenType]]
    ) -> CNF:
        return CourseConstraintsCNFBuilder(prereq_tokens).to_cnf()

    @staticmethod
    def _tokens_to_antirequisites(
        tokens: List[Tuple[str, CourseConstraintsTokenType]],
    ) -> Set[str]:
        invalid_token_types = {
            CourseConstraintsTokenType.LPAR,
            CourseConstraintsTokenType.RPAR,
            CourseConstraintsTokenType.ALEBO,
        }
        if any(token_type in invalid_token_types for _, token_type in tokens):
            raise ValueError(
                "Vylučujúce predmety musia byť konjunkciou kódov predmetov bez zátvoriek a bez OR/alebo."
            )

        antirequisites: Set[str] = set()
        for symbol, token_type in tokens:
            if token_type == CourseConstraintsTokenType.CODE:
                antirequisites.add(symbol)
        return antirequisites

    def get_prerequisites(self) -> CNF:
        return [set(clause) for clause in self._prerequisite_cnf]

    def get_antirequisites(self) -> Set[str]:
        return set(self._antirequisites)
