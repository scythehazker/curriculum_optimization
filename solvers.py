from __future__ import annotations
from dataclasses import dataclass
from typing import List, Tuple
import numpy as np
from course import *
from scipy.optimize import Bounds, LinearConstraint, milp
from constraints import *
from curriculum import Curriculum


class Solver:
    """Bazova trieda-solver, ktora implementuje konstruktor a spolocnu metodu `solve()` pre vsetky solvre"""
    def __init__(self, curriculum: Curriculum, constraints: Constraints) -> None:
        self.curriculum = curriculum
        self.courses = curriculum.get_all_courses()
        self.constraints = constraints

    def solve(self):
        pass


class SolverWithoutRetakes(Solver):
    """Trieda-solver, ktora implementuje vytvaranie ohraniceni pre optimalizaciu bez
    opakovania neuspesnych predmetov"""
    _MIN_PROBABILITY = 1e-12

    @dataclass
    class PreprocessedConstraints:
        R: int
        n: int
        log_p: np.ndarray
        q: np.ndarray
        a: np.ndarray
        B: list[np.ndarray]
        c: np.ndarray
        C: np.ndarray
        K: np.ndarray
        m_K: np.ndarray
        Z_1: np.ndarray
        m_Z1: np.ndarray
        Z_2: np.ndarray
        m_Z2: np.ndarray
        U: np.ndarray
        N: np.ndarray
        V: np.ndarray
        z: np.ndarray
        s: np.ndarray
        P: np.ndarray
        S: np.ndarray

    @staticmethod
    def _rows_to_matrix(rows: list, width: int, dtype=int) -> np.ndarray:
        if not rows:
            return np.zeros((0, width), dtype=dtype)
        return np.array(rows, dtype=dtype)

    def _restructure_course_constraints(
        self,
    ) -> List[Tuple[bool, List[set[int]], set[int]]]:
        available_courses = {
            course.code: course_index for course_index, course in enumerate(self.courses)
        }
        new_course_constraints: List[Tuple[bool, List[set[int]], set[int]]] = []

        for course in self.courses:
            prerequisites = course.course_constraints.get_prerequisites()
            antirequisites = course.course_constraints.get_antirequisites()

            new_prerequisites = []
            is_in_J = True
            for alternative_group in prerequisites:
                new_alternative_group = set()

                for prerequisite in alternative_group:
                    if prerequisite in available_courses.keys():
                        new_alternative_group.add(available_courses[prerequisite])

                if not new_alternative_group:
                    is_in_J = False
                    break
                new_prerequisites.append(new_alternative_group)

            if not is_in_J:
                new_course_constraints.append((False, [], set()))
                continue

            new_antirequisites = set()
            for antirequisite in antirequisites:
                if antirequisite in available_courses.keys():
                    new_antirequisites.add(available_courses[antirequisite])

            new_course_constraints.append((True, new_prerequisites, new_antirequisites))

        return new_course_constraints

    def preprocess_constraints(self) -> PreprocessedConstraints:
        R = self.constraints.length_of_study
        n = len(self.courses)
        total_variables = 2 * R * n

        p = [course.get_probability() for course in self.courses]  # premenne p
        p = np.array(p * (2 * R), dtype=float)  # vektor p
        safe_p = np.clip(p, self._MIN_PROBABILITY, 1.0)
        log_p = np.log(safe_p)  # vektor log p

        q = [0] * total_variables
        for course_index, course in enumerate(self.courses):
            recommended_semester = 2 * (course.year - 1) + course.semester
            while (n * recommended_semester) + course_index < len(q):
                q[(n * recommended_semester) + course_index] = 1
                recommended_semester += 2
        q = np.array(q)  # vektor q

        a = np.array(self.curriculum.get_required_indicator(self.courses))  # premenne a

        B: list[np.ndarray] = []
        for block_indicator in self.curriculum.get_required_optional_block_indicators(self.courses):
            beta_g = [0] * (2 * R * n)
            for course_index, belongs_to_block in enumerate(block_indicator):
                if belongs_to_block:
                    for semester in range(0, 2 * R):
                        beta_g[(semester * n) + course_index] = 1
            beta_g = np.array(beta_g)
            B.append(np.diag(beta_g))
        B = np.array(B)  # matica B

        c = [0] * total_variables
        for course_index, course in enumerate(self.courses):
            for semester in range(0, 2 * R):
                c[(semester * n) + course_index] = course.credits
        c = np.array(c)  # vektor c
        C = np.diag(c)  # matica C

        K = []
        m_K = []
        for r_i, s_i, m_K_i in self.constraints.cumulative_sums:
            k_i_left = [1] * (n * (2 * (r_i - 1) + s_i + 1))
            k_i_right = [0] * (total_variables - len(k_i_left))
            k_i = k_i_left + k_i_right
            K.append(k_i)
            m_K.append(m_K_i)
        K = self._rows_to_matrix(K, total_variables, dtype=int)  # matica K
        m_K = np.array(m_K)  # vektor m_K

        Z_1 = []
        m_Z1 = []
        for r_i, m_Z1_i in self.constraints.individual_sums1:
            z_1_i = np.zeros(total_variables, dtype=int)
            z_1_i[2 * n * (r_i - 1) : 2 * n * r_i] = 1
            Z_1.append(z_1_i)
            m_Z1.append(m_Z1_i)
        Z_1 = self._rows_to_matrix(Z_1, total_variables, dtype=int)  # matica Z_1
        m_Z1 = np.array(m_Z1)  # vektor m_Z1

        Z_2 = []
        m_Z2 = []
        for r_i, s_i, m_Z2_i in self.constraints.individual_sums2:
            z_2_i = np.zeros(total_variables, dtype=int)
            z_2_i[n * (2 * (r_i - 1) + s_i) : n * (2 * (r_i - 1) + s_i + 1)] = 1
            Z_2.append(z_2_i)
            m_Z2.append(m_Z2_i)
        Z_2 = self._rows_to_matrix(Z_2, total_variables, dtype=int)  # matica Z_2
        m_Z2 = np.array(m_Z2)  # vektor m_Z2

        restructured_course_constraints = self._restructure_course_constraints()
        U = []
        N = []
        V = []
        for course_index, course_constraints in enumerate(restructured_course_constraints):
            is_in_J, prerequisites, antirequisites = course_constraints
            if is_in_J:
                for alternative_group in prerequisites:
                    for course_semester in range(1, 2 * R):
                        u = [0] * total_variables
                        u[n * course_semester + course_index] = -1
                        for prerequisite_semester in range(0, course_semester):
                            for prerequisite in alternative_group:
                                u[n * prerequisite_semester + prerequisite] = 1
                        U.append(u)
            else:
                nu = [0] * total_variables
                for semester in range(0, 2 * R):
                    nu[n * semester + course_index] = 1
                N.append(nu)
            for antirequisite in antirequisites:
                v = [0] * total_variables
                for semester in range(0, 2 * R):
                    v[n * semester + course_index] = 1
                    v[n * semester + antirequisite] = 1
                V.append(v)
        U = self._rows_to_matrix(U, total_variables, dtype=int)  # matica U
        N = self._rows_to_matrix(N, total_variables, dtype=int)  # matica N
        V = self._rows_to_matrix(V, total_variables, dtype=int)  # matica V

        z = [course.get_average_grade() for course in self.courses]  # premenne z
        z = np.array(z * (2 * R))  # vektor z
        s = z - self.constraints.m_S  # vektor s

        P = []
        for year in range(0, R):
            pho = np.zeros(2 * R * n, dtype=int)
            pho[2 * n * year : 2 * n * (year + 1)] = 1
            P.append(pho)
        P = np.array(P)  # matica P

        S = []
        for semester in range(0, 2 * R):
            sigma = np.zeros(2 * R * n, dtype=int)
            sigma[n * semester : n * (semester + 1)] = 1
            S.append(sigma)
        S = np.array(S)  # matica S

        return self.PreprocessedConstraints(
            R=R,
            n=n,
            log_p=log_p,
            q=q,
            a=a,
            B=B,
            c=c,
            C=C,
            K=K,
            m_K=m_K,
            Z_1=Z_1,
            m_Z1=m_Z1,
            Z_2=Z_2,
            m_Z2=m_Z2,
            U=U,
            N=N,
            V=V,
            z=z,
            s=s,
            P=P,
            S=S,
        )

    def build_problem_matrices(
        self, preprocessed_constraints: PreprocessedConstraints
    ) -> Tuple[np.ndarray, np.ndarray]:
        R = preprocessed_constraints.R
        n = preprocessed_constraints.n
        c = preprocessed_constraints.c.reshape(2 * R * n, 1)
        s = preprocessed_constraints.s.reshape(2 * R * n, 1)

        A_1 = -np.ones((1, 2 * R * n))
        b_1 = np.array([-1])

        A_2 = np.hstack([np.eye(n) for _ in range(2 * R)])
        b_2 = np.ones(n)

        A_3 = np.eye(2 * R * n)
        b_3 = preprocessed_constraints.q

        A_4 = -np.hstack([np.eye(n) for _ in range(2 * R)])
        b_4 = -preprocessed_constraints.a

        A_5 = -c.T
        b_5 = np.array([-self.constraints.m_A])

        if len(preprocessed_constraints.B) > 0:
            A_6 = np.vstack([-c.T @ B_g for B_g in preprocessed_constraints.B])
            b_6 = -np.array(self.constraints.m_B)
        else:
            A_6 = np.zeros((0, 2 * R * n))
            b_6 = np.zeros(0)

        A_7 = -preprocessed_constraints.K @ preprocessed_constraints.C
        b_7 = -preprocessed_constraints.m_K

        A_8 = -preprocessed_constraints.Z_1 @ preprocessed_constraints.C
        b_8 = -preprocessed_constraints.m_Z1

        A_9 = -preprocessed_constraints.Z_2 @ preprocessed_constraints.C
        b_9 = -preprocessed_constraints.m_Z2

        A_10 = -preprocessed_constraints.U
        b_10 = np.zeros(A_10.shape[0])

        A_11 = preprocessed_constraints.N
        b_11 = np.zeros(A_11.shape[0])

        A_12 = preprocessed_constraints.V
        b_12 = np.ones(A_12.shape[0])

        if self.constraints.m_V > 0.0:
            A_13 = -preprocessed_constraints.log_p.reshape(1, 2 * R * n)
            b_13 = np.array([-np.log(self.constraints.m_V)])
        else:
            A_13 = np.zeros((0, 2 * R * n))
            b_13 = np.zeros(0)

        A_14 = s.T @ preprocessed_constraints.C
        b_14 = np.array([0])

        A_15 = np.vstack(
            [
                np.ones((1, 2 * R * n)),
                preprocessed_constraints.P,
                preprocessed_constraints.S,
                np.ones((1, 2 * R * n)) @ preprocessed_constraints.C,
                preprocessed_constraints.P @ preprocessed_constraints.C,
                preprocessed_constraints.S @ preprocessed_constraints.C,
            ]
        )
        b_15 = np.concatenate(
            [
                [self.constraints.m_PC],
                self.constraints.m_PR * np.ones(R),
                self.constraints.m_PS * np.ones(2 * R),
                [self.constraints.m_KC],
                self.constraints.m_KR * np.ones(R),
                self.constraints.m_KS * np.ones(2 * R),
            ]
        )

        A = np.vstack(
            [
                A_1,
                A_2,
                A_3,
                A_4,
                A_5,
                A_6,
                A_7,
                A_8,
                A_9,
                A_10,
                A_11,
                A_12,
                A_13,
                A_14,
                A_15,
            ]
        )
        b = np.concatenate(
            [
                b_1,
                b_2,
                b_3,
                b_4,
                b_5,
                b_6,
                b_7,
                b_8,
                b_9,
                b_10,
                b_11,
                b_12,
                b_13,
                b_14,
                b_15,
            ]
        )

        return A, b


class SolverWithoutRetakesProbability(SolverWithoutRetakes):
    """Trieda-solver, ktora riesi optimalizaciu pravdepodobnosti absolvovania studia"""
    def solve(self) -> np.array:
        preprocessed_constraints = self.preprocess_constraints()
        A, b = self.build_problem_matrices(preprocessed_constraints)
        d = -preprocessed_constraints.log_p

        milp_constraints = LinearConstraint(A=A, lb=-np.inf, ub=b)
        integrality = np.ones(len(d), dtype=int)
        bounds = Bounds(np.zeros(len(d)), np.ones(len(d)))

        solution = milp(
            c=d,
            constraints=milp_constraints,
            integrality=integrality,
            bounds=bounds,
            options={"disp": False},
        )

        if not solution.success or solution.x is None:
            return None
        x = solution.x
        return x


class SolverWithoutRetakesWeightedAverage(SolverWithoutRetakes):
    """Trieda-solver, ktora riesi optimalizaciu vazenemu studijneho priemeru"""
    def solve(self) -> np.array:
        preprocessed_constraints = self.preprocess_constraints()
        A, b = self.build_problem_matrices(preprocessed_constraints)

        if self.constraints.m_A <= 0:
            return None

        variable_count = A.shape[1]
        omega = 1.0 / self.constraints.m_A

        x_start = 0
        y_start = variable_count
        t_index = 2 * variable_count
        total_variables = 2 * variable_count + 1

        objective = np.zeros(total_variables)
        objective[y_start:t_index] = preprocessed_constraints.z * preprocessed_constraints.c

        constraint_matrices = []
        lower_bounds = []
        upper_bounds = []

        # A y <= b t
        transformed_A = np.zeros((A.shape[0], total_variables))
        transformed_A[:, y_start:t_index] = A
        transformed_A[:, t_index] = -b
        constraint_matrices.append(transformed_A)
        lower_bounds.append(np.full(A.shape[0], -np.inf))
        upper_bounds.append(np.zeros(A.shape[0]))

        # c^T y = 1
        normalized_credits = np.zeros((1, total_variables))
        normalized_credits[0, y_start:t_index] = preprocessed_constraints.c
        constraint_matrices.append(normalized_credits)
        lower_bounds.append(np.array([1.0]))
        upper_bounds.append(np.array([1.0]))

        # y <= Omega x
        upper_link = np.zeros((variable_count, total_variables))
        upper_link[:, x_start:y_start] = -omega * np.eye(variable_count)
        upper_link[:, y_start:t_index] = np.eye(variable_count)
        constraint_matrices.append(upper_link)
        lower_bounds.append(np.full(variable_count, -np.inf))
        upper_bounds.append(np.zeros(variable_count))

        # y >= t - Omega(1 - x)
        lower_link = np.zeros((variable_count, total_variables))
        lower_link[:, x_start:y_start] = -omega * np.eye(variable_count)
        lower_link[:, y_start:t_index] = np.eye(variable_count)
        lower_link[:, t_index] = -1.0
        constraint_matrices.append(lower_link)
        lower_bounds.append(np.full(variable_count, -omega))
        upper_bounds.append(np.full(variable_count, np.inf))

        # y <= t
        t_upper_link = np.zeros((variable_count, total_variables))
        t_upper_link[:, y_start:t_index] = np.eye(variable_count)
        t_upper_link[:, t_index] = -1.0
        constraint_matrices.append(t_upper_link)
        lower_bounds.append(np.full(variable_count, -np.inf))
        upper_bounds.append(np.zeros(variable_count))

        milp_constraints = LinearConstraint(
            A=np.vstack(constraint_matrices),
            lb=np.concatenate(lower_bounds),
            ub=np.concatenate(upper_bounds),
        )
        integrality = np.zeros(total_variables, dtype=int)
        integrality[x_start:y_start] = 1
        bounds = Bounds(
            np.concatenate(
                [
                    np.zeros(variable_count),
                    np.zeros(variable_count),
                    np.array([0.0]),
                ]
            ),
            np.concatenate(
                [
                    np.ones(variable_count),
                    omega * np.ones(variable_count),
                    np.array([omega]),
                ]
            ),
        )

        solution = milp(
            c=objective,
            constraints=milp_constraints,
            integrality=integrality,
            bounds=bounds,
            options={"disp": False},
        )

        if not solution.success or solution.x is None:
            return None
        return solution.x[x_start:y_start]

    def _dinkelbach(
        self,
        A: np.ndarray,
        b: np.ndarray,
        z: np.ndarray,
        c: np.ndarray,
        lambda_0: float = 4.0,
        eps: float = 1e-4,
        max_iter=100,
    ) -> np.array:
        n = A.shape[1]
        milp_constraints = LinearConstraint(A=A, lb=-np.inf, ub=b)
        integrality = np.ones(n, dtype=int)
        bounds = Bounds(np.zeros(n), np.ones(n))

        lambda_ = lambda_0
        x = None

        for _ in range(max_iter):
            d = (z - lambda_) * c

            solution = milp(
                c=d,
                constraints=milp_constraints,
                integrality=integrality,
                bounds=bounds,
                options={"disp": False},
            )
            if not solution.success or solution.x is None:
                break
            x = solution.x

            f = (z * c) @ x
            g = c @ x
            if abs(g) < eps:
                break

            target = f - lambda_ * g

            if abs(target) < eps:
                break

            lambda_ = f / g

        return x

    def _solve_dinkelbach(self) -> np.array:
        preprocessed_constraints = self.preprocess_constraints()
        A, b = self.build_problem_matrices(preprocessed_constraints)

        x = self._dinkelbach(A, b, preprocessed_constraints.z, preprocessed_constraints.c)
        return x
