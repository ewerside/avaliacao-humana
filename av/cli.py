"""Linha de comando.

  python -m av token                         gera token de admin no .env e imprime o SQL para registrar o hash (pelo MCP)
  python -m av validar molde.json            confere o molde sem gravar nada
  python -m av criar molde.json [--links "Ana,Bia"] [--relatorio saida.json]
  python -m av links TESTE --nomes "Ana,Bia" [--versao N]
  python -m av resultados TESTE --saida pasta/ [--versao N]
  python -m av encerrar TESTE | reabrir TESTE
"""
import argparse
import hashlib
import json
import secrets
import sys
from pathlib import Path

from . import VERSAO, config, midia, resultados, spec, supa


def link_geral(teste):
    return f"{config.pagina()}?t={teste}"


def link_pessoal(sessao):
    return f"{config.pagina()}?s={sessao}"


def cmd_token(a):
    t = secrets.token_urlsafe(32)
    p = config.caminho_env()
    linhas = [l for l in (p.read_text(encoding="utf-8").splitlines() if p.exists() else []) if not l.startswith("AV_TOKEN_ADMIN=")]
    linhas.append(f"AV_TOKEN_ADMIN={t}")
    p.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    p.chmod(0o600)
    h = hashlib.sha256(t.encode()).hexdigest()
    print(f"Token gravado em {p} (fora do git). Registre o hash pelo MCP do Supabase, projeto ewerside-geral:")
    print(f"select av.registrar_token('{h}', {a.horas});")
    return 0


def _checar(s):
    erros, avisos = spec.validar(s)
    for x in avisos:
        print("aviso:", x)
    for x in erros:
        print("ERRO:", x)
    return not erros


def cmd_validar(a):
    s = spec.carregar(a.molde)
    ok = _checar(s)
    n = len(s.get("itens") or [])
    rep = sum(1 for i in s.get("itens") or [] if i.get("repetir"))
    ctl = sum(1 for i in s.get("itens") or [] if i.get("controle") is not None)
    print(f"{n} itens ({ctl} controles) + {rep} repetições = {n + rep} telas; mídias: {len(spec.midias(s)) if ok else '?'}; "
          f"tempo estimado {spec.tempo_estimado(s) if ok else '?'} min")
    return 0 if ok else 1


def cmd_criar(a):
    base = Path(a.molde).resolve().parent
    s = spec.carregar(a.molde)
    if not _checar(s):
        return 1
    if not s.get("tempo_min"):
        s["tempo_min"] = spec.tempo_estimado(s)
    supa.admin("validar")
    ms = spec.midias(s)
    print(f"Mídias: {len(ms)}")
    ids, rel = midia.processar(ms, base=base) if ms else ({}, [])
    payload = spec.resolver(s, ids)
    r = supa.admin("criar_teste", payload)
    print(f"Teste {r['teste']} versão {r['versao']} ({'nova' if r['nova'] else 'já existia, nada mudou'}).")
    print("Link geral:", link_geral(r["teste"]))
    saida = {"teste": r["teste"], "versao": r["versao"], "hash": r["hash"], "nova": r["nova"], "link_geral": link_geral(r["teste"]),
             "midias": _midias_por_item(s, rel), "versao_av": VERSAO}
    if a.links:
        nomes = [n.strip() for n in a.links.split(",") if n.strip()]
        ls = supa.admin("criar_sessoes", {"teste": r["teste"], "nomes": nomes})
        print("Links pessoais (o nome não vai para o relatório):")
        for x in ls:
            print(f"  {x['nome']}: {link_pessoal(x['sessao'])}")
        saida["links_pessoais"] = len(ls)
    if a.relatorio:
        Path(a.relatorio).write_text(json.dumps(saida, ensure_ascii=False, indent=1), encoding="utf-8")
        print("Relatório:", a.relatorio)
    return 0


def _midias_por_item(s, rel):
    """Para cada item e painel/opção: qual fonte foi usada (0 = principal, 1+ = alternativa)."""
    por_chave = {x["chave"]: x for x in rel}
    out = {}
    for it in s["itens"]:
        partes = [("painel", j, p) for j, p in enumerate(it.get("paineis") or [])] + \
                 [("opcao", o.get("id"), o) for o in it.get("opcoes") or []]
        for tipo, idx, p in partes:
            m = p.get("midia")
            if not m:
                continue
            x = por_chave.get(midia.chave_origem(spec.fontes_de(m)[0]), {})
            out.setdefault(str(it["id"]), {})[f"{tipo}{idx}"] = {"status": x.get("status"), "fonte_usada": x.get("fonte_usada"),
                                                                  "via": x.get("via"), "w": x.get("w"), "h": x.get("h")}
    return out


def cmd_links(a):
    nomes = [n.strip() for n in a.nomes.split(",") if n.strip()]
    for x in supa.admin("criar_sessoes", {"teste": a.teste, "nomes": nomes, "versao": a.versao}):
        print(f"{x['nome']}: {link_pessoal(x['sessao'])}")
    return 0


def cmd_resultados(a):
    exp = supa.admin("exportar", {"teste": a.teste, "versao": a.versao})
    met = resultados.gravar(exp, a.saida)
    print(resultados.resumo(met))
    print(f"Arquivos em {a.saida}: export.json, respostas.csv, metricas.json, resultado.md")
    return 0


def cmd_estado(a, acao):
    supa.admin(acao, {"teste": a.teste})
    print(f"{a.teste}: {acao} ok")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m av", description="Avaliação humana cega")
    sp = p.add_subparsers(dest="cmd", required=True)
    x = sp.add_parser("token"); x.add_argument("--horas", type=int, default=8)
    x = sp.add_parser("validar"); x.add_argument("molde")
    x = sp.add_parser("criar"); x.add_argument("molde"); x.add_argument("--links"); x.add_argument("--relatorio")
    x = sp.add_parser("links"); x.add_argument("teste"); x.add_argument("--nomes", required=True); x.add_argument("--versao", type=int)
    x = sp.add_parser("resultados"); x.add_argument("teste"); x.add_argument("--saida", required=True); x.add_argument("--versao", type=int)
    x = sp.add_parser("encerrar"); x.add_argument("teste")
    x = sp.add_parser("reabrir"); x.add_argument("teste")
    a = p.parse_args(argv)
    try:
        if a.cmd == "token":
            return cmd_token(a)
        if a.cmd == "validar":
            return cmd_validar(a)
        if a.cmd == "criar":
            return cmd_criar(a)
        if a.cmd == "links":
            return cmd_links(a)
        if a.cmd == "resultados":
            return cmd_resultados(a)
        if a.cmd in ("encerrar", "reabrir"):
            return cmd_estado(a, a.cmd)
    except (supa.ErroSupabase, spec.ErroSpec, RuntimeError) as e:
        print("ERRO:", e, file=sys.stderr)
        return 2
    return 1
