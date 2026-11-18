# Instruções para o Claude neste repositório

Sistema de avaliação humana cega do Ewerton. Responda em português, direto, sem linguagem inflada e sem travessões.

- Repositório público: só código. Nunca commitar molde com dados reais, resposta de IA, gabarito, nome de pessoa, link pessoal (`?s=`), token ou chave secreta. Moldes reais ficam no repositório do projeto que pediu o teste.
- A chave em `docs/config.js` é a publicável do Supabase, feita para o navegador. Nenhuma chave secreta do Supabase entra aqui nem no `.env`; o admin usa o token de curta duração (`python -m av token`), registrado pelo MCP.
- Banco: projeto Supabase `ewerside-geral` (org `ewerside`), schema `av`. Mudança de banco é migração nova em `supabase/migrations/`, aplicada pelo MCP; teste com dados falsos e rode os avisos de segurança depois.
- O navegador nunca pode receber campo oculto. Ao mexer em `av_carregar`, confira com um teste que procura as chaves ocultas na resposta.
- Análises usam o código do avaliador, nunca o nome.
- No n8n, chave só por bloco copiado do fluxo "Chaves do n8n · blocos para copiar (não roda)", com autorização do Ewerton para aquele uso. Nunca ler, digitar ou mover uma chave.
- Mudou o texto público de um teste, muda a versão (automático pelo hash). Não edite versão já respondida no banco.
