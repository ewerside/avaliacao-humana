"""Resultados: junta respostas e campos ocultos, calcula concordância e grava CSV, JSON e um resumo em Markdown.

A configuração da análise vem do próprio teste (campo `analise` do molde, guardado oculto no banco):
  "analise": {
    "ia": {"campo": "veredito", "nome": "juiz X", "mapa": {"mesmo": "sim", "diferente": "nao", "incerto": "nao_sei"},
           "positivo_ia": "mesmo", "positivo_pessoa": "sim"},
    "estrato": {"campo": "veredito", "populacao": {"mesmo": 283, "incerto": 180, "diferente": 297}},
    "gabarito": "campo_do_oculto_com_a_resposta_certa"
  }
Nada aqui usa nome de pessoa: o export do banco só traz o código do avaliador.
"""
import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from .metricas import alfa_krippendorff, kappa_cohen, kappas_pareados, wilson


def _fmt_p(t):
    p, lo, hi = t
    if p is None:
        return "sem dados"
    return f"{100 * p:.0f}% (IC 95% {100 * lo:.0f} a {100 * hi:.0f}%)"


def _valor(r):
    """Resposta canônica de uma linha: escolha, ou a nota como texto."""
    if r.get("escolha") is not None:
        return r["escolha"]
    if r.get("nota") is not None:
        return str(r["nota"])
    return None


def tabela(exp):
    """Linhas de resposta com tipo, papel e campos ocultos do item."""
    itens = {(i["versao"], i["chave"]): i for i in exp["itens"]}
    linhas = []
    for r in exp["respostas"]:
        it = itens[(r["versao"], r["item"])]
        op_oculto = None
        for o in it.get("opcoes") or []:
            if o["chave"] == r.get("escolha"):
                op_oculto = o.get("oculto")
        linhas.append({**r, "tipo": it["tipo"], "papel": it["papel"], "resposta_controle": it.get("resposta_controle"),
                       "oculto": it.get("oculto") or {}, "escolha_oculto": op_oculto, "valor": _valor(r)})
    return linhas


def calcular(exp):
    linhas = tabela(exp)
    versoes = {v["versao"]: v for v in exp["versoes"]}
    analise = (versoes[max(versoes)]["analise"] if versoes else {}) or {}
    out = {"teste": exp["teste"], "exportado_em": exp.get("exportado_em"), "versoes": sorted(versoes),
           "analise": analise, "avaliadores": {}, "ia": None, "entre_pessoas": None, "gabarito": None}

    por_sessao = defaultdict(list)
    for l in linhas:
        por_sessao[(l["avaliador"], l["sessao"])].append(l)
    total_por_sessao = {(s["avaliador"], s["sessao"]): s for s in exp["sessoes"]}

    # ---- por avaliador: progresso, tempo, controles, repetições
    for (av, ses), ls in sorted(por_sessao.items()):
        s = total_por_sessao.get((av, ses), {})
        ctl = [l for l in ls if l["papel"] == "controle" and not l["rep"]]
        ctl_ok = sum(1 for l in ctl if l["valor"] == l["resposta_controle"])
        primeira = {l["item"]: l for l in ls if not l["rep"]}
        reps = [(primeira[l["item"]], l) for l in ls if l["rep"] and l["item"] in primeira]
        rep_ok = sum(1 for a, b in reps if a["valor"] == b["valor"])
        ms = [l["ms"] for l in ls if l.get("ms")]
        out["avaliadores"][f"{av}/{ses}"] = {
            "avaliador": av, "sessao": ses, "versao": ls[0]["versao"], "respondidas": len(ls), "total": s.get("total"),
            "terminada": bool(s.get("terminada_em")),
            "tempo_mediano_s": round(statistics.median(ms) / 1000, 1) if ms else None,
            "tempo_total_min": round(sum(ms) / 60000, 1) if ms else None,
            "controles": {"acertos": ctl_ok, "n": len(ctl), "erros": [{"item": l["item"], "resposta": l["valor"],
                                                                        "esperado": l["resposta_controle"]} for l in ctl if l["valor"] != l["resposta_controle"]]},
            "repeticoes": {"iguais": rep_ok, "n": len(reps), "diferentes": [{"item": a["item"], "primeira": a["valor"], "repeticao": b["valor"]}
                                                                           for a, b in reps if a["valor"] != b["valor"]]},
            "alteracoes": sum(l.get("alteracoes") or 0 for l in ls),
            "distribuicao": dict(Counter(l["valor"] for l in ls if l["papel"] == "normal" and not l["rep"])),
        }

    normais = [l for l in linhas if l["papel"] == "normal" and not l["rep"]]

    # ---- IA contra pessoa
    cfg = analise.get("ia")
    if cfg and cfg.get("campo"):
        campo, mapa = cfg["campo"], cfg.get("mapa") or {}
        pos_ia, pos_p = cfg.get("positivo_ia"), cfg.get("positivo_pessoa")
        est = analise.get("estrato") or {}
        campo_est = est.get("campo") or campo
        comp = [l for l in normais if l["oculto"].get(campo) is not None and l["valor"] is not None]
        ia_raw = [l["oculto"][campo] for l in comp]
        ia = [mapa.get(x, x) for x in ia_raw]
        pe = [l["valor"] for l in comp]
        k = sum(1 for a, b in zip(ia, pe) if a == b)
        res = {"nome": cfg.get("nome"), "n": len(comp), "concordancia": wilson(k, len(comp)), "acertos": k,
               "kappa": kappa_cohen(ia, pe),
               "matriz": [{"ia": a, "pessoa": b, "n": n} for (a, b), n in sorted(Counter(zip(ia_raw, pe)).items())]}
        # por estrato e ponderada pela população
        estratos = defaultdict(lambda: [0, 0])
        for l, a, b in zip(comp, ia, pe):
            e = l["oculto"].get(campo_est)
            estratos[e][1] += 1
            estratos[e][0] += a == b
        res["por_estrato"] = {str(e): {"acertos": v[0], "n": v[1], "concordancia": wilson(v[0], v[1])} for e, v in sorted(estratos.items(), key=lambda x: str(x[0]))}
        pop = est.get("populacao")
        if pop:
            tot = sum(pop[e] for e in pop if estratos.get(e, [0, 0])[1] > 0)
            if tot:
                res["concordancia_ponderada"] = sum(pop[e] / tot * estratos[e][0] / estratos[e][1] for e in pop if estratos.get(e, [0, 0])[1] > 0)
                res["estratos_sem_amostra"] = [e for e in pop if estratos.get(e, [0, 0])[1] == 0]
        # precisão no positivo e versão binária
        if pos_ia and pos_p:
            pos = [b for a, b in zip(ia_raw, pe) if a == pos_ia]
            decididos = [b for b in pos if b != "nao_sei"]
            res["precisao_positivo"] = {
                "ia_positivo": pos_ia, "pessoa_positivo": pos_p, "n": len(pos),
                "contando_nao_sei_como_nao": wilson(sum(1 for b in pos if b == pos_p), len(pos)),
                "so_decididos": wilson(sum(1 for b in decididos if b == pos_p), len(decididos)),
                "nao_sei": sum(1 for b in pos if b == "nao_sei"),
            }
            bi_ia = [a == pos_ia for a in ia_raw]
            bi_pe = [b == pos_p for b in pe]
            kb = sum(1 for a, b in zip(bi_ia, bi_pe) if a == b)
            res["binaria"] = {"descricao": f"IA diz '{pos_ia}' contra pessoa diz '{pos_p}'", "concordancia": wilson(kb, len(comp)),
                              "kappa": kappa_cohen(bi_ia, bi_pe)}
            # pessoa: o que disse quando a IA não disse positivo
            nao_pos = [b for a, b in zip(ia_raw, pe) if a != pos_ia]
            res["pessoa_positivo_quando_ia_nao"] = wilson(sum(1 for b in nao_pos if b == pos_p), len(nao_pos))
        out["ia"] = res

    # ---- entre pessoas
    por_av = defaultdict(dict)
    for l in normais:
        por_av[l["avaliador"]][(l["versao"], l["item"])] = l["valor"]
    if len(por_av) >= 2:
        unidades = sorted({u for d in por_av.values() for u in d})
        dados = [[por_av[a].get(u) for a in sorted(por_av)] for u in unidades]
        tipos = {l["tipo"] for l in normais}
        ep = {"avaliadores": sorted(por_av), "pares": kappas_pareados(por_av), "alfa_nominal": alfa_krippendorff(dados, "nominal")}
        if tipos == {"nota"}:
            num = [[int(v) if v not in (None, "nao_sei") else None for v in u] for u in dados]
            ep["alfa_ordinal"] = alfa_krippendorff(num, "ordinal")
            ep["alfa_intervalar"] = alfa_krippendorff(num, "intervalar")
        out["entre_pessoas"] = ep

    # ---- gabarito
    g = analise.get("gabarito")
    if g:
        com = [l for l in normais if l["oculto"].get(g) is not None]
        por = defaultdict(lambda: [0, 0])
        for l in com:
            por[l["avaliador"]][1] += 1
            por[l["avaliador"]][0] += str(l["valor"]) == str(l["oculto"][g])
        out["gabarito"] = {a: {"acertos": v[0], "n": v[1], "acerto": wilson(v[0], v[1])} for a, v in por.items()}
    return out, linhas


def gravar(exp, pasta):
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    met, linhas = calcular(exp)
    (pasta / "export.json").write_text(json.dumps(exp, ensure_ascii=False, indent=1), encoding="utf-8")
    (pasta / "metricas.json").write_text(json.dumps(met, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    chaves_ocultas = sorted({k for l in linhas for k in l["oculto"]})
    with open(pasta / "respostas.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        cab = ["avaliador", "sessao", "versao", "pos", "item", "tipo", "papel", "rep", "valor", "escolha", "nota",
               "resposta_controle", "ms", "alteracoes", "comentario", "respondido_em", "escolha_oculto"] + [f"oculto.{k}" for k in chaves_ocultas]
        w.writerow(cab)
        for l in linhas:
            oc = [l["oculto"].get(k) for k in chaves_ocultas]
            oc = [json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for v in oc]
            w.writerow([l["avaliador"], l["sessao"], l["versao"], l["pos"], l["item"], l["tipo"], l["papel"], l["rep"], l["valor"],
                        l.get("escolha"), l.get("nota"), l.get("resposta_controle"), l.get("ms"), l.get("alteracoes"),
                        l.get("comentario"), l.get("respondido_em"),
                        json.dumps(l["escolha_oculto"], ensure_ascii=False) if l["escolha_oculto"] else None] + oc)
    (pasta / "resultado.md").write_text(resumo(met), encoding="utf-8")
    return met


def resumo(m):
    L = [f"# Resultado: {m['teste']}", "", f"Exportado em {m.get('exportado_em')}; versões {m['versoes']}.", ""]
    L.append("## Avaliadores")
    for k, a in m["avaliadores"].items():
        c, r = a["controles"], a["repeticoes"]
        L.append(f"- {a['avaliador']} (sessão {a['sessao']}, v{a['versao']}): {a['respondidas']} de {a['total']} respondidas; "
                 f"tempo mediano {a['tempo_mediano_s']} s por tela, total {a['tempo_total_min']} min; "
                 f"controles {c['acertos']} de {c['n']}; repetições iguais {r['iguais']} de {r['n']}; alterações {a['alteracoes']}.")
        for e in c["erros"]:
            L.append(f"  - controle {e['item']}: respondeu {e['resposta']}, esperado {e['esperado']}")
        for d in r["diferentes"]:
            L.append(f"  - repetição {d['item']}: {d['primeira']} e depois {d['repeticao']}")
    ia = m.get("ia")
    if ia:
        L += ["", f"## IA contra pessoa ({ia.get('nome') or 'IA'})", "",
              f"- Concordância simples (com o mapa da análise): {_fmt_p(ia['concordancia'])}, n = {ia['n']}.",
              f"- Kappa de Cohen: {ia['kappa']:.2f}." if ia["kappa"] is not None else "- Kappa: sem dados."]
        if "concordancia_ponderada" in ia:
            L.append(f"- Concordância ponderada pela população dos estratos: {100 * ia['concordancia_ponderada']:.0f}%"
                     + (f" (estratos sem amostra: {ia['estratos_sem_amostra']})" if ia.get("estratos_sem_amostra") else "") + ".")
        for e, v in ia.get("por_estrato", {}).items():
            L.append(f"  - estrato {e}: {v['acertos']} de {v['n']}, {_fmt_p(v['concordancia'])}")
        pp = ia.get("precisao_positivo")
        if pp:
            L += [f"- Precisão da IA quando diz '{pp['ia_positivo']}' (pessoa diz '{pp['pessoa_positivo']}'), n = {pp['n']}:",
                  f"  - contando 'não dá para saber' como não: {_fmt_p(pp['contando_nao_sei_como_nao'])}",
                  f"  - só os casos em que a pessoa decidiu: {_fmt_p(pp['so_decididos'])} ({pp['nao_sei']} 'não dá para saber')"]
            b = ia["binaria"]
            L.append(f"- Binária ({b['descricao']}): {_fmt_p(b['concordancia'])}, kappa {b['kappa']:.2f}." if b["kappa"] is not None else "")
            L.append(f"- Pessoa disse '{pp['pessoa_positivo']}' quando a IA não disse '{pp['ia_positivo']}': {_fmt_p(ia['pessoa_positivo_quando_ia_nao'])}.")
        L += ["", "Matriz (IA × pessoa):", "", "| IA | pessoa | n |", "|---|---|---|"]
        L += [f"| {c['ia']} | {c['pessoa']} | {c['n']} |" for c in ia["matriz"]]
    ep = m.get("entre_pessoas")
    if ep:
        L += ["", "## Entre pessoas", "", f"- Alfa de Krippendorff (nominal): {ep['alfa_nominal']:.2f}"]
        for k in ("alfa_ordinal", "alfa_intervalar"):
            if ep.get(k) is not None:
                L.append(f"- {k.replace('_', ' ')}: {ep[k]:.2f}")
        for p in ep["pares"]:
            L.append(f"- {p['a']} × {p['b']}: concordância {100 * p['concordancia']:.0f}%, kappa {p['kappa']:.2f}, n = {p['n']}"
                     if p["n"] else f"- {p['a']} × {p['b']}: sem itens em comum")
    if m.get("gabarito"):
        L += ["", "## Contra o gabarito"]
        L += [f"- {a}: {v['acertos']} de {v['n']}, {_fmt_p(v['acerto'])}" for a, v in m["gabarito"].items()]
    return "\n".join(x for x in L if x is not None) + "\n"
