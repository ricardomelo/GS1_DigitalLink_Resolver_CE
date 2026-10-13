# ADR 0002 — Tenants: organizações donas de prefixos de empresa GS1

| | |
|---|---|
| Situação | **Aceito** (13 de outubro de 2026). A implementar em três etapas: 1 (este registro), 2 (modelo de dados, verificações no servidor e auditoria), 3 (telas) |
| Item do backlog | 2.4 — tenants |
| Decidido por | o responsável pelo branch, que pediu a opção recomendada em cada ponto da seção 4 |
| Inglês | [ADR 0002 in English](../../adr/0002-tenants.md) (versão de referência) |

## 1. Contexto

O portal conhece **usuários**, cada um com um **papel** (leitor < editor < administrador) e uma lista opcional
de **prefixos de empresa GS1** (`portal/users.py`). Um usuário com prefixos vê e altera só os registros cuja
chave pertence a um deles (`gs1.within_prefixes()`, chamada por `allowed()` / `check_access()` em
`portal/app.py`); um usuário sem prefixos vê todos os registros. Todo administrador gerencia todos os usuários e
lê a trilha de auditoria inteira.

Isso basta para uma organização que roda o próprio resolver. Não basta para uma instalação que atende várias
organizações (uma Organização-Membro da GS1 atendendo seus associados, um prestador de serviço atendendo marcas):

- o administrador de uma organização poderia criar usuários para outra, ou dar a um usuário todos os prefixos;
- a trilha de auditoria, o histórico dos registros e as colunas de "última alteração" mostram os usuários de
  todas as organizações;
- nada diz a que organização pertence um prefixo, então duas organizações poderiam receber o mesmo prefixo;
- o resultado da última "verificação de todos os registros" é um valor só para a instalação inteira, com o nome
  do usuário que a executou.

Os registros ficam no banco do resolver oficial (`resolver_ce`), gravados pela API de entrada de dados com um
único token mestre. O código oficial não conhece organizações e deve ficar como está.

Os itens 3.1 (e-mail), 3.2 (API do tenant e chaves), 4.2 (indicadores por tenant), 5.1 (o domínio próprio do
tenant) e 7.1 (login único por tenant) precisam todos da noção de tenant.

## 2. Decisão

1. **Um tenant é uma organização dona de prefixos de empresa GS1.** A interface chama de *organização* (en-GB
   *organisation*); o código e estes documentos dizem *tenant*. Os tenants são documentos de uma nova coleção
   `tenants` no banco do portal (ADR 0001). **Um prefixo pertence a no máximo um tenant**, e prefixos de tenants
   diferentes não podem se sobrepor (`789835741` e `7898357410` não podem ser de dois tenants).
2. **Um registro pertence ao tenant cujo prefixo inicia sua chave** (depois do dígito indicador, de extensão
   ou de preenchimento, como hoje). A posse é **derivada, nunca gravada** no banco oficial: dar um prefixo a um
   tenant leva junto os seus registros, e os dados oficiais ficam como estão.
3. **O operador é dono de tudo o que nenhum tenant tem.** Usuários sem tenant — todos os usuários de uma
   instalação hoje — são **os usuários do operador**: mantêm os direitos de hoje sobre os registros que nenhum
   tenant tem, e nada além. **Os administradores do operador são os administradores do servidor.** Uma
   instalação que nunca cria um tenant funciona exatamente como antes; atualizar uma instalação não muda nada até
   o primeiro tenant ser criado. Nenhum usuário, registro ou evento do diário é migrado.
4. **Cada usuário pertence a um tenant ou ao operador**, definido na criação do usuário. Dentro de um tenant os
   papéis são os de hoje: leitor, editor e **administrador do tenant** (`admin`). Os prefixos de um usuário do
   tenant, quando informados, ficam dentro dos do tenant.
5. **O administrador do servidor** (um `admin` do operador) cria, renomeia, desativa e remove tenants, atribui
   seus prefixos e gerencia os usuários de todos os tenants (para criar o primeiro administrador de um tenant,
   ou ajudar um que ficou sem acesso). **Ele não vê os registros, o histórico nem a trilha de auditoria de um
   tenant**, exceto pelo **acesso de suporte**: só leitura, aberto para um tenant por vez com um motivo, fechado
   quando ele sai ou encerra a sessão, e **registrado na trilha de auditoria desse tenant** com o motivo.
6. **Toda chamada confere o tenant no servidor.** O escopo de uma requisição é o tenant do usuário, o tenant de
   um acesso de suporte aberto, ou o operador; `allowed()` admite um identificador só quando o dono dele é esse
   escopo (e, dentro dele, quando está nos prefixos do próprio usuário). As importações conferem de novo quando
   o worker grava cada registro, porque um prefixo pode ter mudado de dono desde a prévia.
7. **Uma trilha de auditoria por tenant.** Todo evento do diário leva o tenant a que se refere (`tenant`,
   nenhum para o operador). Eventos de registro pertencem ao dono do registro naquele momento; entradas, ao
   tenant do usuário; administração de usuários, ao tenant do usuário afetado. Quando o administrador do servidor
   age sobre um tenant (seus usuários, seus prefixos, um acesso de suporte), o evento pertence ao tenant **e** é
   marcado como feito pelo operador (`byOperator`), de modo que as duas trilhas o mostram. O administrador de um
   tenant vê só a trilha do seu tenant; o administrador do servidor vê a trilha do operador e todas as ações dos
   usuários do operador, e a trilha inteira de um tenant só durante o acesso de suporte.
8. **Um endereço de e-mail por usuário**, opcional por enquanto, com o formato conferido, único na instalação
   (sem distinguir maiúsculas), definido pelos administradores. Não é usado antes do item 3.1 (e-mail), nunca vai
   para o diário e é apagado com o usuário.
9. **Privacidade desde a concepção.** Minimização de dados: o nome e os prefixos de uma organização; o nome, o
   papel, os prefixos e o e-mail de um usuário; nada mais. Os usuários de um tenant nunca veem os nomes de
   usuários do operador ou de outros tenants (histórico, colunas de "última alteração", o resultado da última
   verificação completa de links). O acesso do administrador do servidor aos dados de um tenant fica visível para
   o tenant.

## 3. Projeto

### 3.1 A coleção `tenants`

```
{"_id": "t-3f9a1c0b2e7d", "name": "Acme Alimentos", "prefixes": ["7891234", "7895678"],
 "disabled": false, "created": "2026-10-13T21:00:00Z", "createdBy": "admin"}
```

- `_id`: `t-` e 12 dígitos hexadecimais aleatórios; nunca muda (o nome pode mudar).
- `name`: 2 a 80 caracteres imprimíveis, único sem distinguir maiúsculas nem espaços nas pontas.
- `prefixes`: 4 a 12 dígitos ASCII cada (como hoje para os usuários), ordenados, sem repetição; **nenhum pode ser
  prefixo de um prefixo de outro tenant** (nem igual a ele), e nenhum pode ser prefixo de outro do mesmo tenant
  (redundante).
- `disabled`: os usuários do tenant não conseguem entrar e as sessões abertas terminam; os registros continuam
  resolvendo (o resolver não conhece tenants) e continuam fora do alcance do operador.

As gravações correm sob a trava dos usuários (`store.lock("users")`), porque as regras cruzam as duas coleções:

| Mudança | Recusada quando |
|---|---|
| um prefixo dado a um tenant | sobrepõe um prefixo de outro tenant; um **usuário do operador** está limitado a um prefixo dentro dele (perderia todos os registros que alcança) |
| um prefixo tirado de um tenant | um **usuário desse tenant** está limitado a um prefixo dentro dele |
| um tenant removido | ainda tem usuários; seus prefixos voltam para o operador |

### 3.2 Usuários

Os documentos de `users` ganham dois campos: `tenant` (o `_id` de um tenant, ou ausente para o operador) e
`email` (opcional). Os papéis continuam `reader`, `editor`, `admin`.

- **Quem gerencia quem.** O administrador de um tenant lista, cria, altera, redefine a senha e remove os usuários
  do seu tenant, só com papéis do tenant. O administrador do servidor gerencia todos os usuários; ao criar um,
  escolhe o tenant (ou o operador).
- **Último administrador.** Deve restar pelo menos um administrador **do operador** ativo (como hoje para
  qualquer administrador). Um tenant pode ficar sem administrador: o administrador do servidor pode criar um.
- **Prefixos de um usuário do tenant** ficam dentro dos do tenant (cada um começa com um deles); vazio significa
  o tenant inteiro. Um tenant sem prefixos não alcança nenhum registro.
- **Entrada.** Um usuário de um tenant desativado ou removido não consegue entrar (`auth.tenantDisabled`); uma
  sessão aberta termina na próxima requisição.
- `create_user.py` ganha `--tenant` (nome ou id) e `--email`; sem `--tenant` o usuário é do operador, como hoje.

### 3.3 O escopo de uma requisição

`require_login` define, a partir da conta (lida a cada requisição, como hoje):

| | `g.tenant` (escopo) | `g.role` | `g.prefixes` |
|---|---|---|---|
| usuário de tenant | o tenant dele | o papel dele | os prefixos dele (vazio: os do tenant) |
| usuário do operador | nenhum | o papel dele | os prefixos dele (vazio: tudo o que o operador tem) |
| administrador do servidor em acesso de suporte | o tenant | `reader` | nenhum (o tenant inteiro) |

`allowed(anchor)`: o dono da âncora (o tenant cujo prefixo inicia a parte da empresa, ou nenhum) é igual a
`g.tenant`, e a âncora está em `g.prefixes` quando houver. Todo lugar que chega aos registros já passa por
`allowed()` ou `check_access()`: o registro e seu histórico, a lista de registros, exportações, importações
(prévia e, agora, cada gravação do worker), verificações de links, QR codes e prévias de Digital Link.

Os tenants são lidos uma vez por requisição (coleção pequena). A posse é o prefixo mais longo que casa — que, com
as sobreposições recusadas, é o único.

### 3.4 Acesso de suporte

`POST /portal/api/support {"tenant", "reason"}` (administradores do servidor; motivo de 5 a 200 caracteres) guarda o
tenant na sessão e registra `support-open` com o motivo na trilha do tenant; `DELETE /portal/api/support` fecha
(`support-close`); sair da sessão também fecha. Enquanto está aberto a página mostra uma faixa com o nome do tenant
e um botão para sair, o administrador do servidor age como leitor daquele tenant (lista, registros, histórico,
exportação, QR codes, a trilha de auditoria do tenant) e não pode alterar registros. Abrir o acesso de suporte a
outro tenant fecha o primeiro.

### 3.5 Diário

Os eventos ganham `tenant` (ausente para o operador) e `byOperator` (verdadeiro quando um usuário do operador agiu
sobre um tenant). Um novo índice `(tenant, at)` atende os filtros. Os eventos gravados antes desta mudança não têm
tenant: eram do operador, e é isso que passam a ser. `journal.for_record()` (o painel Histórico) devolve só as
versões feitas enquanto o registro pertencia ao escopo da requisição, então um registro que passa a um tenant
mantém as versões anteriores na trilha do operador.

Ações novas: `tenant-create`, `tenant-update`, `tenant-remove` (trilha do operador e do tenant), `support-open`,
`support-close` (trilha do tenant, `byOperator`), `login-refused` (um usuário de tenant desativado). Todas na
categoria de retenção administrativa, exceto `login-refused`, que entra na categoria de sessão.

### 3.6 Metadados dos registros e verificações de links

`record_meta` guarda o tenant que fez a alteração; a lista de registros mostra "criado/alterado por" só quando ele
coincide com o escopo da requisição. O resultado da última "verificação de todos os registros" é guardado por
escopo (configuração `lastFullCheck:<tenant>` ou `lastFullCheck` para o operador).

### 3.7 Telas

- **Organizações** (`#tenants`, administradores do servidor): um formulário para criar (nome, prefixos), uma tabela
  com nome, prefixos, usuários, registros, situação e ações (salvar, desativar/ativar, acesso de suporte, remover)
  e o número de registros que não pertencem a nenhuma organização.
- **Usuários**: uma coluna e um filtro *Organização* e, ao criar um usuário, um seletor de organização (só o
  administrador do servidor); uma coluna *E-mail* para os dois administradores.
- **Cabeçalho**: o nome da organização sob o nome do usuário no menu da conta; uma faixa durante o acesso de suporte.
- **Trilha de auditoria**: igual para administradores de tenant (só a trilha deles); a do administrador do servidor
  mostra uma coluna *Organização*.

Os mock-ups dessas telas são entregues com a etapa 3, antes de ela chegar à homologação.

### 3.8 API acrescentada ou alterada

| Método e caminho | Quem | O quê |
|---|---|---|
| `GET /portal/api/tenants` | administrador do servidor | tenants com contagens de usuários e registros; registros que não pertencem a nenhum |
| `POST /portal/api/tenants` | administrador do servidor | criar (`name`, `prefixes`) |
| `PUT /portal/api/tenants/<id>` | administrador do servidor | renomear, mudar prefixos, desativar ou ativar |
| `DELETE /portal/api/tenants/<id>` | administrador do servidor | remover um tenant sem usuários |
| `POST`, `DELETE /portal/api/support` | administrador do servidor | abrir e fechar o acesso de suporte |
| `GET /portal/api/users` e as chamadas de usuários | os dois administradores | com o escopo de 3.2; campos `tenant` e `email` |
| `GET /portal/api/config` | todos | acrescenta `tenant` (`{id, name}` ou nenhum), `serverAdmin`, `support` |

## 4. Opções consideradas

| Ponto | Escolhida (recomendada) | Não escolhidas |
|---|---|---|
| Modelo de tenant | coleção `tenants`; um tenant por usuário | usuários em vários tenants (um seletor de tenant em toda tela; mais difícil de raciocinar) |
| Administrador do servidor | o `admin` do operador; nenhum papel novo | um papel novo acima de `admin`, ou uma marca em qualquer conta (um membro de um tenant que também vê todos os tenants) |
| Administrador do servidor e os dados do tenant | acesso de suporte, só leitura, com motivo, na trilha do tenant | acesso total (sem privacidade); nenhum acesso (sem como ajudar um tenant) |
| Sobreposição de prefixos | recusada | permitida, vence o mais longo (um tenant poderia tomar parte da faixa de outro sem ninguém notar) |
| Instalações existentes | nada migrado: os usuários de hoje passam a ser do operador | um tenant com o nome do operador e os prefixos em uso (registros de usuários sem prefixos ficariam sem tenant; não dá para adivinhar o tamanho do prefixo a partir dos registros sem a tabela de tamanhos de GCP); um tenant por conjunto distinto de prefixos |
| Posse dos registros | derivada do prefixo | um campo `tenant` mantido pelo portal (registros feitos por outras ferramentas não teriam) |
| Auditoria por tenant | um campo `tenant` nos eventos, `byOperator` para as ações do operador | diários separados por tenant (retenção e backups multiplicados) |
| E-mail | opcional, único, definido pelos administradores | obrigatório já (bloquearia os usuários de hoje); preenchido pelo próprio usuário (precisa do item 3.1 para confirmar) |
| Entregas | três etapas: registro, servidor, telas | uma etapa; cinco etapas (dados, API, auditoria, privacidade, telas) |

## 5. Consequências

- Uma instalação que não cria tenants se comporta exatamente como antes.
- **Criar um tenant tira os seus registros dos usuários do operador**, inclusive dos administradores do servidor:
  eles só voltam a alcançá-los pelo acesso de suporte. É o objetivo da mudança; as telas avisam antes de o prefixo
  ser salvo.
- O administrador do servidor não pode alterar os registros de um tenant. Um tenant que precise de ajuda com os
  registros dá os direitos a um dos seus usuários, ou o administrador do servidor cria um usuário no tenant
  (registrado na trilha dele).
- A API de entrada de dados continua com um único token mestre: quem o tem passa por cima dos tenants. As chaves de
  API por tenant vêm com o item 3.2.
- O resolver responde por todos os registros, de todos os tenants: tenants são assunto de administração, não de
  resolução (o item 5.1 traz o domínio próprio do tenant).

## 6. Configuração acrescentada

Nenhuma. Os tenants são dados, gerenciados no portal.

## 7. Entregas

1. Este registro (nos dois idiomas).
2. Modelo de dados, verificações no servidor e auditoria: `portal/tenants.py`, mudanças em `users.py`, `journal.py`,
   `meta.py`, `app.py` e `create_user.py`; um novo programa de testes de desenvolvimento, `test_tenants.py`.
3. Telas (mock-ups antes), os testes de ponta a ponta, os guias do usuário e do desenvolvedor.
