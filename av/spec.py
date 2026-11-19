"""Molde (spec) de um teste: leitura, validação e conversão para o formato que o banco recebe.

O molde é um JSON. Campos de topo:
  teste (slug), projeto, titulo, introducao (lista de 2 a 4 frases), tempo_min, tipo (par|ab|escolha|nota),
  pergunta, botoes (só par; padrão Sim/Não/Não dá para saber), rotulos_paineis, exemplo, comentario (bool),
  fim, config {distancia_repeticao}, analise {...}, itens [...]
Qual tipo usar:
  par      dois painéis (imagem e/ou texto) e respostas fixas, em ordem fixa no rodapé. Categorias como
           "mesmo / parecido / outro / não sei" são `botoes` [{valor, rotulo, tecla}] do tipo par, nunca opções de escolha.
  ab       duas saídas para comparar; os lados são sorteados por pessoa.
  escolha  N saídas diferentes por item para escolher a melhor; a ordem é sorteada por pessoa (só faz sentido
           quando as opções são candidatas a comparar, não respostas fixas).
  nota     escala de 1 a 5.
Exemplo: {tipo?, pergunta?, texto?, paineis, opcoes? (só texto), resposta (uma resposta possível), explicacao}.
Endereços http(s) nos textos viram links que abrem em outra aba.
Item:
  id, tipo (opcional, sobrepõe o do topo), pergunta, texto, paineis [{rotulo, texto, midia}],
  opcoes [{id, texto, midia, oculto}] (ab: 2; escolha: 2 ou mais), escala {min, max} (nota),
  oculto {...} (nunca vai para a página), controle (resposta esperada), repetir (bool)
Mídia (onde houver "midia"): {"arquivo": caminho} | {"url": ...} | {"drive": id}, com "alternativas": [mesmo formato]
  opcional, tentadas em ordem se a primeira falhar.
"""
import json
import re
from pathlib import Path

TIPOS = ("par", "ab", "escolha", "nota")
BOTOES_PAR = [
    {"valor": "sim", "rotulo": "Sim", "tecla": "s"},
    {"valor": "nao", "rotulo": "Não", "tecla": "n"},
    {"valor": "nao_sei", "rotulo": "Não dá para saber", "tecla": "d"},
]
RESPOSTAS_FIXAS = {"ab": {"ambas_boas", "ambas_ruins", "nao_sei"}, "escolha": {"nenhum", "nao_sei"}}
CAMPOS_TOPO = {"teste", "projeto", "titulo", "introducao", "tempo_min", "tipo", "pergunta", "botoes", "rotulos_paineis",
               "exemplo", "comentario", "fim", "config", "analise", "itens", "descricao", "_nota"}
CAMPOS_ITEM = {"id", "tipo", "pergunta", "texto", "paineis", "opcoes", "escala", "oculto", "controle", "repetir"}


class ErroSpec(ValueError):
    pass


def carregar(caminho):
    p = Path(caminho)
    texto = p.read_text(encoding="utf-8")
    if p.suffix in (".yaml", ".yml"):
        import yaml  # opcional
        return yaml.safe_load(texto)
    return json.loads(texto)


def fontes_de(midia):
    """Lista de fontes em ordem de tentativa."""
    if not midia:
        return []
    principal = {k: v for k, v in midia.items() if k in ("arquivo", "url", "drive")}
    return [principal] + list(midia.get("alternativas") or [])


def _checar_midia(m, onde, erros):
    if m is None:
        return
    if not isinstance(m, dict):
        erros.append(f"{onde}: midia deve ser objeto")
        return
    for f in fontes_de(m):
        chaves = [k for k in ("arquivo", "url", "drive") if f.get(k)]
        if len(chaves) != 1:
            erros.append(f"{onde}: cada fonte de mídia precisa de exatamente um entre arquivo, url, drive")
        elif "url" in chaves and not re.match(r"^https?://", f["url"]):
            erros.append(f"{onde}: url precisa começar com http(s)://")


def validar(s):
    """Devolve (erros, avisos). Erro impede criar o teste."""
    erros, avisos = [], []
    if not isinstance(s, dict):
        return ["o molde deve ser um objeto JSON"], []
    for k in s:
        if k not in CAMPOS_TOPO:
            avisos.append(f"campo de topo desconhecido ignorado: {k}")
    if not re.match(r"^[a-z0-9][a-z0-9-]{2,62}$", str(s.get("teste", ""))):
        erros.append("teste: slug de 3 a 63 caracteres, minúsculas, números e hífen")
    if not s.get("titulo"):
        erros.append("titulo é obrigatório")
    intro = s.get("introducao")
    if isinstance(intro, str):
        intro = [intro]
    if not intro:
        erros.append("introducao é obrigatória (2 a 4 frases)")
    elif not 1 <= len(intro) <= 4:
        avisos.append("introducao: o combinado é de 2 a 4 frases")
    tipo_topo = s.get("tipo")
    if tipo_topo is not None and tipo_topo not in TIPOS:
        erros.append(f"tipo inválido: {tipo_topo}")
    itens = s.get("itens")
    if not isinstance(itens, list) or not itens:
        erros.append("itens: lista não vazia")
        return erros, avisos
    ids = set()
    bts = s.get("botoes") or BOTOES_PAR
    if not isinstance(bts, list) or any(not isinstance(b, dict) or not b.get("valor") or not b.get("rotulo") for b in bts):
        erros.append("botoes: lista de {valor, rotulo, tecla opcional}")
        bts = BOTOES_PAR
    valores_par = [b["valor"] for b in bts]
    if len(set(valores_par)) != len(valores_par):
        erros.append("botoes: valores repetidos")
    valores_par = set(valores_par)
    for n, it in enumerate(itens, 1):
        onde = f"item {it.get('id', n)}"
        for k in it:
            if k not in CAMPOS_ITEM:
                avisos.append(f"{onde}: campo desconhecido ignorado: {k}")
        iid = it.get("id")
        if not iid or not re.match(r"^[A-Za-z0-9_.-]{1,40}$", str(iid)):
            erros.append(f"{onde}: id obrigatório (letras, números, _ . -)")
        elif iid in ids:
            erros.append(f"{onde}: id repetido")
        ids.add(iid)
        tipo = it.get("tipo") or tipo_topo
        if tipo not in TIPOS:
            erros.append(f"{onde}: tipo ausente ou inválido")
            continue
        for j, p in enumerate(it.get("paineis") or []):
            if not (p.get("texto") or p.get("midia")):
                erros.append(f"{onde}: painel {j + 1} sem texto nem mídia")
            _checar_midia(p.get("midia"), f"{onde} painel {j + 1}", erros)
        ops = it.get("opcoes") or []
        if tipo == "par" and len(it.get("paineis") or []) != 2:
            erros.append(f"{onde}: tipo par precisa de exatamente 2 painéis")
        if tipo == "ab" and len(ops) != 2:
            erros.append(f"{onde}: tipo ab precisa de exatamente 2 opções")
        if tipo == "escolha" and len(ops) < 2:
            erros.append(f"{onde}: tipo escolha precisa de 2 ou mais opções")
        if tipo in ("ab", "escolha"):
            oids = [o.get("id") for o in ops]
            if any(not o for o in oids) or len(set(oids)) != len(oids):
                erros.append(f"{onde}: cada opção precisa de id único")
            for o in ops:
                if not (o.get("texto") or o.get("midia")):
                    erros.append(f"{onde}: opção {o.get('id')} sem texto nem mídia")
                _checar_midia(o.get("midia"), f"{onde} opção {o.get('id')}", erros)
        if not (it.get("texto") or it.get("paineis") or ops):
            erros.append(f"{onde}: sem conteúdo (texto, painéis ou opções)")
        ctl = it.get("controle")
        if ctl is not None:
            ok = (tipo == "par" and ctl in valores_par) or \
                 (tipo in ("ab", "escolha") and (ctl in {o.get("id") for o in ops} or ctl in RESPOSTAS_FIXAS[tipo])) or \
                 (tipo == "nota" and str(ctl) in {"1", "2", "3", "4", "5"})
            if not ok:
                erros.append(f"{onde}: controle '{ctl}' não é uma resposta possível")
        oc = it.get("oculto")
        if oc is not None and not isinstance(oc, dict):
            erros.append(f"{onde}: oculto deve ser objeto")
    escolhas = [it for it in itens if (it.get("tipo") or tipo_topo) == "escolha"]
    if len(escolhas) >= 2:
        assinaturas = {tuple((o.get("id"), o.get("texto")) for o in (it.get("opcoes") or [])) for it in escolhas}
        if len(assinaturas) == 1:
            erros.append("escolha: as opções são as mesmas em todos os itens, ou seja, respostas fixas. Use tipo par com "
                         "'botoes' (ordem fixa, no rodapé); escolha sorteia a ordem e serve para comparar saídas diferentes")
    n_rep = sum(1 for it in itens if it.get("repetir"))
    n_ctl = sum(1 for it in itens if it.get("controle") is not None)
    total = len(itens) + n_rep
    if total > 40:
        avisos.append(f"{total} telas: acima do combinado (20 a 30, até uns 40)")
    if n_ctl == 0:
        avisos.append("nenhuma pergunta de controle")
    if n_rep == 0:
        avisos.append("nenhuma repetição: não dá para medir consistência")
    ex = s.get("exemplo")
    if ex:
        for j, p in enumerate(ex.get("paineis") or []):
            _checar_midia(p.get("midia"), f"exemplo painel {j + 1}", erros)
        tex = ex.get("tipo") or tipo_topo
        exops = ex.get("opcoes") or []
        if any(o.get("midia") for o in exops):
            erros.append("exemplo: opções com mídia ainda não são aceitas; use texto")
        resp = ex.get("resposta")
        if resp is None:
            avisos.append("exemplo sem resposta marcada")
        else:
            possiveis = {
                "par": valores_par,
                "ab": {"1", "2", "ambas_boas", "ambas_ruins"} | {o.get("id") for o in exops},
                "escolha": {str(i + 1) for i in range(len(exops))} | {o.get("id") for o in exops} | RESPOSTAS_FIXAS["escolha"],
                "nota": {"1", "2", "3", "4", "5"},
            }.get(tex, set())
            if str(resp) not in possiveis:
                erros.append(f"exemplo: resposta '{resp}' não aparece entre as respostas da tela ({tex}); "
                             "sem isso o exemplo não mostra qual é a certa")
    return erros, avisos


def midias(s):
    """Todas as mídias do molde, como referências (dict) que serão trocadas por ids."""
    out = []
    ex = s.get("exemplo") or {}
    for p in ex.get("paineis") or []:
        if p.get("midia"):
            out.append(p["midia"])
    for it in s["itens"]:
        for p in it.get("paineis") or []:
            if p.get("midia"):
                out.append(p["midia"])
        for o in it.get("opcoes") or []:
            if o.get("midia"):
                out.append(o["midia"])
    return out


def resolver(s, ids_midia):
    """Converte o molde no payload de av.criar_teste. ids_midia: id(midia_dict) -> uuid."""
    def painel(p, rotulo_padrao=None):
        d = {"rotulo": p.get("rotulo") or rotulo_padrao, "texto": p.get("texto")}
        if p.get("midia"):
            d["midia"] = ids_midia[id(p["midia"])]
        return {k: v for k, v in d.items() if v is not None}

    rot = s.get("rotulos_paineis") or []
    tipo_topo = s.get("tipo")
    itens = []
    for it in s["itens"]:
        tipo = it.get("tipo") or tipo_topo
        pub = {"pergunta": it.get("pergunta"), "texto": it.get("texto"), "escala": it.get("escala"),
               "paineis": [painel(p, rot[j] if j < len(rot) else None) for j, p in enumerate(it.get("paineis") or [])] or None}
        d = {"id": str(it["id"]), "tipo": tipo, "publico": {k: v for k, v in pub.items() if v is not None},
             "oculto": it.get("oculto") or {}, "repetir": bool(it.get("repetir"))}
        if it.get("controle") is not None:
            d["papel"] = "controle"
            d["resposta_controle"] = str(it["controle"])
        if tipo in ("ab", "escolha"):
            d["opcoes"] = []
            for o in it["opcoes"]:
                op = {"texto": o.get("texto")}
                if o.get("midia"):
                    op["midia"] = ids_midia[id(o["midia"])]
                d["opcoes"].append({"id": str(o["id"]), "publico": {k: v for k, v in op.items() if v is not None},
                                    "oculto": o.get("oculto") or {}})
        itens.append(d)
    ex = s.get("exemplo")
    if ex:
        ex = dict(ex)
        ex["paineis"] = [painel(p, rot[j] if j < len(rot) else None) for j, p in enumerate(ex.get("paineis") or [])]
    intro = s.get("introducao")
    payload = {
        "teste": s["teste"], "projeto": s.get("projeto"), "titulo": s["titulo"],
        "introducao": [intro] if isinstance(intro, str) else intro,
        "tempo_min": s.get("tempo_min"), "tipo": tipo_topo, "pergunta": s.get("pergunta"),
        "botoes": s.get("botoes") or (BOTOES_PAR if any((i.get("tipo") or tipo_topo) == "par" for i in s["itens"]) else None),
        "exemplo": ex, "comentario": s.get("comentario", True), "fim": s.get("fim"),
        "config": s.get("config") or {}, "analise": s.get("analise") or {}, "itens": itens,
    }
    return {k: v for k, v in payload.items() if v is not None}


def tempo_estimado(s, seg_por_tela=22):
    n = len(s["itens"]) + sum(1 for it in s["itens"] if it.get("repetir"))
    return max(1, round((n * seg_por_tela + 60) / 60))
