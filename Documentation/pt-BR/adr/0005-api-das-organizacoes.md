# ADR 0005 — A API das organizações e as chaves de API

| | |
|---|---|
| Situação | **Aceita** (14 de outubro de 2026). A implementar em três etapas: 1 (este registro), 2 (chaves, a API e a sua descrição no servidor), 3 (a tela de chaves de API) |
| Item do backlog | 3.2 — API das organizações e chaves de API |
| Decidido por | o dono do branch, que pediu a opção recomendada em todos os pontos da seção 4 |
| Inglês | [ADR 0005 in English](../../adr/0005-tenant-api.md) (versão de referência) |

## 1. Contexto

Os cadastros são gravados por pessoas no portal, ou por importações de planilhas. Uma organização que mantém os
seus produtos num sistema próprio (um ERP, um PIM, uma plataforma de comércio eletrônico) precisa exportar uma
planilha e importá-la à mão sempre que algo muda. A única interface programável é a API de cadastro oficial, que
tem **um token mestre** para a instalação inteira: quem o tem alcança todos os cadastros de todas as organizações,
passando por cima de perfis, prefixos de empresa GS1 e organizações (ADR 0002, seção 5). Ele não pode ser entregue
a uma organização.

O que o sistema de uma organização precisa é de uma API pequena e estável que faça o que um usuário do portal faz —
ler, gravar e excluir cadastros, gerar etiquetas —, limitada exatamente como um usuário do portal é limitado, com
credenciais que a própria organização possa criar, ver em uso e revogar.

Restrições:

- O portal já tem todas as regras (ADR 0002 `set_scope()` / `allowed()`; ADR 0003 as regras GS1; a sequência segura
  de chamadas do `store_record()`); uma segunda implementação se afastaria delas.
- O portal roda em várias réplicas: um limite de requisições precisa ser compartilhado por todas (ADR 0001).
- Chaves são credenciais; o portal já guarda links de uso único só como hash (ADR 0004).
- Os itens 4.2 (indicadores) e 5.1 (domínios próprios) vão acrescentar operações; a API precisa crescer sem quebrar
  os clientes.

## 2. Decisão

1. **Uma API versionada do portal em `/portal/api/v1/`**, servida pelo próprio portal (nenhum serviço novo, nenhuma
   mudança no proxy), JSON na entrada e na saída, os mesmos códigos de mensagem da API do próprio portal. Uma
   mudança incompatível futura ganha `/v2/`; acréscimos (operações novas, campos novos) ficam na `v1`.
2. **Operações da v1**: quem sou eu (`GET /portal/api/v1`), listar cadastros (paginado), ler um cadastro, criar ou
   substituir um cadastro (`PUT`, idempotente), excluir um cadastro, gerar uma etiqueta (SVG ou PNG); e a descrição
   da API, **`GET /portal/api/v1/openapi.json`** (OpenAPI 3.1), pública. Os cadastros são endereçados como o portal
   os endereça: `/records/{key}/{value}` mais `?qualifiers=/10/L1`.
3. **As chaves de API pertencem a uma organização** (ou ao operador), não a uma pessoa. **Os administradores as
   criam**: um administrador de organização para a sua organização, um administrador do servidor para os cadastros
   do operador (nunca para uma organização: isso passaria por cima da regra de acesso de suporte da ADR 0002). Uma
   chave tem nome, **escopos** (`records:read`, `records:write`, `labels:read`), opcionalmente prefixos de empresa
   GS1 dentro dos da organização, uma **validade** (obrigatória, de 1 a 365 dias, 90 por padrão), e registra quem a
   criou, quando foi usada pela última vez e quem a revogou. No máximo 20 chaves ativas por organização.
4. **A chave aparece uma vez**: `rk_<id>.<segredo>` — 12 dígitos hexadecimais que a identificam (mostrados nas
   listas e na auditoria) e um segredo aleatório de 256 bits. **Só o SHA-256 do segredo é guardado** (como os links
   da ADR 0004); a comparação é em tempo constante. Uma chave perdida é revogada e substituída, nunca recuperada.
5. **Uma chave funciona como um usuário da sua organização funcionaria**: cada chamada recebe o escopo de uma
   requisição (`set_scope()`): a organização da chave, o perfil que os seus escopos implicam (`records:write` →
   editor, senão leitor), os seus prefixos. O `allowed()` e todas as regras do portal valem sem mudança. Uma chave de
   uma organização desativada ou excluída, uma chave expirada ou revogada, é recusada (401).
6. **Um limite de requisições por chave**, compartilhado por todas as réplicas: um contador por chave e minuto no
   banco do portal (TTL), **120 requisições por minuto** por padrão (`PORTAL_API_RATE_PER_MINUTE`); acima disso, 429
   com `Retry-After`.
7. **Auditoria**: criar e revogar uma chave são eventos do diário da organização (`api-key-create`,
   `api-key-revoke`); toda mudança feita por uma chave é um evento de cadastro como outro qualquer, com o usuário
   `api:<id da chave>`. As leituras não vão para o diário (o item 4.1 registra as requisições); a chave guarda o seu
   último uso (no máximo uma gravação por minuto).
8. **E-mail** (ADR 0004): o administrador que criou uma chave é avisado quando ela é criada e sete dias antes de ela
   expirar (categoria de segurança, sempre enviada); o worker confere as validades uma vez por hora.
9. **De servidor para servidor**: a API é para sistemas, não para navegadores. Ela não envia cabeçalhos CORS; uma
   requisição de navegador vinda de outro site é recusada pela conferência de Origin que o portal já faz.

## 3. Projeto

### 3.1 A coleção `api_keys` (`portal/apikeys.py`)

```
{"_id": "3f9a1c0b2e7d", "hash": "<sha256 hex do segredo>", "name": "Integração ERP",
 "tenant": "t-…" (ausente para o operador), "scopes": ["records:read", "records:write"], "prefixes": [],
 "created": <data>, "createdBy": "maria", "expiresAt": <data>, "lastUsed": <data>,
 "revoked": <data>, "revokedBy": "ana", "expiryNotice": <data>}
```

`create()` confere o nome (de 3 a 60 caracteres imprimíveis, único entre as chaves ativas da organização), os
escopos, os dias (de 1 a `PORTAL_API_KEY_MAX_DAYS`, padrão 365) e os prefixos (como `users._check_scope()`), sob a
trava `users`; devolve a chave completa uma vez. `authenticate(texto)` interpreta `rk_<id>.<segredo>`, acha o
documento pelo id e compara os hashes; `revoke()` a marca. Chaves revogadas e expiradas continuam na lista
(acinzentadas) para a auditoria; o portal nunca as apaga.

### 3.2 O limite de requisições (coleção `api_rate`)

`{"_id": "<id da chave>:<minuto>", "n": 17, "at": <data>}` — `find_one_and_update` com `$inc` e `upsert`, um TTL de
dois minutos em `at`. A primeira requisição de um minuto também grava `lastUsed`.

### 3.3 A API (`portal/api_v1.py`)

| Chamada | Escopo | Resposta |
|---|---|---|
| `GET /portal/api/v1` | qualquer | a chave (id, nome, escopos, prefixos, validade), a sua organização, o limite |
| `GET /portal/api/v1/openapi.json` | nenhum | a descrição da API |
| `GET /portal/api/v1/records?key=&limit=&after=` | `records:read` | os cadastros ao alcance da chave, ordenados, no máximo `limit` (1–1000, 100); `next` é o `after` da próxima página |
| `GET /portal/api/v1/records/{key}/{value}?qualifiers=` | `records:read` | descrição, links (o padrão primeiro), tipo do link padrão, Digital Link; 404 `record.notFound` |
| `PUT /portal/api/v1/records/{key}/{value}?qualifiers=` | `records:write` | `{description, links: [{linkType, url, title, hreflang}]}` → 201 criado / 200 substituído, com o Digital Link |
| `DELETE /portal/api/v1/records/{key}/{value}?qualifiers=` | `records:write` | 200 `delete.done`; 404 `record.notFound` |
| `GET /portal/api/v1/labels/{key}/{value}?qualifiers=&format=svg\|png&hri=&version=&ecl=&attr=` | `labels:read` | a etiqueta, como a do portal |

Erros: `{"code", "params"}` como os do portal (`api.keyMissing`, `api.keyInvalid`, `api.scope`, `api.rateLimit`,
`access.prefix`, `record.notFound`, os códigos GS1 e de validação). Os tratadores chamam as funções que os endpoints
do próprio portal usam (`build_document()`, `store_record()`, a sequência de exclusão, a etiqueta), então as regras
são as mesmas.

### 3.4 Chaves no portal

`GET /portal/api/keys`, `POST /portal/api/keys` `{name, scopes, days, prefixes}` → `{key, item}`,
`DELETE /portal/api/keys/<id>` (revogar), para administradores, sempre no escopo da própria conta (um administrador
do servidor em acesso de suporte continua gerenciando as chaves do operador). Uma tela **Chaves de API** as lista e
mostra uma chave nova uma vez, com um botão de copiar e um exemplo de requisição.

## 4. Opções consideradas

| Ponto | Escolhida (recomendada) | Não escolhida |
|---|---|---|
| Onde a API fica | o portal, `/portal/api/v1/` | um serviço novo (uma segunda cópia de todas as regras); a API de cadastro oficial com tokens por organização (muda código oficial; as regras estão no portal) |
| Versionamento | `v1` no caminho; acréscimos sem versão nova | um cabeçalho (`Accept-Version`; fácil de esquecer, mais difícil de experimentar com curl); nenhuma versão |
| A quem pertence uma chave | à organização, criada pelos seus administradores | tokens pessoais de cada usuário (a chave pararia quando a pessoa saísse) |
| Administradores do servidor | chaves só para os cadastros do operador | chaves para qualquer organização (passa por cima do acesso de suporte) |
| Formato da chave | `rk_<id>.<segredo>`, guardado o SHA-256 do segredo | um segredo guardado (uma cópia do banco vaza todas as chaves); um hash lento como bcrypt (desnecessário para um segredo aleatório de 256 bits, e caro a cada chamada); tokens assinados (não podem ser revogados um a um) |
| Validade | obrigatória, 90 dias por padrão, 365 no máximo | opcional (chaves esquecidas vivem para sempre) |
| Escopos | `records:read`, `records:write`, `labels:read` | uma chave com todos os poderes; escopos por operação (finos demais para três recursos) |
| Limite de requisições | por chave e minuto no MongoDB, 120 | na memória de cada processo (errado com réplicas); no nginx (não distingue chaves sem lê-las) |
| Auditoria | gravações como eventos de cadastro, criação e revogação de chaves como eventos de administração; último uso na chave | toda requisição no diário (o item 4.1 faz isso, com retenção) |
| Descrição | um arquivo OpenAPI 3.1 escrito à mão, conferido contra as rotas por um teste | gerado a partir do código (uma biblioteca e decoradores para seis operações) |
| Entrega | três etapas: registro, servidor, tela | uma etapa; quatro (chaves, API, descrição, tela) |

## 5. Consequências

- Uma organização pode ligar os seus próprios sistemas sem o token mestre, limitada aos seus prefixos, e pode ver e
  revogar o que criou. O token mestre continua com o operador, para o portal e as ferramentas da instalação.
- Uma chave é uma credencial: quem a tem grava os cadastros da organização dentro dos seus escopos até ela expirar
  ou ser revogada. As chaves aparecem uma vez, expiram, são limitadas por minuto e a sua criação é avisada por
  e-mail.
- A API responde com os códigos de mensagem do portal, não com frases; o documento OpenAPI os lista.
- Gravar pela API segue as mesmas regras do portal, inclusive o tipo do link padrão compartilhado de uma chave
  (`default.sharedMismatch`), então um cliente precisa tratar essas respostas.

## 6. Configuração acrescentada

| Variável | Padrão | |
|---|---|---|
| `PORTAL_API_RATE_PER_MINUTE` | 120 | requisições por chave e minuto |
| `PORTAL_API_KEY_MAX_DAYS` | 365 | a maior validade que um administrador pode escolher |

## 7. Entrega

1. Este registro (nos dois idiomas).
2. No servidor: `portal/apikeys.py`, `portal/api_v1.py`, `portal/openapi.json`; os endpoints de chaves no `app.py`;
   a conferência de validades de hora em hora no worker; mensagens no `mailtexts.py`; um novo programa de testes de
   desenvolvimento `test_api.py`.
3. A tela de chaves de API (imagens para revisão, já que o dono está ausente), o teste de ponta a ponta, os guias do
   usuário e do desenvolvedor, a referência da API no README.
