"""Métricas de concordância. Sem dependências além da biblioteca padrão."""
import math
from collections import Counter, defaultdict
from itertools import combinations


def wilson(k, n, z=1.96):
    """Intervalo de Wilson para a proporção k/n (95% por padrão). Devolve (p, baixo, alto)."""
    if n == 0:
        return (None, None, None)
    p = k / n
    den = 1 + z * z / n
    centro = (p + z * z / (2 * n)) / den
    meia = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (p, max(0.0, centro - meia), min(1.0, centro + meia))


def concordancia(a, b):
    """Concordância simples entre duas listas pareadas (ignora pares com None). Devolve (k, n)."""
    pares = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    return sum(1 for x, y in pares if x == y), len(pares)


def kappa_cohen(a, b):
    """Kappa de Cohen (nominal) entre dois avaliadores; ignora pares com None."""
    pares = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    n = len(pares)
    if n == 0:
        return None
    po = sum(1 for x, y in pares if x == y) / n
    ca, cb = Counter(x for x, _ in pares), Counter(y for _, y in pares)
    pe = sum(ca[c] * cb[c] for c in set(ca) | set(cb)) / (n * n)
    if pe == 1:
        return 1.0 if po == 1 else 0.0
    return (po - pe) / (1 - pe)


def matriz_confusao(a, b):
    """Contagens (a, b) para pares sem None."""
    return Counter((x, y) for x, y in zip(a, b) if x is not None and y is not None)


def alfa_krippendorff(dados, nivel="nominal", ordem=None):
    """Alfa de Krippendorff.

    dados: lista de unidades; cada unidade é a lista dos valores dados pelos avaliadores (None = ausente).
    nivel: 'nominal', 'ordinal' ou 'intervalar'. Para ordinal, `ordem` dá a sequência dos valores (padrão: sorted).
    """
    unidades = [[v for v in u if v is not None] for u in dados]
    unidades = [u for u in unidades if len(u) >= 2]
    if not unidades:
        return None
    valores = sorted({v for u in unidades for v in u}, key=lambda x: (ordem.index(x) if ordem else x))
    if len(valores) == 1:
        return 1.0
    # matriz de coincidências
    o = defaultdict(float)
    for u in unidades:
        m = len(u)
        c = Counter(u)
        for x in c:
            for y in c:
                o[(x, y)] += c[x] * (c[y] - (1 if x == y else 0)) / (m - 1)
    n_c = {v: sum(o[(v, w)] for w in valores) for v in valores}
    n = sum(n_c.values())

    def delta2(x, y):
        if x == y:
            return 0.0
        if nivel == "nominal":
            return 1.0
        if nivel == "intervalar":
            return float(x - y) ** 2
        if nivel == "ordinal":
            ix, iy = sorted((valores.index(x), valores.index(y)))
            s = sum(n_c[valores[g]] for g in range(ix, iy + 1)) - (n_c[valores[ix]] + n_c[valores[iy]]) / 2
            return s * s
        raise ValueError(nivel)

    do = sum(o[(x, y)] * delta2(x, y) for x in valores for y in valores) / n
    de = sum(n_c[x] * n_c[y] * delta2(x, y) for x in valores for y in valores) / (n * (n - 1))
    if de == 0:
        return 1.0
    return 1 - do / de


def kappas_pareados(por_avaliador):
    """por_avaliador: {avaliador: {unidade: valor}}. Kappa e concordância para cada par de avaliadores."""
    out = []
    for a, b in combinations(sorted(por_avaliador), 2):
        us = sorted(set(por_avaliador[a]) & set(por_avaliador[b]))
        va = [por_avaliador[a][u] for u in us]
        vb = [por_avaliador[b][u] for u in us]
        k, n = concordancia(va, vb)
        out.append({"a": a, "b": b, "n": n, "concordancia": k / n if n else None, "kappa": kappa_cohen(va, vb)})
    return out
