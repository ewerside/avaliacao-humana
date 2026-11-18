"""Gera o JSON do fluxo n8n "Avaliação humana · mídia" (proxy de imagens para o script de criação de teste).

POST /webhook/teste-avaliacao-midia  {"token": "<token de admin>", "fonte": {"drive": "<id>"} | {"url": "https://..."}}
Responde com os bytes da imagem, ou JSON {ok:false, erro} com status 403/400.
O token é conferido no Supabase (av_admin 'validar') antes de qualquer download.
A credencial do Drive vem do bloco "Google Drive · API" do fluxo "Chaves do n8n" (só a referência; uso autorizado
pelo Ewerton em 18/11/2026 para baixar fotos pelo id).
"""
import json
import sys
import uuid

SUPABASE = "https://wasbvkkavtmrxssytwho.supabase.co"
CHAVE_PUBLICA = "sb_publishable_QYf4rI8sp3Q3EaJ3Rs5PVQ_UT0FI5aO"  # publicável, a mesma da página
CRED_DRIVE = {"googleDriveOAuth2Api": {"id": "grJHqOgt11g8Jveb", "name": "Google Drive account"}}


def node(name, typ, ver, pos, params, cred=None, extra=None):
    n = {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, "av-midia/" + name)), "name": name, "type": typ,
         "typeVersion": ver, "position": pos, "parameters": params}
    if cred:
        n["credentials"] = cred
    if extra:
        n.update(extra)
    return n


def se(name, pos, conds):
    return node(name, "n8n-nodes-base.if", 2, pos, {
        "conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose"},
                       "conditions": [dict(id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"cond/{name}/{i}")), **c) for i, c in enumerate(conds)],
                       "combinator": "and"}, "options": {}})


JS_PREPARAR = r"""// Valida a fonte. Bloqueia endereços internos (o n8n não pode virar porta para a rede local).
const b = ($('Webhook teste-avaliacao-midia').first().json.body) || {};
const f = b.fonte || {};
let rota = '', erro = '';
if (f.drive) {
  if (!/^[A-Za-z0-9_-]{10,200}$/.test(String(f.drive))) erro = 'id do Drive inválido'; else rota = 'drive';
} else if (f.url) {
  // sem URL(): o sandbox do Code node não tem; parse por expressão regular
  const m = /^(https?):\/\/(?:[^@\/?#]*@)?(\[[^\]]+\]|[^\/?#:]+)(?::(\d+))?(?:[\/?#]|$)/i.exec(String(f.url));
  if (!m) erro = 'url inválida (só http ou https)';
  else {
    const h = m[2].toLowerCase().replace(/^\[|\]$/g, '');
    const interno = /^(localhost|0\.0\.0\.0|127\.|10\.|192\.168\.|169\.254\.|172\.(1[6-9]|2\d|3[01])\.|::1$|f[cd][0-9a-f]{2}:|0x)/.test(h)
      || /\.(local|internal|localhost)$/.test(h) || h === 'ewerside.duckdns.org' || !/\./.test(h) || /^[\d.]+$/.test(h) && !/^\d+\.\d+\.\d+\.\d+$/.test(h);
    if (interno) erro = 'endereço não permitido';
    else rota = 'url';
  }
} else erro = 'fonte sem drive nem url';
return [{ json: { token: String(b.token || ''), rota, erro, drive: String(f.drive || ''), url: String(f.url || '') } }];"""

nodes = [
    node("Webhook teste-avaliacao-midia", "n8n-nodes-base.webhook", 2, [0, 300],
         {"httpMethod": "POST", "path": "teste-avaliacao-midia", "responseMode": "responseNode", "options": {}},
         extra={"webhookId": str(uuid.uuid5(uuid.NAMESPACE_URL, "av-midia/webhook"))}),
    node("Preparar", "n8n-nodes-base.code", 2, [220, 300], {"jsCode": JS_PREPARAR}),
    node("Conferir token", "n8n-nodes-base.httpRequest", 4.2, [440, 300], {
        "method": "POST", "url": SUPABASE + "/rest/v1/rpc/av_admin",
        "sendHeaders": True, "headerParameters": {"parameters": [{"name": "apikey", "value": CHAVE_PUBLICA}]},
        "sendBody": True, "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify({ p_token: $json.token, p_acao: 'validar', p_dados: {} }) }}",
        "options": {"response": {"response": {"fullResponse": True, "neverError": True}}, "timeout": 15000}}),
    se("Pode baixar?", [660, 300], [
        {"leftValue": "={{ $json.statusCode }}", "rightValue": 200, "operator": {"type": "number", "operation": "equals"}},
        {"leftValue": "={{ $('Preparar').first().json.erro }}", "rightValue": "", "operator": {"type": "string", "operation": "empty", "singleValue": True}},
    ]),
    se("Drive?", [880, 200], [
        {"leftValue": "={{ $('Preparar').first().json.rota }}", "rightValue": "drive", "operator": {"type": "string", "operation": "equals"}}]),
    node("Baixar do Drive", "n8n-nodes-base.httpRequest", 4.2, [1100, 100], {
        "method": "GET", "url": "={{ 'https://www.googleapis.com/drive/v3/files/' + $('Preparar').first().json.drive }}",
        "sendQuery": True, "queryParameters": {"parameters": [{"name": "alt", "value": "media"}, {"name": "supportsAllDrives", "value": "true"}]},
        "authentication": "predefinedCredentialType", "nodeCredentialType": "googleDriveOAuth2Api",
        "options": {"response": {"response": {"responseFormat": "file", "outputPropertyName": "data", "neverError": True}}, "timeout": 60000}},
        CRED_DRIVE),
    node("Baixar URL", "n8n-nodes-base.httpRequest", 4.2, [1100, 300], {
        "method": "GET", "url": "={{ $('Preparar').first().json.url }}",
        "sendHeaders": True, "headerParameters": {"parameters": [
            {"name": "User-Agent", "value": "Mozilla/5.0 (avaliacao-humana)"}, {"name": "Accept", "value": "image/*,*/*;q=0.5"}]},
        "options": {"response": {"response": {"responseFormat": "file", "outputPropertyName": "data", "neverError": True}},
                    "redirect": {"redirect": {"maxRedirects": 3}}, "timeout": 30000}}),
    node("Responder imagem", "n8n-nodes-base.respondToWebhook", 1.1, [1320, 200],
         {"respondWith": "binary", "options": {}}),
    node("Responder recusa", "n8n-nodes-base.respondToWebhook", 1.1, [880, 420],
         {"respondWith": "json",
          "responseBody": "={{ JSON.stringify({ ok: false, erro: $('Preparar').first().json.erro || 'token de admin inválido ou vencido' }) }}",
          "options": {"responseCode": 403}}),
]


def liga(a, b, saida=0):
    return a, b, saida


ligacoes = [liga("Webhook teste-avaliacao-midia", "Preparar"), liga("Preparar", "Conferir token"),
            liga("Conferir token", "Pode baixar?"), liga("Pode baixar?", "Drive?", 0), liga("Pode baixar?", "Responder recusa", 1),
            liga("Drive?", "Baixar do Drive", 0), liga("Drive?", "Baixar URL", 1),
            liga("Baixar do Drive", "Responder imagem"), liga("Baixar URL", "Responder imagem")]
connections = {}
for a, b, s in ligacoes:
    saidas = connections.setdefault(a, {"main": []})["main"]
    while len(saidas) <= s:
        saidas.append([])
    saidas[s].append({"node": b, "type": "main", "index": 0})

fluxo = {"name": "Avaliação humana · mídia", "nodes": nodes, "connections": connections,
         "settings": {"executionOrder": "v1", "saveDataSuccessExecution": "none", "saveDataErrorExecution": "all"}}
json.dump(fluxo, sys.stdout, ensure_ascii=False)
