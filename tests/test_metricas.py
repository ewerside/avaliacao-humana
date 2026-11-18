import math

import pytest

from av.metricas import alfa_krippendorff, concordancia, kappa_cohen, wilson

# Exemplo clássico de Krippendorff (2011), "Computing Krippendorff's Alpha-Reliability": 4 avaliadores, 12 unidades.
A = [1, 2, 3, 3, 2, 1, 4, 1, 2, None, None, None]
B = [1, 2, 3, 3, 2, 2, 4, 1, 2, 5, None, 3]
C = [None, 3, 3, 3, 2, 3, 4, 2, 2, 5, 1, None]
D = [1, 2, 3, 3, 2, 4, 4, 1, 2, 5, 1, None]
UNIDADES = [list(t) for t in zip(A, B, C, D)]


def test_alfa_nominal_exemplo_classico():
    assert alfa_krippendorff(UNIDADES, "nominal") == pytest.approx(0.743, abs=1e-3)


def test_alfa_intervalar_exemplo_classico():
    assert alfa_krippendorff(UNIDADES, "intervalar") == pytest.approx(0.849, abs=1e-3)


def test_alfa_ordinal_exemplo_classico():
    assert alfa_krippendorff(UNIDADES, "ordinal") == pytest.approx(0.815, abs=1e-3)


def test_alfa_confere_com_pacote_krippendorff():
    kr = pytest.importorskip("krippendorff")
    import numpy as np
    m = np.array([[math.nan if v is None else v for v in linha] for linha in (A, B, C, D)], dtype=float)
    for nosso, deles in (("nominal", "nominal"), ("ordinal", "ordinal"), ("intervalar", "interval")):
        assert alfa_krippendorff(UNIDADES, nosso) == pytest.approx(kr.alpha(reliability_data=m, level_of_measurement=deles), abs=1e-9)


def test_alfa_categorias_texto():
    u = [["sim", "sim"], ["nao", "nao"], ["sim", "nao"], ["nao_sei", "nao_sei"]]
    assert -1 <= alfa_krippendorff(u, "nominal") <= 1


def test_kappa_exemplo_conhecido():
    # 50 itens: 20 sim/sim, 5 sim/nao, 10 nao/sim, 15 nao/nao -> po=0,7; pe=0,5; kappa=0,4
    a = ["s"] * 25 + ["n"] * 25
    b = ["s"] * 20 + ["n"] * 5 + ["s"] * 10 + ["n"] * 15
    assert kappa_cohen(a, b) == pytest.approx(0.4)
    assert concordancia(a, b) == (35, 50)


def test_kappa_ignora_ausentes_e_perfeito():
    assert kappa_cohen(["a", "b", None], ["a", "b", "a"]) == 1.0


def test_wilson():
    p, lo, hi = wilson(9, 10)
    assert p == 0.9 and lo == pytest.approx(0.596, abs=1e-3) and hi == pytest.approx(0.982, abs=1e-3)
    assert wilson(0, 0) == (None, None, None)
