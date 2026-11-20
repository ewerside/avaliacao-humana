-- Página inicial: lista de testes, quem concluiu e, com um nome, o que falta para a pessoa. 20/11/2026.
--
-- Pedido do Ewerton (20/11/2026): página inicial com todos os testes e quem já concluiu; quem digita o nome
-- vê os testes pendentes para si. Decisão dele: o nome completo de quem concluiu aparece para todos.
-- Isso abre uma exceção à regra "nome só em av.avaliadores": a página inicial mostra o nome de quem terminou.
-- Continua valendo: exportação e análises usam o código do avaliador; nenhum campo oculto sai daqui.

alter table av.testes add column if not exists na_inicial boolean not null default true;
comment on column av.testes.na_inicial is 'Aparece na página inicial (falso para testes de exemplo e de verificação).';

-- Nome comparável: sem espaços nas pontas, minúsculo, sem acento, espaços repetidos viram um.
create or replace function av.nome_norm(p text) returns text
language sql immutable set search_path = '' as $$
  select regexp_replace(
           translate(lower(btrim(coalesce(p, ''))),
                     'áàâãäéèêëíìîïóòôõöúùûüçñ', 'aaaaaeeeeiiiiooooouuuucn'),
           '\s+', ' ', 'g')
$$;

create or replace function public.av_inicio(p_nome text default null) returns jsonb
language plpgsql stable security definer set search_path = '' as $$
declare n text := nullif(av.nome_norm(p_nome), '');
begin
  return jsonb_build_object('ok', true, 'testes', coalesce((
    select jsonb_agg(x.j order by x.aberto desc, x.criado_em desc)
    from (
      select t.aberto, t.criado_em, jsonb_strip_nulls(jsonb_build_object(
        'teste', t.slug,
        'projeto', t.projeto,
        'titulo', v.publico->>'titulo',
        'aberto', t.aberto,
        'criado_em', t.criado_em,
        'telas', (select count(*) + count(*) filter (where i.repetir) from av.itens i where i.versao_id = v.id),
        'tempo_min', (v.publico->>'tempo_min')::int,
        'concluiram', (
          select coalesce(jsonb_agg(jsonb_build_object('nome', c.nome, 'em', c.em) order by c.em), '[]'::jsonb)
          from (select distinct on (av.nome_norm(a.nome)) a.nome, s.terminada_em as em
                from av.sessoes s
                join av.versoes vv on vv.id = s.versao_id and vv.teste_id = t.id
                join av.avaliadores a on a.id = s.avaliador_id
                where s.terminada_em is not null and av.nome_norm(a.nome) not like 'verificacao%'
                order by av.nome_norm(a.nome), s.terminada_em) c),
        'em_andamento', (
          select count(distinct av.nome_norm(a.nome))
          from av.sessoes s
          join av.versoes vv on vv.id = s.versao_id and vv.teste_id = t.id
          join av.avaliadores a on a.id = s.avaliador_id
          where s.terminada_em is null and av.nome_norm(a.nome) not like 'verificacao%'
            and exists (select 1 from av.respostas r where r.sessao_id = s.id)
            and not exists (select 1 from av.sessoes s2 join av.versoes v2 on v2.id = s2.versao_id
                            join av.avaliadores a2 on a2.id = s2.avaliador_id
                            where v2.teste_id = t.id and s2.terminada_em is not null
                              and av.nome_norm(a2.nome) = av.nome_norm(a.nome))),
        'meu', case when n is null then null else (
          select case
            when bool_or(s.terminada_em is not null) then jsonb_build_object('situacao', 'concluido')
            when count(*) filter (where s.versao_id = v.id) > 0 then jsonb_build_object('situacao', 'em_andamento',
              'sessao', (select s3.codigo from av.sessoes s3 join av.avaliadores a3 on a3.id = s3.avaliador_id
                         where s3.versao_id = v.id and av.nome_norm(a3.nome) = n and s3.terminada_em is null
                         order by (select count(*) from av.respostas r where r.sessao_id = s3.id) desc, s3.criada_em desc
                         limit 1))
            else jsonb_build_object('situacao', 'pendente') end
          from av.sessoes s
          join av.versoes vv on vv.id = s.versao_id and vv.teste_id = t.id
          join av.avaliadores a on a.id = s.avaliador_id
          where av.nome_norm(a.nome) = n) end
      )) as j
      from av.testes t
      join lateral (select * from av.versoes v where v.teste_id = t.id and v.ativa order by v.versao desc limit 1) v on true
      where t.na_inicial
    ) x), '[]'::jsonb));
end $$;

revoke execute on function av.nome_norm(text) from public, anon, authenticated;
revoke execute on function public.av_inicio(text) from public;
grant execute on function public.av_inicio(text) to anon, authenticated;
