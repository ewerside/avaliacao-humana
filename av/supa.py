"""Cliente mínimo do Supabase: RPC público, RPC de admin (com token) e upload no Storage."""
import json
import time
import urllib.error
import urllib.request

from . import config


class ErroSupabase(RuntimeError):
    pass


def _req(metodo, caminho, corpo=None, cabecalhos=None, tentativas=3):
    h = {"apikey": config.chave_publica(), "Content-Type": "application/json"}
    h.update(cabecalhos or {})
    dados = None if corpo is None else (corpo if isinstance(corpo, bytes) else json.dumps(corpo).encode())
    for n in range(tentativas):
        r = urllib.request.Request(config.url() + caminho, data=dados, headers=h, method=metodo)
        try:
            with urllib.request.urlopen(r, timeout=60) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            corpo_erro = e.read()
            if e.code >= 500 and n < tentativas - 1:
                time.sleep(1 + n)
                continue
            return e.code, corpo_erro
        except urllib.error.URLError as e:
            if n < tentativas - 1:
                time.sleep(1 + n)
                continue
            raise ErroSupabase(f"sem conexão com o Supabase ({e.reason}); o domínio *.supabase.co está liberado?") from e


def rpc(funcao, **args):
    st, corpo = _req("POST", f"/rest/v1/rpc/{funcao}", args)
    if st >= 300:
        raise ErroSupabase(f"{funcao}: HTTP {st}: {corpo[:300].decode(errors='replace')}")
    return json.loads(corpo)


def admin(acao, dados=None):
    st, corpo = _req("POST", "/rest/v1/rpc/av_admin",
                     {"p_token": config.token_admin(), "p_acao": acao, "p_dados": dados or {}})
    if st >= 300:
        raise ErroSupabase(f"admin/{acao}: HTTP {st}: {corpo[:300].decode(errors='replace')}")
    return json.loads(corpo)


def enviar_arquivo(caminho, dados, tipo="image/jpeg"):
    st, corpo = _req("POST", f"/storage/v1/object/{config.BUCKET}/{caminho}", dados,
                     {"Content-Type": tipo, "Cache-Control": "max-age=31536000"})
    if st >= 300:
        raise ErroSupabase(f"upload {caminho}: HTTP {st}: {corpo[:300].decode(errors='replace')}")


def url_publica(caminho):
    return f"{config.url()}/storage/v1/object/public/{config.BUCKET}/{caminho}"
