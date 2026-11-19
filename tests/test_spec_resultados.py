import copy
import json
from pathlib import Path

from av import resultados, spec

RAIZ = Path(__file__).resolve().parent.parent


def molde():
    return spec.carregar(RAIZ / "moldes" / "exemplo-tipos.json")


def test_molde_de_exemplo_valido():
    erros, _ = spec.validar(molde())
    assert erros == []


def test_erros_comuns():
    s = molde()
    s["itens"][0]["paineis"].pop()                      # par com 1 painel
    s["itens"][1]["id"] = s["itens"][2]["id"]           # id repetido
    s["itens"][3]["controle"] = "talvez"                # controle impossível
    s["itens"][4]["opcoes"].append({"id": "x", "texto": "t"})  # ab com 3 opções
    erros, _ = spec.validar(s)
    texto = " | ".join(erros)
    for trecho in ("exatamente 2 painéis", "id repetido", "controle 'talvez'", "exatamente 2 opções"):
        assert trecho in texto


def _categorias_como_escolha():
    ops = [{"id": "mesmo", "texto": "Mesmo modelo"}, {"id": "parecido", "texto": "Parecido"}, {"id": "outro", "texto": "Outro"}]
    return {"teste": "categorias-teste", "titulo": "t", "introducao": ["a", "b"], "tipo": "escolha",
            "exemplo": {"paineis": [{"texto": "p"}, {"texto": "a"}], "resposta": "parecido"},
            "itens": [{"id": f"I{n}", "paineis": [{"texto": "p"}, {"texto": "a"}], "opcoes": copy.deepcopy(ops)} for n in range(3)]}


def test_categorias_fixas_nao_vao_como_escolha():
    erros, _ = spec.validar(_categorias_como_escolha())
    texto = " | ".join(erros)
    assert "respostas fixas" in texto              # opções iguais em todos os itens
    assert "exemplo: resposta 'parecido'" in texto  # exemplo sem a resposta na tela


def test_categorias_fixas_como_botoes_do_par():
    s = _categorias_como_escolha()
    s["tipo"] = "par"
    s["botoes"] = [{"valor": "mesmo", "rotulo": "Mesmo modelo"}, {"valor": "parecido", "rotulo": "Parecido"},
                   {"valor": "outro", "rotulo": "Outro produto"}, {"valor": "nao_sei", "rotulo": "Não sei"}]
    for it in s["itens"]:
        it.pop("opcoes")
    erros, _ = spec.validar(s)
    assert erros == []
    s["botoes"].append({"valor": "mesmo", "rotulo": "de novo"})
    assert any("valores repetidos" in e for e in spec.validar(s)[0])


def test_resolver_nao_vaza_oculto_no_publico():
    s = molde()
    ids = {id(m): f"00000000-0000-0000-0000-{n:012d}" for n, m in enumerate(spec.midias(s))}
    p = spec.resolver(s, ids)
    for it in p["itens"]:
        pub = json.dumps(it["publico"]) + json.dumps([o["publico"] for o in it.get("opcoes", [])])
        assert "veredito" not in pub and "origem" not in pub and "gabarito" not in pub
    assert p["itens"][3]["papel"] == "controle" and p["itens"][3]["resposta_controle"] == "sim"


def _export_falso():
    itens = [
        {"versao": 1, "chave": "P1", "tipo": "par", "papel": "normal", "resposta_controle": None, "repetir": True, "oculto": {"v": "mesmo"}},
        {"versao": 1, "chave": "P2", "tipo": "par", "papel": "normal", "resposta_controle": None, "repetir": False, "oculto": {"v": "diferente"}},
        {"versao": 1, "chave": "P3", "tipo": "par", "papel": "normal", "resposta_controle": None, "repetir": False, "oculto": {"v": "mesmo"}},
        {"versao": 1, "chave": "C1", "tipo": "par", "papel": "controle", "resposta_controle": "sim", "repetir": False, "oculto": {}},
    ]
    def r(av, pos, item, esc, rep=False):
        return {"avaliador": av, "sessao": av[-4:], "versao": 1, "pos": pos, "item": item, "rep": rep, "escolha": esc, "nota": None, "ms": 2000}
    resp = [r("av-aaaa", 1, "P1", "sim"), r("av-aaaa", 2, "P2", "nao"), r("av-aaaa", 3, "P3", "nao_sei"), r("av-aaaa", 4, "C1", "sim"),
            r("av-aaaa", 5, "P1", "nao", True),
            r("av-bbbb", 1, "P1", "sim"), r("av-bbbb", 2, "P2", "nao"), r("av-bbbb", 3, "P3", "sim"), r("av-bbbb", 4, "C1", "nao")]
    ses = [{"sessao": a[-4:], "avaliador": a, "versao": 1, "total": 5, "terminada_em": "x"} for a in ("av-aaaa", "av-bbbb")]
    analise = {"ia": {"campo": "v", "mapa": {"mesmo": "sim", "diferente": "nao", "incerto": "nao_sei"}, "positivo_ia": "mesmo", "positivo_pessoa": "sim"},
               "estrato": {"campo": "v", "populacao": {"mesmo": 3, "diferente": 1}}}
    return {"teste": "t", "versoes": [{"versao": 1, "analise": analise}], "itens": itens, "sessoes": ses, "respostas": resp}


def test_resultados_contas():
    m, _ = resultados.calcular(_export_falso())
    a, b = m["avaliadores"]["av-aaaa/aaaa"], m["avaliadores"]["av-bbbb/bbbb"]
    assert (a["controles"]["acertos"], a["controles"]["n"]) == (1, 1)
    assert (b["controles"]["acertos"], b["controles"]["n"]) == (0, 1)
    assert (a["repeticoes"]["iguais"], a["repeticoes"]["n"]) == (0, 1)
    ia = m["ia"]
    assert ia["n"] == 6 and ia["acertos"] == 5          # só o nao_sei de A em P3 discorda
    pp = ia["precisao_positivo"]
    assert pp["n"] == 4 and pp["nao_sei"] == 1
    assert pp["contando_nao_sei_como_nao"][0] == 0.75 and pp["so_decididos"][0] == 1.0
    # ponderada: mesmo 3/4 com peso 3/4, diferente 2/2 com peso 1/4
    assert abs(ia["concordancia_ponderada"] - (0.75 * 0.75 + 0.25 * 1.0)) < 1e-9
    assert m["entre_pessoas"]["pares"][0]["n"] == 3


def test_resumo_e_gravacao(tmp_path):
    met = resultados.gravar(_export_falso(), tmp_path)
    assert (tmp_path / "respostas.csv").read_text(encoding="utf-8").count("\n") == 10
    assert "Precisão da IA" in (tmp_path / "resultado.md").read_text(encoding="utf-8")
