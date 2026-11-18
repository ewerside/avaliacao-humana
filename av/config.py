"""Configuração: URL e chave pública do Supabase, token de admin (só no .env) e o proxy de mídia do n8n."""
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

URL_PADRAO = "https://wasbvkkavtmrxssytwho.supabase.co"
CHAVE_PUBLICA_PADRAO = "sb_publishable_QYf4rI8sp3Q3EaJ3Rs5PVQ_UT0FI5aO"  # publicável: feita para o navegador
BUCKET = "av-midia"
PAGINA_PADRAO = "https://ewerside.github.io/avaliacao-humana/"
N8N_MIDIA_PADRAO = "https://ewerside.duckdns.org/webhook/teste-avaliacao-midia"


def _ler_env():
    """Lê .env da pasta atual e da raiz do repositório, sem sobrescrever o ambiente."""
    vals = {}
    for p in (Path.cwd() / ".env", RAIZ / ".env"):
        if p.exists():
            for linha in p.read_text(encoding="utf-8").splitlines():
                linha = linha.strip()
                if not linha or linha.startswith("#") or "=" not in linha:
                    continue
                k, v = linha.split("=", 1)
                vals.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return vals


def obter(nome, padrao=None):
    return os.environ.get(nome) or _ler_env().get(nome) or padrao


def url():
    return obter("AV_SUPABASE_URL", URL_PADRAO).rstrip("/")


def chave_publica():
    return obter("AV_CHAVE_PUBLICA", CHAVE_PUBLICA_PADRAO)


def token_admin():
    t = obter("AV_TOKEN_ADMIN")
    if not t:
        raise SystemExit("Sem AV_TOKEN_ADMIN. Rode `python -m av token` e registre o hash pelo MCP do Supabase.")
    return t


def pagina():
    return obter("AV_PAGINA", PAGINA_PADRAO)


def n8n_midia():
    return obter("AV_N8N_MIDIA", N8N_MIDIA_PADRAO)


def caminho_env():
    return Path.cwd() / ".env"
