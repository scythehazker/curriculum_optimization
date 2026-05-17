from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Optional
import math

from flask import Flask, render_template, request

from constraints import Constraints
from curriculum import Curriculum, RequiredOptionalBlock
from curriculum_presets import CurriculumPresetRepository
from infolist import InfolistParser
from course import SemesterType
from solvers import SolverWithoutRetakesProbability, SolverWithoutRetakesWeightedAverage

BASE_DIR = Path(__file__).resolve().parent
CURRICULA_DIR = BASE_DIR / "curricula"
app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))
PRESET_REPOSITORY = CurriculumPresetRepository(CURRICULA_DIR)
MIN_REQUIRED_OPTIONAL_BLOCKS = 1
PROBABILITY_DISPLAY_LOWER_BOUND = 0.0001


def _parse_int(value: str, default: int = 0) -> int:
    value = (value or "").strip()
    return int(value) if value else default


def _parse_float(value: str, default: float = 0.0) -> float:
    value = (value or "").strip()
    return float(value) if value else default


def _parse_tuple_lines(raw: str, expected_length: int) -> list[tuple[int, ...]]:
    rows: list[tuple[int, ...]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != expected_length:
            raise ValueError(
                f"Očakáva sa {expected_length} hodnôt oddelených čiarkou, zadané: {line}"
            )
        rows.append(tuple(int(part) for part in parts))
    return rows


def _parse_uploaded_course(file_storage, parser: InfolistParser, study_program_code: Optional[str]):
    with NamedTemporaryFile("wb", suffix=".html", delete=True) as temp_file:
        temp_file.write(file_storage.read())
        temp_file.flush()
        return parser.parse(temp_file.name, study_program_code)


def _build_curriculum_from_request(form, files) -> Curriculum:
    """Pomocou triedy `InfolistParser` stahuje data o predmetoch z prislusnych infolistov a
    vracia vytvoreny nimi studijny plan ako objekt `Curriculum`"""
    parser = InfolistParser()
    curriculum_name = form.get("curriculum_name", "").strip() or "Nepomenovaný študijný plán"
    study_program_code = form.get("study_program_code", "").strip() or None
    block_count = max(
        MIN_REQUIRED_OPTIONAL_BLOCKS,
        _parse_int(
            form.get("block_count", str(MIN_REQUIRED_OPTIONAL_BLOCKS)),
            MIN_REQUIRED_OPTIONAL_BLOCKS,
        ),
    )

    curriculum = Curriculum(curriculum_name)

    for file_storage in files.getlist("required_courses"):
        if file_storage and file_storage.filename:
            curriculum.add_required_course(
                _parse_uploaded_course(file_storage, parser, study_program_code)
            )

    for block_index in range(block_count):
        min_credits = _parse_int(form.get(f"required_optional_min_credits_{block_index}", "0"), 0)
        block = RequiredOptionalBlock(
            name=form.get(f"required_optional_name_{block_index}", "").strip()
            or f"Blok {block_index + 1}",
            min_credits=min_credits,
        )
        for file_storage in files.getlist(f"required_optional_block_{block_index}"):
            if file_storage and file_storage.filename:
                course = _parse_uploaded_course(file_storage, parser, study_program_code)
                if not curriculum.find_course(course.code):
                    block.add_course(course)
        curriculum.add_required_optional_block(block)

    for file_storage in files.getlist("optional_courses"):
        if file_storage and file_storage.filename:
            curriculum.add_optional_course(
                _parse_uploaded_course(file_storage, parser, study_program_code)
            )

    for file_storage in files.getlist("state_exam_courses"):
        if file_storage and file_storage.filename:
            curriculum.add_state_exam_course(
                _parse_uploaded_course(file_storage, parser, study_program_code)
            )

    return curriculum


def _has_uploaded_infolists(files) -> bool:
    for field_name in files:
        for file_storage in files.getlist(field_name):
            if file_storage and file_storage.filename:
                return True
    return False


def _state_exam_credits_counted(form) -> bool:
    return form.get("state_exam_credits_counted") == "on"


def _build_constraints_from_request(
    form,
    block_count: int,
    required_optional_min_credits: Optional[list[int]] = None,
) -> Constraints:
    m_b = (
        list(required_optional_min_credits)
        if required_optional_min_credits is not None
        else [
            _parse_int(form.get(f"required_optional_min_credits_{block_index}", "0"), 0)
            for block_index in range(block_count)
        ]
    )
    return Constraints(
        length_of_study=_parse_int(form.get("length_of_study", "0"), 0),
        m_A=_parse_int(form.get("m_A", "0"), 0),
        m_B=m_b,
        m_V=_parse_float(form.get("m_V", "0.0"), 0.0),
        m_S=_parse_float(form.get("m_S", "4.0"), 4.0),
        m_PC=_parse_int(form.get("m_PC", "0"), 0),
        m_PR=_parse_int(form.get("m_PR", "0"), 0),
        m_PS=_parse_int(form.get("m_PS", "0"), 0),
        m_KC=_parse_int(form.get("m_KC", "0"), 0),
        m_KR=_parse_int(form.get("m_KR", "0"), 0),
        m_KS=_parse_int(form.get("m_KS", "0"), 0),
        cumulative_sums=_parse_tuple_lines(form.get("cumulative_sums", ""), 3),
        individual_sums1=_parse_tuple_lines(form.get("individual_sums1", ""), 2),
        individual_sums2=_parse_tuple_lines(form.get("individual_sums2", ""), 3),
    )


def _validate_curriculum(
    curriculum: Curriculum, constraints: Constraints, solver_type: str
) -> None:
    if len(curriculum.required_optional_blocks) != len(constraints.m_B):
        raise ValueError("Počet B blokov sa nezhoduje s počtom kreditových obmedzení pre B bloky.")

    _validate_stage_constraints(constraints)

    if not curriculum.get_all_courses():
        raise ValueError(
            "Pred spustením riešenia nahrajte aspoň jeden informačný list predmetu"
            " okrem predmetov štátnej skúšky."
        )

    empty_required_optional_blocks = [
        block.name or f"Blok {index + 1}"
        for index, block in enumerate(curriculum.required_optional_blocks)
        if block.min_credits > 0 and not block.courses
    ]
    if empty_required_optional_blocks:
        raise ValueError(
            "Niektoré povinne voliteľné bloky vyžadujú kredity, ale neobsahujú žiadne nahrané predmety:\n"
            + "\n".join(empty_required_optional_blocks)
        )

    missing_fields: list[str] = []
    missing_grades: list[str] = []
    for course in curriculum.get_all_courses():
        if course.year is None:
            missing_fields.append(f"{course.code}: odporúčaný ročník")
        if course.semester is None:
            missing_fields.append(f"{course.code}: odporúčaný semester")
        if course.credits is None:
            missing_fields.append(f"{course.code}: kredity")
        if course.grades is None and solver_type in {"probability", "weighted_average"}:
            missing_grades.append(course.code)

    if missing_fields:
        raise ValueError("Niektoré spracované predmety sú neúplné:\n" + "\n".join(missing_fields))
    if missing_grades:
        raise ValueError(
            "Niektoré predmety nemajú v informačných listoch rozdelenie známok, "
            "ale zvolený typ riešenia ho potrebuje:\n" + "\n".join(missing_grades)
        )

    missing_state_exam_fields: list[str] = []
    for course in curriculum.state_exam_courses:
        if course.credits is None:
            missing_state_exam_fields.append(f"{course.code}: kredity")

    if missing_state_exam_fields:
        raise ValueError(
            "Niektoré spracované predmety štátnej skúšky sú neúplné:\n"
            + "\n".join(missing_state_exam_fields)
        )


def _build_curriculum_warnings(curriculum: Curriculum) -> list[str]:
    courses_without_grade_distribution = [
        course.code
        for course in curriculum.get_all_courses()
        if not getattr(course, "has_grade_distribution", True)
    ]
    if not courses_without_grade_distribution:
        return []
    return [
        "Niektoré predmety nemajú v informačných listoch rozdelenie známok. "
        "Pre tieto predmety sa automaticky nastaví 0 % pravdepodobnosť absolvovania: "
        + ", ".join(courses_without_grade_distribution)
    ]


def _validate_stage_constraints(constraints: Constraints) -> None:
    errors: list[str] = []

    def validate_year(field_name: str, row_index: int, year: int) -> None:
        if year < 1 or year > constraints.length_of_study:
            errors.append(
                f"{field_name}, riadok {row_index}: rok musí byť medzi 1 a "
                f"{constraints.length_of_study}, zadané {year}."
            )

    def validate_semester(field_name: str, row_index: int, semester: int) -> None:
        if semester not in {0, 1}:
            errors.append(
                f"{field_name}, riadok {row_index}: semester musí byť 0 alebo 1, zadané {semester}."
            )

    def validate_credits(field_name: str, row_index: int, credits: int) -> None:
        if credits < 0:
            errors.append(
                f"{field_name}, riadok {row_index}: kredity musia byť nezáporné, zadané {credits}."
            )

    for row_index, (year, semester, credits) in enumerate(constraints.cumulative_sums, start=1):
        validate_year("cumulative_sums", row_index, year)
        validate_semester("cumulative_sums", row_index, semester)
        validate_credits("cumulative_sums", row_index, credits)

    for row_index, (year, credits) in enumerate(constraints.individual_sums1, start=1):
        validate_year("individual_sums1", row_index, year)
        validate_credits("individual_sums1", row_index, credits)

    for row_index, (year, semester, credits) in enumerate(constraints.individual_sums2, start=1):
        validate_year("individual_sums2", row_index, year)
        validate_semester("individual_sums2", row_index, semester)
        validate_credits("individual_sums2", row_index, credits)

    if errors:
        raise ValueError(
            "Neplatné ohraničenia na prechod medzi časťami štúdia:\n" + "\n".join(errors)
        )


def _decode_solution(curriculum: Curriculum, x) -> list[dict[str, object]]:
    if x is None:
        return []

    courses = curriculum.get_all_courses()
    n = len(courses)
    solution_rows: list[dict[str, object]] = []
    for index, value in enumerate(x):
        if value < 0.5:
            continue
        course_index = index % n
        semester_index = index // n
        year = semester_index // 2 + 1
        semester = SemesterType.Z if semester_index % 2 == 0 else SemesterType.L
        course = courses[course_index]
        solution_rows.append(
            {
                "code": course.code,
                "name": course.name,
                "role": _describe_course_role(curriculum, course.code),
                "credits": course.credits,
                "year": year,
                "semester": semester.name,
                "probability": course.get_probability(),
                "average_grade": course.get_average_grade(),
                "is_state_exam": False,
            }
        )
    solution_rows.extend(_build_state_exam_rows(curriculum))
    return solution_rows


def _build_state_exam_rows(curriculum: Curriculum) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for course in curriculum.state_exam_courses:
        rows.append(
            {
                "code": course.code,
                "name": course.name,
                "role": _describe_course_role(curriculum, course.code),
                "credits": course.credits,
                "year": "Koniec štúdia",
                "semester": "Koniec štúdia",
                "probability": "Pravdepodobnosť sa nezapočítava",
                "average_grade": "Vážený priemer sa nezapočítava",
                "is_state_exam": True,
            }
        )
    return rows


def _build_solution_message(x, solution_rows: list[dict[str, object]]) -> str:
    if x is None:
        return "Solver nenašiel prípustné riešenie pre aktuálne vstupy."
    selected_course_count = sum(1 for row in solution_rows if not row["is_state_exam"])
    if selected_course_count == 0:
        return "Solver skončil, ale zvolené obmedzenia povoľujú prázdny výber predmetov."
    return f"Solver našiel riešenie s počtom vybratých predmetov: {selected_course_count}."


def _build_solution_summary(curriculum: Curriculum, x) -> Optional[dict[str, object]]:
    if x is None:
        return None

    courses = curriculum.get_all_courses()
    n = len(courses)
    selected_courses = []
    for index, value in enumerate(x):
        if value < 0.5:
            continue
        course_index = index % n
        selected_courses.append(courses[course_index])

    if not selected_courses:
        return {
            "selected_course_count": 0,
            "total_credits": 0,
            "state_exam_credits": curriculum.get_state_exam_credits(),
            "total_credits_with_state_exams": curriculum.get_state_exam_credits(),
            "log_probability": "žiadne predmety",
            "probability": "žiadne predmety",
            "weighted_average": "žiadne predmety",
        }

    probabilities = [course.get_probability() for course in selected_courses]
    average_grades = [course.get_average_grade() for course in selected_courses]
    credits = [course.credits for course in selected_courses]

    log_probability = sum(math.log(max(probability, 1e-12)) for probability in probabilities)
    total_credits = sum(credits)
    weighted_average = None
    if total_credits > 0:
        weighted_average = (
            sum(grade * credit for grade, credit in zip(average_grades, credits)) / total_credits
        )

    return {
        "selected_course_count": len(selected_courses),
        "total_credits": total_credits,
        "state_exam_credits": curriculum.get_state_exam_credits(),
        "total_credits_with_state_exams": total_credits + curriculum.get_state_exam_credits(),
        "log_probability": log_probability,
        "probability": _format_probability(math.exp(log_probability)),
        "weighted_average": weighted_average,
    }


def _format_probability(value: float) -> str:
    if 0 < value < PROBABILITY_DISPLAY_LOWER_BOUND:
        return f"< {PROBABILITY_DISPLAY_LOWER_BOUND:g}"
    return f"{value:.4f}"


def _describe_course_role(curriculum: Curriculum, course_code: str) -> str:
    parts: list[str] = []
    if curriculum.is_required_course(course_code):
        parts.append("A")
    block_indices = curriculum.get_required_optional_block_indices(course_code)
    if block_indices:
        block_names = [
            curriculum.required_optional_blocks[index].name or f"Blok {index + 1}"
            for index in block_indices
        ]
        parts.append("B: " + ", ".join(block_names))
    if curriculum.is_optional_course(course_code):
        parts.append("C")
    if curriculum.is_state_exam_course(course_code):
        parts.append("Predmety štátnej skúšky")
    return "; ".join(parts) if parts else "Nepriradené"


@app.route("/", methods=["GET", "POST"])
def index():
    """Hlavna Flask-metoda, ktora sa vola pri obnoveni stranky. Koordinuje vytvaranie objektov a
    vracia na frontend najdene vysledky, prip. chyby a upozornenia"""
    error = None
    result_message = None
    warnings: list[str] = []
    solution_summary = None
    solution_rows: list[dict[str, object]] = []
    curriculum = None
    curriculum_presets = PRESET_REPOSITORY.discover_options()
    selected_source = request.values.get(
        "curriculum_source", "preset" if curriculum_presets else "upload"
    )
    if selected_source not in {"preset", "upload"}:
        selected_source = "preset" if curriculum_presets else "upload"

    block_count = _parse_int(
        request.values.get("block_count", str(MIN_REQUIRED_OPTIONAL_BLOCKS)),
        MIN_REQUIRED_OPTIONAL_BLOCKS,
    )
    if block_count < MIN_REQUIRED_OPTIONAL_BLOCKS:
        block_count = MIN_REQUIRED_OPTIONAL_BLOCKS

    if request.method == "POST" and request.form.get("action") == "solve":
        try:
            if selected_source == "preset":
                if _has_uploaded_infolists(request.files):
                    raise ValueError(
                        "Vyberte buď existujúci študijný plán, alebo nahrané informačné listy, nie oboje."
                    )
                curriculum = PRESET_REPOSITORY.build_curriculum(request.form.get("preset_id", ""))
                constraints = _build_constraints_from_request(
                    request.form,
                    len(curriculum.required_optional_blocks),
                    curriculum.get_required_optional_min_credits(),
                )
            else:
                curriculum = _build_curriculum_from_request(request.form, request.files)
                constraints = _build_constraints_from_request(request.form, block_count)
            warnings = _build_curriculum_warnings(curriculum)
            state_exam_credits_counted = _state_exam_credits_counted(request.form)
            if state_exam_credits_counted:
                constraints.m_A = max(0, constraints.m_A - curriculum.get_state_exam_credits())

            solver_type = request.form.get("solver_type", "probability")
            _validate_curriculum(curriculum, constraints, solver_type)
            if solver_type == "weighted_average":
                solver = SolverWithoutRetakesWeightedAverage(curriculum, constraints)
            else:
                solver = SolverWithoutRetakesProbability(curriculum, constraints)

            x = solver.solve()
            solution_rows = _decode_solution(curriculum, x)
            result_message = _build_solution_message(x, solution_rows)
            solution_summary = _build_solution_summary(curriculum, x)
        except Exception as exc:
            error = str(exc)

    return render_template(
        "index.html",
        block_count=block_count,
        error=error,
        warnings=warnings,
        result_message=result_message,
        solution_summary=solution_summary,
        solution_rows=solution_rows,
        curriculum=curriculum,
        curriculum_presets=curriculum_presets,
        selected_source=selected_source,
        state_exam_credits_counted=_state_exam_credits_counted(request.form),
        form_data=request.form,
    )


if __name__ == "__main__":
    app.run(debug=False)
