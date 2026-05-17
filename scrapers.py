from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse
from urllib.request import urlopen

from bs4 import BeautifulSoup

INFOLIST_INDEX_URL = "https://sluzby.fmph.uniba.sk/infolist/current/sk/"
CURRICULA_DIR = Path(__file__).resolve().parent / "curricula"
CURRICULUM_RE = re.compile(r"^sp_(?:[A-Za-z]{3}(?:-k)?)\.html$")
CURRICULUM_BLOCK_RE = re.compile(r"^([0-9A-Za-z]+(?:-[0-9A-Za-z]+)*):")
COURSE_INFOLIST_RE = re.compile(r"^[0-9]-[A-Za-z]{3}-[0-9A-Za-z]+(?:_[0-9]{2})?\.html$")


@dataclass(frozen=True)
class CurriculumPage:
    """Dataclass, uchovava stiahnute `CurriculumScraper` studijne plany"""
    filename: str
    url: str

    @property
    def folder_name(self) -> str:
        return Path(self.filename).stem.removeprefix("sp_")


@dataclass(frozen=True)
class CurriculumBlock:
    """Dataclass, uchovava info o blokoch studijnych planov"""
    code: str
    title: str
    infolist_filenames: list[str]


class CurriculumScraper:
    """Stahuje studijne plany z webovej stranky `INFOLIST_INDEX_URL` podla `CURRICULUM_RE` do
    vlastneho podpriecinku v priecinku `CURRICULA_DIR`"""
    def __init__(
        self,
        index_url: str = INFOLIST_INDEX_URL,
        output_dir: Path = CURRICULA_DIR,
        curriculum_pattern: re.Pattern[str] = CURRICULUM_RE,
    ) -> None:
        self.index_url = index_url
        self.output_dir = output_dir
        self.curriculum_pattern = curriculum_pattern

    def find_curriculum_pages(self) -> list[CurriculumPage]:
        html = self.fetch_bytes(self.index_url)
        soup = BeautifulSoup(html, "html.parser")

        pages_by_filename: dict[str, CurriculumPage] = {}
        for href in self._iter_local_hrefs(soup):
            filename = Path(urlparse(href).path).name
            if not self.curriculum_pattern.fullmatch(filename):
                continue
            pages_by_filename[filename] = CurriculumPage(
                filename=filename,
                url=urljoin(self.index_url, filename),
            )

        return [pages_by_filename[filename] for filename in sorted(pages_by_filename)]

    def download_curriculum_pages(self) -> list[Path]:
        self.output_dir.mkdir(parents=True, exist_ok=True)

        downloaded_paths: list[Path] = []
        for page in self.find_curriculum_pages():
            curriculum_dir = self.output_dir / page.folder_name
            curriculum_dir.mkdir(parents=True, exist_ok=True)

            output_path = curriculum_dir / page.filename
            output_path.write_bytes(self.fetch_bytes(page.url))
            downloaded_paths.append(output_path)

        return downloaded_paths

    def fetch_bytes(self, url: str) -> bytes:
        with urlopen(url) as response:
            return response.read()

    def _iter_local_hrefs(self, soup: BeautifulSoup) -> Iterable[str]:
        for link in soup.find_all("a", href=True):
            href = link["href"].strip()
            if href and not urlparse(href).scheme:
                yield href


class CurriculumBuilder:
    """Pomocou `bs4` stahuje infolisty zo studijnych planov vytvorenych `CurriculumScraper`"""
    def __init__(
        self,
        curricula_dir: Path = CURRICULA_DIR,
        infolist_base_url: str = INFOLIST_INDEX_URL,
        block_pattern: re.Pattern[str] = CURRICULUM_BLOCK_RE,
        course_infolist_pattern: re.Pattern[str] = COURSE_INFOLIST_RE,
    ) -> None:
        self.curricula_dir = curricula_dir
        self.infolist_base_url = infolist_base_url
        self.block_pattern = block_pattern
        self.course_infolist_pattern = course_infolist_pattern

    def find_curriculum_files(self) -> list[Path]:
        return sorted(self.curricula_dir.glob("*/sp_*.html"))

    def extract_blocks(self, curriculum_file: Path) -> list[CurriculumBlock]:
        soup = BeautifulSoup(curriculum_file.read_bytes(), "html.parser")

        blocks: list[CurriculumBlock] = []
        current_code: str | None = None
        current_title = ""
        current_infolists: list[str] = []
        current_seen: set[str] = set()

        def flush_current_block() -> None:
            if current_code is not None:
                blocks.append(
                    CurriculumBlock(
                        code=current_code,
                        title=current_title,
                        infolist_filenames=list(current_infolists),
                    )
                )

        for row in soup.find_all("tr"):
            header = row.find("th")
            if header is not None:
                flush_current_block()
                current_code, current_title = self._parse_block_header(
                    header.get_text(" ", strip=True)
                )
                current_infolists = []
                current_seen = set()
                continue

            if current_code is None:
                continue

            for filename in self._iter_course_infolist_filenames(row):
                if filename in current_seen:
                    continue
                current_infolists.append(filename)
                current_seen.add(filename)

        flush_current_block()
        return blocks

    def build_curriculum(self, curriculum_file: Path) -> list[Path]:
        downloaded_paths: list[Path] = []
        curriculum_dir = curriculum_file.parent

        for block in self.extract_blocks(curriculum_file):
            block_dir = curriculum_dir / block.code
            block_dir.mkdir(parents=True, exist_ok=True)

            for filename in block.infolist_filenames:
                output_path = block_dir / filename
                output_path.write_bytes(self._fetch_infolist(filename))
                downloaded_paths.append(output_path)

        return downloaded_paths

    def build_all_curricula(self) -> list[Path]:
        downloaded_paths: list[Path] = []
        for curriculum_file in self.find_curriculum_files():
            downloaded_paths.extend(self.build_curriculum(curriculum_file))
        return downloaded_paths

    def _parse_block_header(self, header_text: str) -> tuple[str, str]:
        match = self.block_pattern.match(header_text)
        if match is None:
            raise ValueError(f"Cannot parse curriculum block header: {header_text}")
        return match.group(1), header_text

    def _iter_course_infolist_filenames(self, row) -> Iterable[str]:
        for link in row.find_all("a", href=True):
            filename = Path(urlparse(link["href"]).path).name
            if self.course_infolist_pattern.fullmatch(filename):
                yield filename

    def _fetch_infolist(self, filename: str) -> bytes:
        with urlopen(urljoin(self.infolist_base_url, filename)) as response:
            return response.read()


if __name__ == "__main__":
    scraper = CurriculumScraper()
    curriculum_paths = scraper.download_curriculum_pages()
    print(f"Je stiahnute {len(curriculum_paths)} web-stranok planov.")

    builder = CurriculumBuilder()
    infolist_paths = builder.build_all_curricula()
    print(f"Je stiahnute {len(infolist_paths)} web-stranok infolistov.")
