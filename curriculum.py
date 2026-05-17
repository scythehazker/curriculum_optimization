from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from course import Course


@dataclass
class RequiredOptionalBlock:
    name: str = ""
    min_credits: int = 0
    courses: list[Course] = field(default_factory=list)

    def add_course(self, course: Course) -> None:
        if all(existing.code != course.code for existing in self.courses):
            self.courses.append(course)

    def remove_course(self, course_code: str) -> None:
        self.courses = [course for course in self.courses if course.code != course_code]

    def get_course_codes(self) -> list[str]:
        return [course.code for course in self.courses]


@dataclass
class Curriculum:
    """
    Dataclass, ktory reprezentuje studijny plan. Obsahuje meno studijneho
    programu, povinne predmety, bloky povinne volitelnych predmetov,
    vyberove predmety a predmety statnych skusok.
    """

    name: str
    required_courses: list[Course] = field(default_factory=list)
    required_optional_blocks: list[RequiredOptionalBlock] = field(default_factory=list)
    optional_courses: list[Course] = field(default_factory=list)
    state_exam_courses: list[Course] = field(default_factory=list)

    def add_required_course(self, course: Course) -> None:
        if not self._contains_course(course.code):
            self.required_courses.append(course)

    def add_required_optional_block(self, block: RequiredOptionalBlock) -> None:
        self.required_optional_blocks.append(block)

    def add_optional_course(self, course: Course) -> None:
        if not self._contains_course(course.code):
            self.optional_courses.append(course)

    def add_state_exam_course(self, course: Course) -> None:
        if not self._contains_course(course.code):
            self.state_exam_courses.append(course)

    def get_all_courses(self) -> list[Course]:
        courses = list(self.required_courses)
        for block in self.required_optional_blocks:
            for course in block.courses:
                if all(existing.code != course.code for existing in courses):
                    courses.append(course)
        for course in self.optional_courses:
            if all(existing.code != course.code for existing in courses):
                courses.append(course)
        return courses

    def get_state_exam_credits(self) -> int:
        return sum(course.credits or 0 for course in self.state_exam_courses)

    def find_course(self, course_code: str) -> Optional[Course]:
        for course in self.get_all_courses() + self.state_exam_courses:
            if course.code == course_code:
                return course
        return None

    def get_required_optional_min_credits(self) -> list[int]:
        return [block.min_credits for block in self.required_optional_blocks]

    def get_required_optional_course_codes(self) -> list[list[str]]:
        return [block.get_course_codes() for block in self.required_optional_blocks]

    def is_required_course(self, course_code: str) -> bool:
        return any(course.code == course_code for course in self.required_courses)

    def get_required_optional_block_indices(self, course_code: str) -> list[int]:
        indices = []
        for block_index, block in enumerate(self.required_optional_blocks):
            if any(course.code == course_code for course in block.courses):
                indices.append(block_index)
        return indices

    def is_optional_course(self, course_code: str) -> bool:
        return any(course.code == course_code for course in self.optional_courses)

    def is_state_exam_course(self, course_code: str) -> bool:
        return any(course.code == course_code for course in self.state_exam_courses)

    def get_required_indicator(self, ordered_courses: Optional[list[Course]] = None) -> list[int]:
        courses = ordered_courses if ordered_courses is not None else self.get_all_courses()
        return [1 if self.is_required_course(course.code) else 0 for course in courses]

    def get_required_optional_block_indicators(
        self,
        ordered_courses: Optional[list[Course]] = None,
    ) -> list[list[int]]:
        courses = ordered_courses if ordered_courses is not None else self.get_all_courses()
        indicators: list[list[int]] = []
        for block_index, _ in enumerate(self.required_optional_blocks):
            indicator = []
            for course in courses:
                indicator.append(
                    1 if block_index in self.get_required_optional_block_indices(course.code) else 0
                )
            indicators.append(indicator)
        return indicators

    def _contains_course(self, course_code: str) -> bool:
        return self.find_course(course_code) is not None
