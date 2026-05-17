from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Dict, Optional
from course_constraints import CourseConstraints


class SemesterType(IntEnum):
    Z = 0  # zimny semester
    L = 1  # letny semester


class GradeType(Enum):
    A = 1
    B = 2
    C = 3
    D = 4
    E = 5
    FX = 6


@dataclass(eq=False)
class Course:
    """
    Obsahuje informaciu o predmete: kod a nazov, pocet kreditov, v akom rocniku a semestri
    je dostupny a student je k nemu pripraveny, prerekvizity, vyluculuje predmety a
    rozdelenie znamok.
    """

    code: str
    name: Optional[str] = None
    credits: Optional[int] = None
    year: Optional[int] = None
    semester: Optional[SemesterType] = None
    course_constraints: Optional[CourseConstraints] = None
    grades: Optional[Dict[GradeType, float]] = None
    has_grade_distribution: bool = True

    def set_name(self, name: str) -> bool:
        if name is None or len(name.strip()) == 0:
            return False
        self.name = name.strip()
        return True

    def set_credits(self, credits: int) -> bool:
        if credits is None or credits < 0:
            return False
        self.credits = credits
        return True

    def set_year(self, year: int) -> bool:
        if year is None or year < 1:
            return False
        self.year = year
        return True

    def set_semester(self, semester: str) -> bool:
        if semester is None or len(semester.strip()) != 1:
            return False
        semester = semester.upper()
        match semester:
            case "Z":
                self.semester = SemesterType.Z
            case "L":
                self.semester = SemesterType.L
            case _:
                return False
        return True

    def set_course_constraints(self, prerequisites: str, antirequisites: str) -> bool:
        try:
            self.course_constraints = CourseConstraints(prerequisites, antirequisites)
            return True
        except ValueError as e:
            raise ValueError(f"{self.code}: {e}") from e

    def set_grades(self, grades: Dict[str, float], eps: float = 0.1):
        # nech grades budu pisane velkymi pismenami
        normalized_grades = {grade.upper(): percentage for grade, percentage in grades.items()}

        total = sum(normalized_grades.values())
        if (
            set(normalized_grades.keys()) != {"A", "B", "C", "D", "E", "FX"}
            or abs(total - 100.0) >= eps
            or total <= 0.0
        ):
            return False

        # preskalujeme percenta, aby sa skladali do 1
        scale = 1.0 / total

        converted = {}
        for grade, percentage in normalized_grades.items():
            match grade:
                case "A":
                    converted[GradeType.A] = percentage * scale
                case "B":
                    converted[GradeType.B] = percentage * scale
                case "C":
                    converted[GradeType.C] = percentage * scale
                case "D":
                    converted[GradeType.D] = percentage * scale
                case "E":
                    converted[GradeType.E] = percentage * scale
                case "FX":
                    converted[GradeType.FX] = percentage * scale

        self.grades = converted
        return True

    def __str__(self) -> str:
        return self.code

    def __repr__(self) -> str:
        return f"Course(code={self.code!r})"

    def get_probability(self) -> float:
        if self.grades:
            return 1.0 - self.grades[GradeType.FX]
        return None

    def get_average_grade(self) -> float:
        if self.grades:
            average_grade = (
                1.0 * self.grades[GradeType.A]
                + 1.5 * self.grades[GradeType.B]
                + 2.0 * self.grades[GradeType.C]
                + 2.5 * self.grades[GradeType.D]
                + 3.0 * self.grades[GradeType.E]
                + 4.0 * self.grades[GradeType.FX]
            )
            return average_grade
        return None
