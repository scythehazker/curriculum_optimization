from __future__ import annotations
import json
from dataclasses import dataclass, field
import numpy as np

INF = np.inf


@dataclass
class Constraints:
    length_of_study: int = 0
    m_A: int = 0
    m_B: list[int] = field(default_factory=list)
    m_V: float = 0.0
    m_S: float = 4.0
    m_PC: int = INF
    m_PR: int = INF
    m_PS: int = INF
    m_KC: int = INF
    m_KR: int = INF
    m_KS: int = INF
    cumulative_sums: list[tuple[int, int, int]] = field(default_factory=list)
    individual_sums1: list[tuple[int, int]] = field(default_factory=list)
    individual_sums2: list[tuple[int, int, int]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> Constraints:
        raw_m_b = data.get("m_B", [])
        if isinstance(raw_m_b, (int, float)):
            m_b = [int(raw_m_b)]
        else:
            m_b = [int(x) for x in raw_m_b]

        return cls(
            length_of_study=int(data.get("length_of_study", 0)),
            m_A=int(data.get("m_A", 0)),
            m_B=m_b,
            m_V=float(data.get("m_V", 0.0)),
            m_S=float(data.get("m_S", 4.0)),
            m_PC=int(data.get("m_PC", INF)),
            m_PR=int(data.get("m_PR", INF)),
            m_PS=int(data.get("m_PS", INF)),
            m_KC=int(data.get("m_KC", INF)),
            m_KR=int(data.get("m_KR", INF)),
            m_KS=int(data.get("m_KS", INF)),
            cumulative_sums=[tuple(x) for x in data.get("cumulative_sums", [])],
            individual_sums1=[tuple(x) for x in data.get("individual_sums1", [])],
            individual_sums2=[tuple(x) for x in data.get("individual_sums2", [])],
        )

    @classmethod
    def from_json(cls, raw: str) -> Constraints:
        return cls.from_dict(json.loads(raw))
