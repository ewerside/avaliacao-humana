# avaliacao-humana

Página de avaliação humana cega para medir quanto um juiz de IA concorda com pessoas. A pessoa abre um link no celular, se identifica com um nome ou apelido, lê uma introdução curta e responde com cliques. As respostas vão para o Supabase; um script calcula a concordância.

Este repositório tem só código. Moldes com dados reais (e com a resposta da IA ou o gabarito) ficam no repositório do projeto que pediu o teste.

## Como funciona

- **Página** (`docs/`, publicada no GitHub Pages): HTML estático, sem dependências. Fala com o Supabase só por funções RPC, com a chave publicável.
- **Banco** (`supabase/migrations/`): tabelas no schema `av`, fora da API, com RLS ligado e sem política. O navegador só chama `av_carregar`, `av_iniciar`, `av_confirmar`, `av_responder` e `av_finalizar`, que devolvem texto, imagens e botões, nunca os campos ocultos (resposta da IA, gabarito, origem de cada opção).
- **Embaralhamento no servidor**, por pessoa: ordem dos itens, repetições a pelo menos N posições da original, lado do A/B e ordem das opções. A página devolve só o que estava na tela (por exemplo, "a opção 2"); o servidor traduz.
- **Admin sem chave secreta**: `python -m av token` grava um token no `.env` e imprime o SQL que registra o hash dele (rodado pelo MCP do Supabase). Vale até 24 h. As funções de criação, links e exportação exigem esse token.
- **Imagens**: bucket público `av-midia` com caminho aleatório, 1.200 px no lado maior mais miniatura de 400 px, JPEG sem EXIF. O upload só é aceito em caminho com bilhete emitido pelo admin.
- **Mídia que a sessão não alcança** (Google Drive, sites fora da lista de domínios): o fluxo do n8n "Avaliação humana · mídia" busca os bytes, depois de conferir o token no Supabase.
- **Nomes de pessoas** ficam só em `av.avaliadores`. A exportação usa o código do avaliador (`av-xxxxxx`).

## Tipos de pergunta

| tipo | tela | respostas gravadas |
|---|---|---|
| `par` | dois painéis (esquerda/direita; no celular, em cima/embaixo) | `sim`, `nao`, `nao_sei` (ou os botões do molde) |
| `ab` | duas saídas, lados sorteados por pessoa | id da opção, `ambas_boas`, `ambas_ruins` |
| `escolha` | N opções, ordem sorteada | id da opção, `nenhum`, `nao_sei` |
| `nota` | 1 a 5 com rótulos nas pontas | a nota |

Todo item aceita comentário opcional. Cada painel ou opção pode ter imagem, texto ou os dois.

## Criar um teste

```bash
pip install pillow
python -m av token                      # registre o hash impresso pelo MCP do Supabase (projeto ewerside-geral)
python -m av validar meu-teste.json
python -m av criar meu-teste.json --relatorio criado.json [--links "Ana,Bia"]
python -m av resultados meu-teste --saida resultados/
```

O formato do molde está no topo de `av/spec.py`; `moldes/exemplo-tipos.json` usa os quatro tipos, controle e repetições. Mudou o texto público, muda a versão; as respostas antigas ficam na versão anterior.

## Resultados

`python -m av resultados` grava `export.json`, `respostas.csv`, `metricas.json` e `resultado.md`: por avaliador (tempo, acerto nos controles, consistência nas repetições), IA contra pessoa (concordância com IC de Wilson, kappa de Cohen, matriz, por estrato e ponderada pela população, precisão no positivo) e, com dois ou mais avaliadores, kappa por par e alfa de Krippendorff.

## Testes

```bash
python -m pytest -q
```

## Rede da sessão do Claude

Os scripts falam direto com `*.supabase.co`, `ewerside.duckdns.org` (fluxo de mídia do n8n), `*.gstatic.com` e `*.googleusercontent.com` (miniaturas). No claude.ai esses domínios ficam em Configurações > Recursos > Domínios adicionais permitidos.

## Recriar em outro lugar

1. Aplicar `supabase/migrations/0001_av.sql` num projeto Supabase (pelo SQL editor ou pelo MCP). Ela cria o schema `av`, as funções, o bucket `av-midia` e a política de upload com bilhete.
2. Trocar a URL do projeto e a chave publicável em `docs/config.js` e em `av/config.py`.
3. Ativar o GitHub Pages na pasta `docs/` do ramo `main`.
4. Gerar o fluxo de mídia com `python n8n/gerar_fluxo_midia.py > fluxo.json`, importar no n8n, ligar a credencial do Google Drive e publicar.
5. Rodar `python -m pytest -q` e criar `moldes/exemplo-tipos.json` para conferir o caminho inteiro.
