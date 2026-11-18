-- Avaliação humana cega (schema av). Versão 1, 18/11/2026.
--
-- Regras:
-- * Tabelas no schema av, que não é exposto pela API. RLS ligado em todas e nenhuma política:
--   o papel anon não lê nem grava tabela nenhuma.
-- * A página só chama as funções public.av_carregar, av_iniciar, av_confirmar, av_responder e
--   av_finalizar. Elas devolvem só o conteúdo público (texto, mídia, botões) e nunca os campos
--   ocultos (resposta da IA, gabarito, origem de cada opção).
-- * Funções de admin ficam em av.* (chamadas pelo MCP do Supabase, como postgres) e, no modo
--   direto, por public.av_admin com um token de admin de curta duração (só o hash fica no banco).
-- * Nome de pessoa só existe em av.avaliadores.nome; exportações usam o código do avaliador.

create extension if not exists pgcrypto with schema extensions;

create schema if not exists av;
revoke all on schema av from public;
-- usage só para a política do Storage chamar av.bilhete_valido; nenhuma tabela tem grant.
grant usage on schema av to anon, authenticated;

-- ---------------------------------------------------------------- tabelas

create table if not exists av.testes (
  id uuid primary key default gen_random_uuid(),
  slug text not null unique check (slug ~ '^[a-z0-9][a-z0-9-]{2,62}$'),
  projeto text,
  aberto boolean not null default true,
  criado_em timestamptz not null default now()
);

create table if not exists av.versoes (
  id uuid primary key default gen_random_uuid(),
  teste_id uuid not null references av.testes(id) on delete cascade,
  versao int not null,
  hash text not null,
  publico jsonb not null,          -- título, introdução, exemplo, pergunta, botões, escala
  config jsonb not null default '{}'::jsonb,   -- distância das repetições etc.
  analise jsonb not null default '{}'::jsonb,  -- oculto: como comparar com a IA, estratos
  ativa boolean not null default true,
  criado_em timestamptz not null default now(),
  unique (teste_id, versao),
  unique (teste_id, hash)
);

create table if not exists av.midias (
  id uuid primary key default gen_random_uuid(),
  caminho text not null unique,    -- no bucket av-midia
  caminho_mini text not null,
  largura int,
  altura int,
  bytes int,
  sha256 text,
  origem jsonb not null default '{}'::jsonb,   -- oculto: de onde veio
  origem_chave text unique,        -- hash da fonte, para reaproveitar o upload
  criado_em timestamptz not null default now()
);

create table if not exists av.itens (
  id uuid primary key default gen_random_uuid(),
  versao_id uuid not null references av.versoes(id) on delete cascade,
  chave text not null,
  tipo text not null check (tipo in ('par', 'ab', 'escolha', 'nota')),
  papel text not null default 'normal' check (papel in ('normal', 'controle')),
  publico jsonb not null,          -- pergunta, texto, paineis [{rotulo, texto, midia}]
  oculto jsonb not null default '{}'::jsonb,
  resposta_controle text,
  repetir boolean not null default false,
  ordem int not null,
  unique (versao_id, chave)
);

create table if not exists av.opcoes (
  id uuid primary key default gen_random_uuid(),
  item_id uuid not null references av.itens(id) on delete cascade,
  chave text not null,
  publico jsonb not null,          -- texto, midia
  oculto jsonb not null default '{}'::jsonb,
  ordem int not null,
  unique (item_id, chave)
);

create table if not exists av.avaliadores (
  id uuid primary key default gen_random_uuid(),
  codigo text not null unique,
  nome text not null check (length(nome) between 1 and 60),
  criado_em timestamptz not null default now()
);

create table if not exists av.sessoes (
  id uuid primary key default gen_random_uuid(),
  codigo text not null unique,     -- vai no link (?s=...)
  avaliador_id uuid not null references av.avaliadores(id) on delete cascade,
  versao_id uuid not null references av.versoes(id) on delete cascade,
  origem text not null check (origem in ('geral', 'pessoal')),
  semente bigint not null,
  plano jsonb not null,            -- [{pos, item, rep, opcoes:[ids na ordem exibida]}]
  criada_em timestamptz not null default now(),
  confirmada_em timestamptz,
  terminada_em timestamptz
);

create table if not exists av.respostas (
  id bigserial primary key,
  sessao_id uuid not null references av.sessoes(id) on delete cascade,
  pos int not null,
  item_id uuid not null references av.itens(id) on delete cascade,
  rep boolean not null default false,
  escolha text,                    -- canônica (sim/nao/nao_sei, chave da opção, ambas_boas...)
  exibida text,                    -- o que a página mandou
  nota int check (nota between 1 and 5),
  comentario text check (length(comentario) <= 2000),
  ms int check (ms between 0 and 86400000),
  primeira_escolha text,
  primeira_nota int,
  alteracoes int not null default 0,
  criado_em timestamptz not null default now(),
  respondido_em timestamptz not null default now(),
  unique (sessao_id, pos)
);

create table if not exists av.tokens_admin (
  hash text primary key,
  validade timestamptz not null,
  criado_em timestamptz not null default now()
);

create table if not exists av.bilhetes (
  prefixo text primary key,        -- m/<uuid>; vale para <prefixo>.jpg e <prefixo>-p.jpg
  validade timestamptz not null,
  criado_em timestamptz not null default now()
);

create index if not exists itens_versao on av.itens (versao_id);
create index if not exists opcoes_item on av.opcoes (item_id);
create index if not exists sessoes_versao on av.sessoes (versao_id);
create index if not exists respostas_item on av.respostas (item_id);

alter table av.testes enable row level security;
alter table av.versoes enable row level security;
alter table av.midias enable row level security;
alter table av.itens enable row level security;
alter table av.opcoes enable row level security;
alter table av.avaliadores enable row level security;
alter table av.sessoes enable row level security;
alter table av.respostas enable row level security;
alter table av.tokens_admin enable row level security;
alter table av.bilhetes enable row level security;

revoke all on all tables in schema av from public, anon, authenticated;
revoke all on all sequences in schema av from public, anon, authenticated;

-- ---------------------------------------------------------------- utilidades

create or replace function av.codigo(n int) returns text
language sql volatile set search_path = '' as $$
  select string_agg(substr('23456789abcdefghjkmnpqrstuvwxyz', (get_byte(x.b, i) % 31) + 1, 1), '' order by i)
  from (select extensions.gen_random_bytes(n) as b) x, generate_series(0, n - 1) as i
$$;

create or replace function av.token_valido(p_token text) returns boolean
language sql stable security definer set search_path = '' as $$
  select coalesce(length(p_token) >= 32, false) and exists (
    select 1 from av.tokens_admin t
    where t.hash = encode(extensions.digest(p_token, 'sha256'), 'hex') and t.validade > now())
$$;

create or replace function av.registrar_token(p_hash text, p_horas int default 8) returns timestamptz
language plpgsql security definer set search_path = '' as $$
declare v timestamptz := now() + make_interval(hours => least(greatest(p_horas, 1), 24));
begin
  if p_hash !~ '^[0-9a-f]{64}$' then raise exception 'hash inválido'; end if;
  delete from av.tokens_admin where validade < now();
  insert into av.tokens_admin (hash, validade) values (p_hash, v)
  on conflict (hash) do update set validade = excluded.validade;
  return v;
end $$;

create or replace function av.bilhete_valido(p_nome text) returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from av.bilhetes b
    where b.validade > now() and p_nome in (b.prefixo || '.jpg', b.prefixo || '-p.jpg'))
$$;

create or replace function av.criar_bilhetes(p_n int, p_horas int default 2) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare r jsonb := '[]'::jsonb; p text;
begin
  if p_n < 1 or p_n > 500 then raise exception 'n fora de 1..500'; end if;
  delete from av.bilhetes where validade < now() - interval '1 day';
  for i in 1..p_n loop
    p := 'm/' || gen_random_uuid()::text;
    insert into av.bilhetes (prefixo, validade) values (p, now() + make_interval(hours => least(greatest(p_horas, 1), 24)));
    r := r || to_jsonb(p);
  end loop;
  return r;
end $$;

create or replace function av.registrar_midia(p jsonb) returns uuid
language plpgsql security definer set search_path = '' as $$
declare v uuid;
begin
  insert into av.midias (caminho, caminho_mini, largura, altura, bytes, sha256, origem, origem_chave)
  values (p->>'caminho', p->>'caminho_mini', (p->>'largura')::int, (p->>'altura')::int, (p->>'bytes')::int,
          p->>'sha256', coalesce(p->'origem', '{}'::jsonb), p->>'origem_chave')
  on conflict (origem_chave) do update set
    caminho = excluded.caminho, caminho_mini = excluded.caminho_mini, largura = excluded.largura,
    altura = excluded.altura, bytes = excluded.bytes, sha256 = excluded.sha256, origem = excluded.origem
  returning id into v;
  return v;
end $$;

create or replace function av.midias_por_origem(p_chaves text[]) returns jsonb
language sql stable security definer set search_path = '' as $$
  select coalesce(jsonb_object_agg(m.origem_chave, jsonb_build_object(
    'id', m.id, 'caminho', m.caminho, 'caminho_mini', m.caminho_mini, 'largura', m.largura, 'altura', m.altura)), '{}'::jsonb)
  from av.midias m where m.origem_chave = any(p_chaves)
$$;

-- Troca {"midia": "<uuid>"} pelos caminhos públicos, em qualquer lista de painéis/opções.
create or replace function av.resolver_midia(p jsonb) returns jsonb
language sql stable security definer set search_path = '' as $$
  select case
    when p ? 'midia' and (p->>'midia') is not null then
      (p - 'midia') || coalesce((select jsonb_build_object('img', m.caminho, 'mini', m.caminho_mini, 'w', m.largura, 'h', m.altura)
                                 from av.midias m where m.id = (p->>'midia')::uuid), '{}'::jsonb)
    else p end
$$;

create or replace function av.resolver_lista(p jsonb) returns jsonb
language sql stable security definer set search_path = '' as $$
  select coalesce(jsonb_agg(av.resolver_midia(e) order by o), '[]'::jsonb)
  from jsonb_array_elements(coalesce(p, '[]'::jsonb)) with ordinality as t(e, o)
$$;

-- ---------------------------------------------------------------- criação de teste

-- Recebe a spec já resolvida (mídias trocadas por ids). Mesma parte pública = mesma versão.
create or replace function av.criar_teste(p jsonb) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  v_teste uuid; v_versao uuid; v_num int; v_hash text; v_pub jsonb; v_itens_pub jsonb;
  v_item jsonb; v_op jsonb; v_item_id uuid; v_ordem int := 0; v_oordem int; v_existente uuid;
  v_tipo text;
begin
  if coalesce(p->>'teste', '') !~ '^[a-z0-9][a-z0-9-]{2,62}$' then raise exception 'slug inválido'; end if;
  if jsonb_typeof(p->'itens') <> 'array' or jsonb_array_length(p->'itens') = 0 then raise exception 'sem itens'; end if;

  v_pub := jsonb_strip_nulls(jsonb_build_object(
    'titulo', p->'titulo', 'introducao', p->'introducao', 'tempo_min', p->'tempo_min',
    'exemplo', p->'exemplo', 'tipo', p->'tipo', 'pergunta', p->'pergunta', 'botoes', p->'botoes',
    'escala', p->'escala', 'comentario', coalesce(p->'comentario', 'true'::jsonb),
    'rotulos_paineis', p->'rotulos_paineis', 'fim', p->'fim'));
  select jsonb_agg(jsonb_build_object('chave', i->'id', 'tipo', coalesce(i->'tipo', p->'tipo'), 'publico', i->'publico',
                                      'papel', coalesce(i->'papel', '"normal"'::jsonb), 'repetir', coalesce(i->'repetir', 'false'::jsonb),
                                      'opcoes', (select jsonb_agg(jsonb_build_object('chave', o->'id', 'publico', o->'publico')) from jsonb_array_elements(coalesce(i->'opcoes', '[]'::jsonb)) o))
                   order by n)
    into v_itens_pub from jsonb_array_elements(p->'itens') with ordinality as t(i, n);
  v_hash := md5((v_pub || jsonb_build_object('itens', v_itens_pub, 'config', coalesce(p->'config', '{}'::jsonb)))::text);

  insert into av.testes (slug, projeto) values (p->>'teste', p->>'projeto')
  on conflict (slug) do update set projeto = coalesce(excluded.projeto, av.testes.projeto)
  returning id into v_teste;

  select id, versao into v_existente, v_num from av.versoes where teste_id = v_teste and hash = v_hash;
  if v_existente is not null then
    return jsonb_build_object('teste', p->>'teste', 'versao', v_num, 'versao_id', v_existente, 'nova', false, 'hash', v_hash);
  end if;

  select coalesce(max(versao), 0) + 1 into v_num from av.versoes where teste_id = v_teste;
  update av.versoes set ativa = false where teste_id = v_teste;
  insert into av.versoes (teste_id, versao, hash, publico, config, analise)
  values (v_teste, v_num, v_hash, v_pub, coalesce(p->'config', '{}'::jsonb), coalesce(p->'analise', '{}'::jsonb))
  returning id into v_versao;

  for v_item in select * from jsonb_array_elements(p->'itens') loop
    v_ordem := v_ordem + 1;
    v_tipo := coalesce(v_item->>'tipo', p->>'tipo');
    if v_tipo not in ('par', 'ab', 'escolha', 'nota') then raise exception 'tipo inválido no item %', v_item->>'id'; end if;
    insert into av.itens (versao_id, chave, tipo, papel, publico, oculto, resposta_controle, repetir, ordem)
    values (v_versao, v_item->>'id', v_tipo, coalesce(v_item->>'papel', 'normal'), coalesce(v_item->'publico', '{}'::jsonb),
            coalesce(v_item->'oculto', '{}'::jsonb), v_item->>'resposta_controle', coalesce((v_item->>'repetir')::boolean, false), v_ordem)
    returning id into v_item_id;
    if v_tipo in ('ab', 'escolha') then
      if jsonb_array_length(coalesce(v_item->'opcoes', '[]'::jsonb)) < 2 then raise exception 'item % sem opções', v_item->>'id'; end if;
      if v_tipo = 'ab' and jsonb_array_length(v_item->'opcoes') <> 2 then raise exception 'item % (ab) precisa de 2 opções', v_item->>'id'; end if;
      v_oordem := 0;
      for v_op in select * from jsonb_array_elements(v_item->'opcoes') loop
        v_oordem := v_oordem + 1;
        insert into av.opcoes (item_id, chave, publico, oculto, ordem)
        values (v_item_id, v_op->>'id', coalesce(v_op->'publico', '{}'::jsonb), coalesce(v_op->'oculto', '{}'::jsonb), v_oordem);
      end loop;
    end if;
  end loop;

  return jsonb_build_object('teste', p->>'teste', 'versao', v_num, 'versao_id', v_versao, 'nova', true, 'hash', v_hash);
end $$;

-- ---------------------------------------------------------------- sessões

-- Ordem sorteada por pessoa; repetições a pelo menos `distancia_repeticao` posições da original;
-- ordem das opções (lados do A/B) sorteada por posição, inclusive na repetição.
create or replace function av.gerar_plano(p_versao uuid, p_semente bigint) returns jsonb
language plpgsql volatile security definer set search_path = '' as $$
declare
  v_dist int; v_seq uuid[]; v_flag boolean[]; v_rep uuid[]; r uuid; n int; p0 int; ini int; alvo int;
  troca int; tmp uuid; v_plano jsonb := '[]'::jsonb; v_it record; v_ops jsonb;
begin
  select coalesce((config->>'distancia_repeticao')::int, 8) into v_dist from av.versoes where id = p_versao;
  perform setseed(((p_semente % 2000001) - 1000000)::double precision / 1000000.0);
  select array_agg(id order by rnd) into v_seq
    from (select id, random() as rnd from (select id from av.itens where versao_id = p_versao order by ordem) s) t;
  n := coalesce(array_length(v_seq, 1), 0);
  v_flag := array_fill(false, array[n]);
  select array_agg(id order by rnd) into v_rep
    from (select id, random() as rnd from (select id from av.itens where versao_id = p_versao and repetir order by ordem) s) t;
  -- original de cada repetido precisa caber antes do fim com a distância mínima
  foreach r in array coalesce(v_rep, '{}'::uuid[]) loop
    p0 := array_position(v_seq, r);
    if p0 > n - v_dist - 1 then
      for k in 1..50 loop
        troca := 1 + floor(random() * greatest(n - v_dist - 1, 1))::int;
        exit when not (v_seq[troca] = any(v_rep));
      end loop;
      if not (v_seq[troca] = any(v_rep)) then
        tmp := v_seq[troca]; v_seq[troca] := r; v_seq[p0] := tmp;
      end if;
    end if;
  end loop;
  foreach r in array coalesce(v_rep, '{}'::uuid[]) loop
    p0 := array_position(v_seq, r);
    n := array_length(v_seq, 1);
    ini := least(p0 + v_dist + 1, n + 1);
    alvo := ini + floor(random() * (n + 2 - ini))::int;
    if alvo > n + 1 then alvo := n + 1; end if;
    v_seq := v_seq[1:alvo - 1] || r || v_seq[alvo:n];
    v_flag := v_flag[1:alvo - 1] || true || v_flag[alvo:n];
  end loop;
  for i in 1..coalesce(array_length(v_seq, 1), 0) loop
    select id, tipo into v_it from av.itens where id = v_seq[i];
    if v_it.tipo in ('ab', 'escolha') then
      select jsonb_agg(id order by rnd) into v_ops from (select id, random() as rnd from av.opcoes where item_id = v_it.id order by ordem) o;
    else
      v_ops := null;
    end if;
    v_plano := v_plano || jsonb_build_array(jsonb_strip_nulls(jsonb_build_object('pos', i, 'item', v_it.id, 'rep', v_flag[i], 'opcoes', v_ops)));
  end loop;
  return v_plano;
end $$;

create or replace function av.criar_sessao(p_versao uuid, p_nome text, p_origem text) returns text
language plpgsql security definer set search_path = '' as $$
declare v_av uuid; v_cod text; v_sem bigint; v_nome text := btrim(coalesce(p_nome, ''));
begin
  if length(v_nome) < 1 or length(v_nome) > 60 then raise exception 'nome precisa ter de 1 a 60 caracteres'; end if;
  insert into av.avaliadores (codigo, nome) values ('av-' || av.codigo(6), v_nome) returning id into v_av;
  v_cod := av.codigo(12);
  v_sem := (('x' || encode(extensions.gen_random_bytes(4), 'hex'))::bit(32)::int)::bigint & 2147483647;
  insert into av.sessoes (codigo, avaliador_id, versao_id, origem, semente, plano, confirmada_em)
  values (v_cod, v_av, p_versao, p_origem, v_sem, av.gerar_plano(p_versao, v_sem),
          case when p_origem = 'geral' then now() end);
  return v_cod;
end $$;

create or replace function av.versao_id(p_slug text, p_versao int default null) returns uuid
language sql stable security definer set search_path = '' as $$
  select v.id from av.versoes v join av.testes t on t.id = v.teste_id
  where t.slug = p_slug and (p_versao is null and v.ativa or v.versao = p_versao)
  order by v.versao desc limit 1
$$;

create or replace function av.criar_sessoes(p_slug text, p_nomes text[], p_versao int default null) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare v uuid := av.versao_id(p_slug, p_versao); r jsonb := '[]'::jsonb; nm text;
begin
  if v is null then raise exception 'teste % não encontrado', p_slug; end if;
  foreach nm in array p_nomes loop
    r := r || jsonb_build_array(jsonb_build_object('nome', nm, 'sessao', av.criar_sessao(v, nm, 'pessoal')));
  end loop;
  return r;
end $$;

-- ---------------------------------------------------------------- exportação (sem nomes)

create or replace function av.exportar(p_slug text, p_versao int default null) returns jsonb
language sql stable security definer set search_path = '' as $$
  with t as (select * from av.testes where slug = p_slug),
  vs as (select v.* from av.versoes v join t on t.id = v.teste_id where p_versao is null or v.versao = p_versao)
  select jsonb_build_object(
    'teste', p_slug,
    'exportado_em', now(),
    'versoes', (select coalesce(jsonb_agg(jsonb_build_object('versao', versao, 'hash', hash, 'ativa', ativa, 'publico', publico,
                 'config', config, 'analise', analise, 'criado_em', criado_em) order by versao), '[]'::jsonb) from vs),
    'itens', (select coalesce(jsonb_agg(jsonb_build_object('versao', vs.versao, 'chave', i.chave, 'tipo', i.tipo, 'papel', i.papel,
                 'resposta_controle', i.resposta_controle, 'repetir', i.repetir, 'oculto', i.oculto, 'ordem', i.ordem,
                 'opcoes', (select jsonb_agg(jsonb_build_object('chave', o.chave, 'oculto', o.oculto) order by o.ordem) from av.opcoes o where o.item_id = i.id))
                 order by vs.versao, i.ordem), '[]'::jsonb)
              from av.itens i join vs on vs.id = i.versao_id),
    'sessoes', (select coalesce(jsonb_agg(jsonb_build_object('sessao', left(s.id::text, 8), 'avaliador', a.codigo, 'versao', vs.versao,
                 'origem', s.origem, 'total', jsonb_array_length(s.plano), 'criada_em', s.criada_em, 'confirmada_em', s.confirmada_em,
                 'terminada_em', s.terminada_em, 'respondidas', (select count(*) from av.respostas r where r.sessao_id = s.id))
                 order by s.criada_em), '[]'::jsonb)
              from av.sessoes s join vs on vs.id = s.versao_id join av.avaliadores a on a.id = s.avaliador_id),
    'respostas', (select coalesce(jsonb_agg(jsonb_build_object('sessao', left(s.id::text, 8), 'avaliador', a.codigo, 'versao', vs.versao,
                 'pos', r.pos, 'item', i.chave, 'rep', r.rep, 'escolha', r.escolha, 'nota', r.nota, 'exibida', r.exibida,
                 'comentario', r.comentario, 'ms', r.ms, 'primeira_escolha', r.primeira_escolha, 'primeira_nota', r.primeira_nota,
                 'alteracoes', r.alteracoes, 'respondido_em', r.respondido_em)
                 order by s.criada_em, r.pos), '[]'::jsonb)
              from av.respostas r join av.sessoes s on s.id = r.sessao_id join vs on vs.id = s.versao_id
              join av.avaliadores a on a.id = s.avaliador_id join av.itens i on i.id = r.item_id)
  )
$$;

-- ---------------------------------------------------------------- API pública (página)

create or replace function public.av_iniciar(p_teste text, p_nome text) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare v uuid;
begin
  select av.versao_id(p_teste, null) into v;
  if v is null or not exists (select 1 from av.testes where slug = p_teste and aberto) then
    return jsonb_build_object('ok', false, 'erro', 'Teste não encontrado ou encerrado.');
  end if;
  return jsonb_build_object('ok', true, 'sessao', av.criar_sessao(v, p_nome, 'geral'));
end $$;

create or replace function public.av_confirmar(p_sessao text, p_nome text default null) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare s av.sessoes;
begin
  select * into s from av.sessoes where codigo = p_sessao;
  if s.id is null then return jsonb_build_object('ok', false, 'erro', 'Link inválido.'); end if;
  if length(btrim(coalesce(p_nome, ''))) between 1 and 60 then
    update av.avaliadores set nome = btrim(p_nome) where id = s.avaliador_id;
  end if;
  update av.sessoes set confirmada_em = coalesce(confirmada_em, now()) where id = s.id;
  return jsonb_build_object('ok', true);
end $$;

create or replace function public.av_carregar(p_sessao text) returns jsonb
language plpgsql stable security definer set search_path = '' as $$
declare s av.sessoes; v av.versoes; t av.testes; nome text; itens jsonb;
begin
  select * into s from av.sessoes where codigo = p_sessao;
  if s.id is null then return jsonb_build_object('ok', false, 'erro', 'Link inválido.'); end if;
  select * into v from av.versoes where id = s.versao_id;
  select * into t from av.testes where id = v.teste_id;
  select a.nome into nome from av.avaliadores a where a.id = s.avaliador_id;

  select coalesce(jsonb_agg(jsonb_strip_nulls(jsonb_build_object(
      'pos', (e->>'pos')::int,
      'tipo', i.tipo,
      'pergunta', coalesce(i.publico->>'pergunta', v.publico->>'pergunta'),
      'texto', i.publico->>'texto',
      'paineis', av.resolver_lista(i.publico->'paineis'),
      'escala', coalesce(i.publico->'escala', v.publico->'escala'),
      'opcoes', (select jsonb_agg(av.resolver_midia(o.publico) order by x.n)
                 from jsonb_array_elements_text(e->'opcoes') with ordinality as x(opid, n)
                 join av.opcoes o on o.id = x.opid::uuid),
      'resposta', (select jsonb_strip_nulls(jsonb_build_object('exibida', r.exibida, 'nota', r.nota, 'comentario', r.comentario))
                   from av.respostas r where r.sessao_id = s.id and r.pos = (e->>'pos')::int)
    )) order by (e->>'pos')::int), '[]'::jsonb)
  into itens
  from jsonb_array_elements(s.plano) e join av.itens i on i.id = (e->>'item')::uuid;

  return jsonb_build_object(
    'ok', true,
    'aberto', t.aberto,
    'nome', nome,
    'confirmada', s.confirmada_em is not null,
    'terminada', s.terminada_em is not null,
    'versao', v.versao,
    'teste', (v.publico - 'exemplo') || jsonb_build_object('exemplo',
       case when v.publico ? 'exemplo' then (v.publico->'exemplo') || jsonb_build_object('paineis', av.resolver_lista(v.publico->'exemplo'->'paineis'))
       end),
    'itens', itens);
end $$;

create or replace function public.av_responder(p_sessao text, p_pos int, p_escolha text default null, p_nota int default null,
                                               p_comentario text default null, p_ms int default null) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  s av.sessoes; v av.versoes; e jsonb; i av.itens; v_canon text; v_idx int; v_oid uuid; v_validos text[]; n_resp int;
  v_coment text := nullif(btrim(coalesce(p_comentario, '')), '');
begin
  select * into s from av.sessoes where codigo = p_sessao;
  if s.id is null then return jsonb_build_object('ok', false, 'erro', 'Link inválido.'); end if;
  if s.confirmada_em is null then return jsonb_build_object('ok', false, 'erro', 'Confirme o nome antes de responder.'); end if;
  if not exists (select 1 from av.versoes vv join av.testes t on t.id = vv.teste_id where vv.id = s.versao_id and t.aberto) then
    return jsonb_build_object('ok', false, 'erro', 'Teste encerrado.');
  end if;
  select * into v from av.versoes where id = s.versao_id;
  select el into e from jsonb_array_elements(s.plano) as t(el) where (el->>'pos')::int = p_pos;
  if e is null then return jsonb_build_object('ok', false, 'erro', 'Posição inválida.'); end if;
  select * into i from av.itens where id = (e->>'item')::uuid;
  if length(coalesce(v_coment, '')) > 2000 then v_coment := left(v_coment, 2000); end if;

  if i.tipo = 'nota' then
    if p_nota is null or p_nota < 1 or p_nota > 5 then
      if p_escolha = 'nao_sei' then v_canon := 'nao_sei';
      else return jsonb_build_object('ok', false, 'erro', 'Nota inválida.'); end if;
    end if;
  elsif i.tipo = 'par' then
    select coalesce(array_agg(b->>'valor'), array['sim', 'nao', 'nao_sei'])
      into v_validos from jsonb_array_elements(coalesce(i.publico->'botoes', v.publico->'botoes', '[]'::jsonb)) b;
    if not (p_escolha = any(v_validos)) then return jsonb_build_object('ok', false, 'erro', 'Escolha inválida.'); end if;
    v_canon := p_escolha;
  else
    if p_escolha ~ '^[0-9]{1,2}$' then
      v_idx := p_escolha::int;
      v_oid := (e->'opcoes'->>(v_idx - 1))::uuid;
      if v_oid is null then return jsonb_build_object('ok', false, 'erro', 'Opção inválida.'); end if;
      select chave into v_canon from av.opcoes where id = v_oid;
    elsif (i.tipo = 'ab' and p_escolha in ('ambas_boas', 'ambas_ruins', 'nao_sei'))
       or (i.tipo = 'escolha' and p_escolha in ('nenhum', 'nao_sei')) then
      v_canon := p_escolha;
    else
      return jsonb_build_object('ok', false, 'erro', 'Escolha inválida.');
    end if;
  end if;

  insert into av.respostas (sessao_id, pos, item_id, rep, escolha, exibida, nota, comentario, ms, primeira_escolha, primeira_nota)
  values (s.id, p_pos, i.id, coalesce((e->>'rep')::boolean, false), v_canon, p_escolha,
          case when i.tipo = 'nota' then p_nota end, v_coment, p_ms, v_canon, case when i.tipo = 'nota' then p_nota end)
  on conflict (sessao_id, pos) do update set
    escolha = excluded.escolha, exibida = excluded.exibida, nota = excluded.nota, comentario = excluded.comentario,
    ms = coalesce(av.respostas.ms, 0) + coalesce(excluded.ms, 0), respondido_em = now(),
    alteracoes = av.respostas.alteracoes + case when av.respostas.escolha is distinct from excluded.escolha
                                                 or av.respostas.nota is distinct from excluded.nota then 1 else 0 end;

  select count(*) into n_resp from av.respostas where sessao_id = s.id;
  return jsonb_build_object('ok', true, 'respondidas', n_resp, 'total', jsonb_array_length(s.plano));
end $$;

create or replace function public.av_finalizar(p_sessao text) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare s av.sessoes; n int;
begin
  select * into s from av.sessoes where codigo = p_sessao;
  if s.id is null then return jsonb_build_object('ok', false, 'erro', 'Link inválido.'); end if;
  select count(*) into n from av.respostas where sessao_id = s.id;
  if n >= jsonb_array_length(s.plano) then
    update av.sessoes set terminada_em = coalesce(terminada_em, now()) where id = s.id;
  end if;
  return jsonb_build_object('ok', true, 'respondidas', n, 'total', jsonb_array_length(s.plano));
end $$;

-- Ponto único de admin no modo direto (scripts fora do MCP). Exige token registrado por av.registrar_token.
create or replace function public.av_admin(p_token text, p_acao text, p_dados jsonb default '{}'::jsonb) returns jsonb
language plpgsql security definer set search_path = '' as $$
begin
  if not av.token_valido(p_token) then raise exception 'token de admin inválido ou vencido' using errcode = '28000'; end if;
  case p_acao
    when 'validar' then return jsonb_build_object('ok', true);
    when 'bilhetes' then return av.criar_bilhetes(coalesce((p_dados->>'n')::int, 1));
    when 'midias_por_origem' then return av.midias_por_origem(array(select jsonb_array_elements_text(p_dados->'chaves')));
    when 'registrar_midia' then return to_jsonb(av.registrar_midia(p_dados));
    when 'criar_teste' then return av.criar_teste(p_dados);
    when 'criar_sessoes' then return av.criar_sessoes(p_dados->>'teste', array(select jsonb_array_elements_text(p_dados->'nomes')), (p_dados->>'versao')::int);
    when 'exportar' then return av.exportar(p_dados->>'teste', (p_dados->>'versao')::int);
    when 'encerrar' then update av.testes set aberto = false where slug = p_dados->>'teste'; return jsonb_build_object('ok', true);
    when 'reabrir' then update av.testes set aberto = true where slug = p_dados->>'teste'; return jsonb_build_object('ok', true);
    else raise exception 'ação desconhecida: %', p_acao;
  end case;
end $$;

-- ---------------------------------------------------------------- permissões

revoke execute on all functions in schema av from public, anon, authenticated;
grant execute on function av.bilhete_valido(text) to anon, authenticated;

revoke execute on function public.av_iniciar(text, text) from public;
revoke execute on function public.av_confirmar(text, text) from public;
revoke execute on function public.av_carregar(text) from public;
revoke execute on function public.av_responder(text, int, text, int, text, int) from public;
revoke execute on function public.av_finalizar(text) from public;
revoke execute on function public.av_admin(text, text, jsonb) from public;
grant execute on function public.av_iniciar(text, text) to anon, authenticated;
grant execute on function public.av_confirmar(text, text) to anon, authenticated;
grant execute on function public.av_carregar(text) to anon, authenticated;
grant execute on function public.av_responder(text, int, text, int, text, int) to anon, authenticated;
grant execute on function public.av_finalizar(text) to anon, authenticated;
grant execute on function public.av_admin(text, text, jsonb) to anon, authenticated;

alter default privileges in schema av revoke execute on functions from public;

-- ---------------------------------------------------------------- Storage

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('av-midia', 'av-midia', true, 3145728, array['image/jpeg', 'image/png', 'image/webp'])
on conflict (id) do update set public = true, file_size_limit = excluded.file_size_limit, allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "av-midia: upload com bilhete" on storage.objects;
create policy "av-midia: upload com bilhete" on storage.objects
  for insert to anon, authenticated
  with check (bucket_id = 'av-midia' and av.bilhete_valido(name));
