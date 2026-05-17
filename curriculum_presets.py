from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

from curriculum import Curriculum, RequiredOptionalBlock
from infolist import InfolistParser


@dataclass(frozen=True)
class RequiredOptionalBlockPreset:
    name: str
    folder: str
    min_credits: int


@dataclass(frozen=True)
class CurriculumPreset:
    """Dataclass, validuje a uchovava informacie o stiahnutom studijnom plane na zaklade 
    yaml manifesta"""
    id: str
    name: str
    directory: str
    path: Path
    study_program_code: Optional[str]
    required_folder: Optional[str]
    required_optional_blocks: list[RequiredOptionalBlockPreset]
    optional_folder: Optional[str]
    state_exam_folder: Optional[str]

    @classmethod
    def from_manifest(cls, manifest_path: Path) -> CurriculumPreset:
        data = cls._load_manifest(manifest_path)
        preset_dir = manifest_path.parent

        preset_id = cls._required_string(data, "id", manifest_path)
        name = cls._required_string(data, "name", manifest_path)
        study_program_code = cls._optional_string(data, "study_program_code", manifest_path)
        required_folder = cls._optional_string(data, "required_folder", manifest_path)
        optional_folder = cls._optional_string(data, "optional_folder", manifest_path)
        state_exam_folder = cls._optional_string(data, "state_exam_folder", manifest_path)

        required_optional_blocks = cls._parse_required_optional_blocks(data, manifest_path)

        preset = cls(
            id=preset_id,
            name=name,
            directory=preset_dir.name,
            path=preset_dir,
            study_program_code=study_program_code,
            required_folder=required_folder,
            required_optional_blocks=required_optional_blocks,
            optional_folder=optional_folder,
            state_exam_folder=state_exam_folder,
        )
        preset.validate()
        return preset

    def validate(self) -> None:
        folders = []
        if self.required_folder is not None:
            folders.append(("required_folder", self.required_folder, True))
        if self.optional_folder is not None:
            folders.append(("optional_folder", self.optional_folder, False))
        if self.state_exam_folder is not None:
            folders.append(("state_exam_folder", self.state_exam_folder, False))
        for index, block in enumerate(self.required_optional_blocks):
            folders.append(
                (
                    f"required_optional_blocks[{index}].folder",
                    block.folder,
                    block.min_credits > 0,
                )
            )

        for field_name, folder_name, require_html in folders:
            folder_path = self.path / folder_name
            if not folder_path.is_dir():
                raise ValueError(
                    f"{self.path / 'manifest.yml'}: {field_name} odkazuje na neexistujúci priečinok '{folder_name}'."
                )
            if require_html and not list(folder_path.glob("*.html")):
                raise ValueError(
                    f"{self.path / 'manifest.yml'}: priečinok '{folder_name}' v poli {field_name} neobsahuje žiadne HTML súbory."
                )

    def to_option(self) -> dict[str, str]:
        return {
            "id": self.id,
            "name": self.name,
            "directory": self.directory,
        }

    @staticmethod
    def _load_manifest(manifest_path: Path) -> dict[str, Any]:
        with manifest_path.open(encoding="utf-8") as file:
            data = yaml.safe_load(file)
        if not isinstance(data, dict):
            raise ValueError(f"{manifest_path}: manifest musí byť mapovanie.")
        return data

    @staticmethod
    def _required_string(data: dict[str, Any], key: str, manifest_path: Path) -> str:
        value = CurriculumPreset._optional_string(data, key, manifest_path)
        if value is None:
            raise ValueError(f"{manifest_path}: chýba povinné pole '{key}'.")
        return value

    @staticmethod
    def _optional_string(data: dict[str, Any], key: str, manifest_path: Path) -> Optional[str]:
        value = data.get(key)
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(f"{manifest_path}: pole '{key}' musí byť reťazec.")
        value = value.strip()
        return value or None

    @staticmethod
    def _parse_required_optional_blocks(
        data: dict[str, Any],
        manifest_path: Path,
    ) -> list[RequiredOptionalBlockPreset]:
        raw_blocks = data.get("required_optional_blocks", [])
        if raw_blocks is None:
            raw_blocks = []
        if not isinstance(raw_blocks, list):
            raise ValueError(f"{manifest_path}: pole 'required_optional_blocks' musí byť zoznam.")

        blocks: list[RequiredOptionalBlockPreset] = []
        for index, raw_block in enumerate(raw_blocks):
            if not isinstance(raw_block, dict):
                raise ValueError(
                    f"{manifest_path}: required_optional_blocks[{index}] musí byť dict."
                )

            name = CurriculumPreset._required_string(raw_block, "name", manifest_path)
            folder = CurriculumPreset._required_string(raw_block, "folder", manifest_path)
            raw_min_credits = raw_block.get("min_credits")
            if raw_min_credits is None:
                raise ValueError(
                    f"{manifest_path}: required_optional_blocks[{index}] nemá pole 'min_credits'."
                )
            try:
                min_credits = int(raw_min_credits)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"{manifest_path}: required_optional_blocks[{index}].min_credits musí byť celé číslo."
                ) from exc
            if min_credits < 0:
                raise ValueError(
                    f"{manifest_path}: required_optional_blocks[{index}].min_credits musí byť nezáporné."
                )

            blocks.append(
                RequiredOptionalBlockPreset(name=name, folder=folder, min_credits=min_credits)
            )

        return blocks


class CurriculumPresetRepository:
    """Zahrna pracu zo stiahnutymi studijnymi planmi; konkretne robi z nich analog
    repozitara a vie vyrobit z objektov repozitara objekt studijneho planu `Curriculum`"""
    def __init__(self, curricula_dir: Path, parser: Optional[InfolistParser] = None) -> None:
        self.curricula_dir = curricula_dir
        self.parser = parser or InfolistParser()

    def discover(self) -> list[CurriculumPreset]:
        presets = [
            CurriculumPreset.from_manifest(path)
            for path in sorted(self.curricula_dir.glob("*/manifest.yml"))
        ]
        self._validate_unique_ids(presets)
        return sorted(presets, key=lambda preset: preset.name.casefold())

    def discover_options(self) -> list[dict[str, str]]:
        return [preset.to_option() for preset in self.discover()]

    def get(self, preset_id: str) -> CurriculumPreset:
        preset_id = (preset_id or "").strip()
        if not preset_id:
            raise ValueError("Vyberte existujúci študijný plán.")

        for preset in self.discover():
            if preset.id == preset_id:
                return preset
        raise ValueError(f"Neznámy prednastavený študijný plán: {preset_id}")

    def build_curriculum(self, preset_id: str) -> Curriculum:
        preset = self.get(preset_id)
        curriculum = Curriculum(preset.name)

        if preset.required_folder:
            for path in self._iter_html_files(preset.path / preset.required_folder):
                curriculum.add_required_course(
                    self.parser.parse(str(path), preset.study_program_code)
                )

        for block_preset in preset.required_optional_blocks:
            block = RequiredOptionalBlock(
                name=block_preset.name, min_credits=block_preset.min_credits
            )
            for path in self._iter_html_files(preset.path / block_preset.folder):
                course = self.parser.parse(str(path), preset.study_program_code)
                if not curriculum.find_course(course.code):
                    block.add_course(course)
            curriculum.add_required_optional_block(block)

        if preset.optional_folder:
            for path in self._iter_html_files(preset.path / preset.optional_folder):
                curriculum.add_optional_course(
                    self.parser.parse(str(path), preset.study_program_code)
                )

        if preset.state_exam_folder:
            for path in self._iter_html_files(preset.path / preset.state_exam_folder):
                curriculum.add_state_exam_course(
                    self.parser.parse(str(path), preset.study_program_code)
                )

        return curriculum

    def _validate_unique_ids(self, presets: list[CurriculumPreset]) -> None:
        seen: dict[str, str] = {}
        for preset in presets:
            if preset.id in seen:
                raise ValueError(
                    f"Duplicitné id prednastaveného študijného plánu '{preset.id}' v {seen[preset.id]} a {preset.path}."
                )
            seen[preset.id] = str(preset.path)

    def _iter_html_files(self, folder: Path) -> list[Path]:
        if not folder.is_dir():
            raise ValueError(f"Priečinok študijného plánu neexistuje: {folder}")
        return sorted(folder.glob("*.html"))
