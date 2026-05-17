from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlparse
from urllib.request import urlopen
import re

from bs4 import BeautifulSoup, NavigableString, Tag

from course import Course


class InfolistParser:
    """Zahrna pracu po extrahovaniu informacie z informacnych listov"""

    _GRADE_LABELS = ("A", "B", "C", "D", "E", "FX")
    _CODE_LABELS = ("Kód", "Course ID")
    _TITLE_LABELS = ("Názov predmetu", "Course title")
    _CREDITS_LABELS = ("Počet kreditov", "Credits")
    _SEMESTER_LABELS = ("Odporúčaný semester štúdia", "Recommended semester")
    _PREREQUISITE_LABELS = ("Podmieňujúce predmety", "Required prerequisites")
    _CONTENT_PREREQUISITE_LABELS = ("Obsahová prerekvizita", "Content prerequisite")
    _ANTIREQUISITE_LABELS = (
        "Vylučujúce predmety",
        "Excluded courses",
        "Antirequisites",
    )

    def parse(self, source: str, study_program_code: Optional[str] = None) -> Course:
        """Pomocou `bs4` validuje a vytvara predmet ako objekt typu `Course` z HTML infolista"""
        soup = BeautifulSoup(self._load_source(source), "html.parser")

        course_code = self._extract_code(soup)
        course_name = self._extract_name(soup)
        credits = self._extract_credits(soup)

        course = Course(course_code)
        self._require(
            course.set_name(course_name),
            f"Nie je možné nastaviť názov predmetu pre '{course_code}'.",
        )
        self._require(
            course.set_credits(credits),
            f"Nie je možné nastaviť kredity pre '{course_code}'.",
        )

        year, semester = self._extract_recommended_semester(soup, study_program_code)
        if year is not None:
            self._require(
                course.set_year(year),
                f"Nie je možné nastaviť odporúčaný ročník pre '{course_code}'.",
            )
        if semester is not None:
            self._require(
                course.set_semester(semester),
                f"Nie je možné nastaviť odporúčaný semester pre '{course_code}'.",
            )

        prerequisites = self._extract_prerequisites(soup)
        antirequisites = self._extract_antirequisites(soup)
        self._require(
            course.set_course_constraints(prerequisites, antirequisites),
            f"Nie je možné nastaviť obmedzenia predmetu pre '{course_code}'.",
        )

        grades = self._extract_grades(soup)
        if grades is None:
            course.has_grade_distribution = False
            grades = {"A": 0.0, "B": 0.0, "C": 0.0, "D": 0.0, "E": 0.0, "FX": 100.0}
        self._require(
            course.set_grades(grades),
            f"Nie je možné nastaviť rozdelenie známok pre '{course_code}'.",
        )

        return course

    def _load_source(self, source: str) -> str:
        parsed = urlparse(source)
        if parsed.scheme in {"http", "https"}:
            with urlopen(source) as response:
                return response.read().decode("utf-8", errors="ignore")

        return Path(source).read_text(encoding="utf-8", errors="ignore")

    def _extract_code(self, soup: BeautifulSoup) -> str:
        return self._extract_inline_value(soup, self._CODE_LABELS)

    def _extract_name(self, soup: BeautifulSoup) -> str:
        return self._extract_inline_value(soup, self._TITLE_LABELS)

    def _extract_credits(self, soup: BeautifulSoup) -> int:
        credits_text = self._extract_inline_value(soup, self._CREDITS_LABELS)
        match = re.search(r"\d+", credits_text)
        if match is None:
            raise ValueError("Nie je možné získať počet kreditov z informačného listu.")
        return int(match.group(0))

    def _extract_recommended_semester(
        self,
        soup: BeautifulSoup,
        study_program_code: Optional[str],
    ) -> tuple[Optional[int], Optional[str]]:
        block = self._find_section_cell(soup, self._SEMESTER_LABELS)
        if block is None:
            return None, None

        lines = [line.strip() for line in block.stripped_strings]
        lines = [
            line
            for line in lines
            if line
            and self._normalize_label(line) not in self._normalize_labels(self._SEMESTER_LABELS)
        ]

        selected_line = None
        if study_program_code is not None:
            normalized_program_code = study_program_code.strip().casefold()
            exact_prefix = f"{normalized_program_code} "
            for line in lines:
                if line.casefold().startswith(exact_prefix):
                    selected_line = line
                    break

        if selected_line is None and lines:
            fallback_semester = self._extract_fallback_semester(lines)
            if fallback_semester is None:
                return None, None
            return 1, fallback_semester
        if selected_line is None:
            return None, None

        match = re.search(r"(\d+)\s*/\s*([ZL])", selected_line)
        if match is None:
            fallback_semester = self._extract_fallback_semester(lines)
            if fallback_semester is None:
                return None, None
            return 1, fallback_semester
        return int(match.group(1)), match.group(2)

    def _extract_prerequisites(self, soup: BeautifulSoup) -> str:
        block = self._find_section_cell(soup, self._PREREQUISITE_LABELS)
        if block is None:
            return ""
        text = self._extract_constraint_section_text(
            block,
            start_labels=self._PREREQUISITE_LABELS,
            stop_labels=self._CONTENT_PREREQUISITE_LABELS + self._ANTIREQUISITE_LABELS,
        )
        return self._normalize_constraint_expression(text)

    def _extract_antirequisites(self, soup: BeautifulSoup) -> str:
        block = self._find_section_cell(soup, self._ANTIREQUISITE_LABELS)
        if block is None:
            return ""
        text = self._extract_constraint_section_text(
            block,
            start_labels=self._ANTIREQUISITE_LABELS,
            stop_labels=(),
        )
        return self._normalize_constraint_expression(text)

    def _extract_grades(self, soup: BeautifulSoup) -> Optional[Dict[str, float]]:
        text = soup.get_text(" ", strip=True)
        grades: Dict[str, float] = {}
        for label in self._GRADE_LABELS:
            match = re.search(rf"\b{label}:\s*([0-9]+(?:[.,][0-9]+)?)%", text)
            if match is None:
                return None
            grades[label] = float(match.group(1).replace(",", "."))
        return grades

    def _extract_inline_value(self, soup: BeautifulSoup, labels: tuple[str, ...]) -> str:
        strong = self._find_strong(soup, labels)
        if strong is None:
            raise ValueError(f"Nie je možné nájsť pole s označeniami: {labels}")

        parent = strong.parent
        if parent is None:
            raise ValueError(f"Nie je možné získať hodnotu poľa s označeniami: {labels}")

        text = self._clean_text(parent.get_text(" "))
        for label in labels:
            text = re.sub(rf"^{re.escape(label)}\s*:\s*", "", text)
        return text

    def _find_section_cell(self, soup: BeautifulSoup, labels: tuple[str, ...]) -> Optional[Tag]:
        strong = self._find_strong(soup, labels)
        if strong is None:
            return None
        parent = strong.parent
        return parent if isinstance(parent, Tag) else None

    def _find_strong(self, soup: BeautifulSoup, labels: tuple[str, ...]) -> Optional[Tag]:
        normalized_labels = self._normalize_labels(labels)
        for strong in soup.find_all("strong"):
            strong_text = self._normalize_label(strong.get_text(" "))
            if strong_text in normalized_labels:
                return strong
        return None

    def _normalize_constraint_text(self, value: str) -> str:
        if not re.search(r"\s", value) and any(character.isdigit() for character in value):
            return f"{value} {value}"
        return value

    def _normalize_constraint_expression(self, value: str) -> str:
        value = self._clean_text(value)
        value = re.sub(r"\(\s+", "(", value)
        value = re.sub(r"\s+\)", ")", value)
        return value

    def _clean_text(self, value: str) -> str:
        value = value.replace("\xa0", " ")
        value = re.sub(r"\s+", " ", value)
        return value.strip()

    def _normalize_label(self, value: str) -> str:
        return self._clean_text(value).rstrip(":")

    def _normalize_labels(self, values: tuple[str, ...]) -> set[str]:
        return {self._normalize_label(value) for value in values}

    def _require(self, condition: bool, message: str) -> None:
        if not condition:
            raise ValueError(message)

    def _extract_fallback_semester(self, lines: list[str]) -> Optional[str]:
        semesters = []
        for line in lines:
            match = re.search(r"\d+\s*/\s*([ZL])", line)
            if match is not None:
                semesters.append(match.group(1))

        if not semesters:
            return None
        if "Z" in semesters:
            return "Z"
        return "L"

    def _extract_constraint_section_text(
        self,
        block: Tag,
        start_labels: tuple[str, ...],
        stop_labels: tuple[str, ...],
    ) -> str:
        normalized_start_labels = self._normalize_labels(start_labels)
        normalized_stop_labels = self._normalize_labels(stop_labels)

        pieces: list[str] = []
        for child in block.children:
            if isinstance(child, NavigableString):
                pieces.append(str(child))
                continue

            if not isinstance(child, Tag):
                continue

            if child.name == "strong":
                label = self._normalize_label(child.get_text(" "))
                if label in normalized_start_labels:
                    continue
                if label in normalized_stop_labels:
                    break

            if child.name == "p":
                strong = child.find("strong")
                if (
                    strong is not None
                    and self._normalize_label(strong.get_text(" ")) in normalized_stop_labels
                ):
                    break

            pieces.append(self._render_constraint_child(child))

        return "".join(pieces)

    def _render_constraint_child(self, child: Tag) -> str:
        if child.name == "a":
            return self._normalize_constraint_text(self._clean_text(child.get_text(" ")))
        if child.name == "br":
            return " "
        return child.get_text(" ", strip=False)
