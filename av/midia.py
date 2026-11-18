"""Mídia: busca a imagem (arquivo local, URL ou Drive), reduz, tira metadados e sobe no Storage com bilhete.

Fontes que a sessão não alcança (Drive, sites fora da lista de domínios) passam pelo fluxo do n8n
"Avaliação humana · mídia", que confere o token de admin no Supabase antes de buscar.
"""
import hashlib
import io
import json
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, ImageOps

from . import config, supa
from .spec import fontes_de

LADO_MAIOR = 1200
LADO_MINI = 400
UA = "Mozilla/5.0 (avaliacao-humana; +https://github.com/ewerside/avaliacao-humana)"


def chave_origem(fonte):
    """Identidade da fonte (para reaproveitar o upload entre testes)."""
    return "f1:" + hashlib.sha256(json.dumps(fonte, sort_keys=True).encode()).hexdigest()[:40]


def _baixar_url(url, limite=15_000_000):
    r = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "image/*,*/*;q=0.5"})
    with urllib.request.urlopen(r, timeout=30) as resp:
        dados = resp.read(limite + 1)
    if len(dados) > limite:
        raise ValueError("imagem grande demais")
    return dados


def _baixar_n8n(fonte, limite=25_000_000):
    corpo = json.dumps({"token": config.token_admin(), "fonte": fonte}).encode()
    r = urllib.request.Request(config.n8n_midia(), data=corpo, method="POST",
                               headers={"Content-Type": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(r, timeout=90) as resp:
        tipo = resp.headers.get("Content-Type", "")
        dados = resp.read(limite + 1)
    if "json" in tipo:
        raise ValueError("n8n: " + dados[:300].decode(errors="replace"))
    if len(dados) > limite:
        raise ValueError("imagem grande demais")
    return dados


def baixar(fonte, base=Path(".")):
    """Bytes da fonte. Tenta direto; se a rede da sessão bloquear, usa o n8n."""
    if fonte.get("arquivo"):
        return (base / fonte["arquivo"]).read_bytes(), "arquivo"
    if fonte.get("drive"):
        return _baixar_n8n({"drive": fonte["drive"]}), "n8n-drive"
    try:
        return _baixar_url(fonte["url"]), "direto"
    except (urllib.error.URLError, OSError, ValueError):
        return _baixar_n8n({"url": fonte["url"]}), "n8n-url"


def reduzir(dados, lado):
    im = Image.open(io.BytesIO(dados))
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA", "P"):
        fundo = Image.new("RGB", im.size, (255, 255, 255))
        im = im.convert("RGBA")
        fundo.paste(im, mask=im.split()[-1])
        im = fundo
    else:
        im = im.convert("RGB")
    im.thumbnail((lado, lado), Image.LANCZOS)  # nunca amplia
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85 if lado > 600 else 80, optimize=True, progressive=True)  # sem EXIF
    return buf.getvalue(), im.size


def processar(midias, base=Path("."), log=print):
    """Sobe as mídias que faltam. midias: lista de dicts do molde. Devolve id(dict) -> uuid e relatório."""
    por_chave = {}
    for m in midias:
        por_chave.setdefault(chave_origem(fontes_de(m)[0]), []).append(m)
    existentes = supa.admin("midias_por_origem", {"chaves": list(por_chave)}) if por_chave else {}
    faltam = [k for k in por_chave if k not in existentes]
    bilhetes = supa.admin("bilhetes", {"n": len(faltam)}) if faltam else []
    ids, relatorio = {}, []
    for k, ms in por_chave.items():
        if k in existentes:
            uid = existentes[k]["id"]
            relatorio.append({"chave": k, "status": "reaproveitada"})
        else:
            prefixo = bilhetes.pop()
            erro, usado, dados = None, None, None
            for f in fontes_de(ms[0]):
                try:
                    dados, via = baixar(f, base)
                    Image.open(io.BytesIO(dados)).verify()
                    usado = {"fonte": f, "via": via}
                    break
                except Exception as e:  # tenta a próxima fonte
                    erro = f"{type(e).__name__}: {e}"
                    dados = None
            if dados is None:
                raise RuntimeError(f"mídia {fontes_de(ms[0])[0]} falhou em todas as fontes: {erro}")
            grande, (w, h) = reduzir(dados, LADO_MAIOR)
            mini, _ = reduzir(dados, LADO_MINI)
            supa.enviar_arquivo(prefixo + ".jpg", grande)
            supa.enviar_arquivo(prefixo + "-p.jpg", mini)
            uid = supa.admin("registrar_midia", {
                "caminho": prefixo + ".jpg", "caminho_mini": prefixo + "-p.jpg", "largura": w, "altura": h,
                "bytes": len(grande), "sha256": hashlib.sha256(grande).hexdigest(),
                "origem": {"fonte": usado["fonte"], "via": usado["via"], "tentativas": fontes_de(ms[0])},
                "origem_chave": k})
            relatorio.append({"chave": k, "status": "enviada", "via": usado["via"],
                              "fonte_usada": 0 if usado["fonte"] == fontes_de(ms[0])[0] else
                              fontes_de(ms[0]).index(usado["fonte"]), "w": w, "h": h, "kb": len(grande) // 1024})
            log(f"  mídia {len(relatorio)}/{len(por_chave)}: {usado['via']} {w}x{h} {len(grande) // 1024} KB")
        for m in ms:
            ids[id(m)] = uid
    return ids, relatorio
