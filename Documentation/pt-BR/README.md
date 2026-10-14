# GS1 Digital Link Resolver CE — Expansion Pack (documentação em português)

[![Testes de desenvolvimento](https://github.com/ricardomelo/GS1_DigitalLink_Resolver_CE/actions/workflows/dev-tests.yml/badge.svg?branch=gs1br/develop)](https://github.com/ricardomelo/GS1_DigitalLink_Resolver_CE/actions/workflows/dev-tests.yml)

*English version: [README](../../README.md).*

> **Aviso importante (do projeto oficial).** Este software livre e de código aberto não é mantido pela
> GS1. Questões levantadas aqui podem ser respondidas pela comunidade, mas não serão tratadas pela própria
> GS1. Quem usa este software não deve supor que ele esteja totalmente conforme o padrão publicado
> [GS1-Conformant Resolver](https://ref.gs1.org/standards/resolver/).

> **Software da comunidade; o operador é o responsável.** Tanto o GS1 Resolver Community Edition oficial
> quanto este fork são mantidos pelas suas comunidades de colaboradores, não pela GS1 nem por qualquer
> Organização-Membro GS1. O software é fornecido "no estado em que se encontra", sem garantias ou condições
> de qualquer tipo (Apache License 2.0, seções 7 e 8). Quem instala e opera uma instalação é o único
> responsável por ela e pelo seu uso: a sua segurança e disponibilidade, os cadastros e links que ela
> publica e a conformidade deles com os padrões GS1.

Este repositório é um fork do
[**GS1 Resolver Community Edition v3**](https://github.com/gs1/GS1_DigitalLink_Resolver_CE) oficial (a partir
do commit [`bf885fd`](https://github.com/gs1/GS1_DigitalLink_Resolver_CE/commit/bf885fdf4888f0395229478bf6b50342c1f761a8)),
mantido no branch `gs1br/develop`. Ele conserva o Resolver e a API de cadastro oficiais e acrescenta o que
uma organização precisa para operar um Resolver para os seus associados:

- um **portal de gestão de links** que simplifica o cadastro, em português do Brasil e inglês britânico;
- todas as **chaves primárias de identificação e qualificadores** da
  [GS1 Digital Link URI Syntax 1.7](https://ref.gs1.org/standards/digital-link/uri-syntax/);
- **correções de conformidade** no Resolver ([GS1-Conformant Resolver 1.2.1](https://ref.gs1.org/standards/resolver/))
  e páginas HTML para quem abre um link no navegador;
- uma **página inicial**, um **arquivo de descrição do Resolver configurável** e **reforço de segurança**;
- um **instalador interativo para Ubuntu**, **backup diário** e **testes de desenvolvimento** para tudo.

![Página inicial do Resolver](../images/guide/pt-BR/home.png)

---

## Documentação em português

| Documento | Para quem | Conteúdo |
|---|---|---|
| [Guia do portal](guia-do-portal.md) | quem cadastra; administradores | todas as tarefas do portal, passo a passo, com imagens |
| [Funcionalidades](funcionalidades.md) | todos | cada funcionalidade, o que faz e quando foi incluída |
| [Histórico](historico.md) | mantenedores, revisores | como o projeto evoluiu sessão a sessão, decisões, lições, pendências |
| [Guia do desenvolvedor](guia-do-desenvolvedor.md) | desenvolvedores | serviços, arquivos-fonte, fluxos, API do portal, arquivos de dados, testes, como estender |
| [Revisão de conformidade](revisao-de-conformidade.md) | mantenedores, revisores, operadores | revisão cláusula a cláusula frente à GS1 Digital Link URI Syntax 1.7 e ao GS1-Conformant Resolver 1.2.1: achados, evidências, candidatos a errata |
| [Decisões de arquitetura](adr/0001-estado-do-portal-no-mongodb.md) | mantenedores, desenvolvedores, operadores | ADR 0001: o estado do portal no MongoDB, tarefas em segundo plano num worker, mais de uma réplica |
| [Organizações (tenants)](adr/0002-organizacoes.md) | mantenedores, desenvolvedores, operadores | ADR 0002: organizações donas de prefixos de empresa GS1, o administrador do servidor, acesso de suporte, uma trilha de auditoria por tenant |
| [Regras GS1 do dicionário](adr/0003-regras-gs1-do-dicionario.md) | mantenedores, desenvolvedores | ADR 0003: uma fonte única para as regras GS1 (o GS1 Barcode Syntax Dictionary), uma versão do motor, mensagens do motor traduzidas, uma verificação semanal de atualizações |
| [E-mail](adr/0004-e-mail.md) | mantenedores, desenvolvedores, operadores | ADR 0004: e-mail de saída por um relay autenticado, convites, recuperação de senha por link de uso único, notificações com preferências por usuário |
| [API das organizações](adr/0005-api-das-organizacoes.md) | mantenedores, desenvolvedores, operadores | ADR 0005: a API versionada do portal para os sistemas das organizações, chaves de API criadas pelos administradores (escopos, prefixos, validade, só o hash), um limite de requisições por chave, descrição OpenAPI |
| [Registro de requisições](adr/0006-registro-de-requisicoes.md) | mantenedores, desenvolvedores, operadores | ADR 0006: o Resolver registra cada requisição de resolução de forma assíncrona e sem dados pessoais (nenhum endereço, nenhum User-Agent, nenhum número de série), eventos brutos com expiração, agregados diários por chave feitos pelo worker, atribuição às organizações na hora da consulta, as chamadas da API das organizações |

Em inglês ficam também a [documentação detalhada das extensões](../extensions/README.md), o
[changelog](../extensions/CHANGELOG.md) e o [README oficial](../upstream-README.md). O índice de todos os
documentos está em [Documentation/README.md](../README.md).

## Sumário

1. [O projeto original](#o-projeto-original)
2. [O que este fork acrescenta](#o-que-este-fork-acrescenta)
3. [Arquitetura](#arquitetura)
4. [O portal de gestão de links](#o-portal-de-gestão-de-links)
5. [Cobertura do GS1 Digital Link](#cobertura-do-gs1-digital-link)
6. [Referência das APIs](#referência-das-apis)
7. [Requisitos do sistema](#requisitos-do-sistema)
8. [Instalação com o script para Ubuntu](#instalação-com-o-script-para-ubuntu)
9. [Instalação manual](#instalação-manual)
10. [Configuração](#configuração)
11. [Operação](#operação)
12. [Desenvolvimento e testes](#desenvolvimento-e-testes)
13. [Backlog em aberto](#backlog-em-aberto)
14. [Licença e créditos](#licença-e-créditos)

## O projeto original

O GS1 Resolver Community Edition é uma aplicação web livre e de código aberto, desenvolvida pela GS1
Resolver Community, que resolve identificadores GS1 carregados em URIs GS1 Digital Link (normalmente em QR
Codes) para os recursos da web cadastrados para eles: páginas de produto, instruções, bulas, receitas,
dados de rastreabilidade e mais — o recurso certo para o *motivo* da leitura do código.

A versão 3 é escrita em Python e roda como uma composição Docker de quatro serviços: um **serviço de
cadastro** (API REST com token bearer), um **serviço web de resolução**, um banco de documentos **MongoDB** e
um **proxy de front-end** (nginx). Ela guarda os links no formato IETF Linkset e oferece vários links por
identificador, qualificadores de chave, negociação de conteúdo por idioma e tipo de mídia, e Digital Links
comprimidos.

O README original é mantido, sem mudanças, em [upstream-README.md](../upstream-README.md).

## O que este fork acrescenta

| Área | Acréscimo |
|---|---|
| **Portal** (`/portal/`) | Entrada com senha por usuário (com botão de mostrar/ocultar); editor para qualquer chave primária e qualificadores, com conferências GS1 enquanto se digita; destinos por tipo de link GS1, idioma e título; destino principal; etiquetas com QR Code (PNG/SVG) nas dimensões do guia *QR Codes powered by GS1*, com escolha de versão, correção de erros e texto legível, opcionalmente com atributos de dados GS1 Digital Link (validade, peso, preço…); lista de registros com busca e filtros por tipo de chave e qualificador; importação/exportação de planilhas (XLSX, CSV) com prévia; verificador de links |
| **Governança** | Perfis (administrador, editor, leitor); organizações (tenants) donas de prefixos de empresa GS1, cada uma com seus usuários e sua auditoria, e um administrador do servidor com acesso de suporte só de leitura e registrado; acesso limitado a prefixos de empresa GS1 por usuário; tela de administração de usuários com senhas temporárias ou, com um relay de e-mail, convites por e-mail; chaves de API para os sistemas das próprias organizações (API das organizações); recuperação de senha por e-mail; avisos de segurança; histórico de cada cadastro com restauração; auditoria com filtros e exportação CSV |
| **Chaves e qualificadores** | As 16 chaves primárias da URI Syntax §4.3 e todos os qualificadores da §4.4, com os formatos da §4.6, a ordem e os caminhos compostos da §4.9, montados a partir do GS1 Barcode Syntax Dictionary da versão do engine que todos os serviços usam |
| **Atributos de dados** | Todos os atributos de dados da URI Syntax §4.10 nos QR Codes, validados pelo GS1 Barcode Syntax Engine (formatos, dígitos verificadores, datas, listas de códigos e as regras de associação das General Specifications), com as mensagens no idioma do usuário; repassados pelo Resolver aos destinos |
| **Resolver** | Subida na hierarquia de qualificadores (série → lote → variante → chave), regras de 404, formas de `linkType`, `defaultLink`, linkset RFC 9264 válido no schema da GS1, JSON-LD sob pedido, o link padrão salvo quando a requisição indica uma versão de idioma, caminhos conferidos pelo GS1 Barcode Syntax Engine, valores com `%2F`, a query string repassada exatamente como enviada, EPC em binário (`/eh…`, `/ex…`) de etiquetas NFC descomprimido, páginas HTML em pt-BR / en-GB para navegadores |
| **API de cadastro** | `GET /api/summary` (todos os cadastros numa requisição); `GET /api/index` passou a exigir o token; o "Authorize" do Swagger funciona em todas as operações protegidas |
| **Configuração** | Padrões no `.env.example` + `.env` opcional para todos os serviços; arquivo de descrição (`/.well-known/gs1resolver`) montado a partir da configuração; endereços de bind para as portas publicadas |
| **Registro de acessos** | O Resolver registra cada requisição que responde — código, resultado, nível, destino, tempo, idioma, classe de dispositivo — sem o endereço de quem leu, o User-Agent, números de série ou valores de atributos de dados; contagens diárias por chave; uma tela *Acessos* conforme o alcance de cada usuário, com exportação CSV; as chamadas da API das organizações ([ADR 0006](adr/0006-registro-de-requisicoes.md)) |
| **Página inicial** (`/`) | Menu para o portal, a documentação da API, o padrão GS1 Digital Link, gs1.org e este código; independente do domínio |
| **Operação** | Instalador interativo para Ubuntu 22.04 / 24.04; backup diário do banco e da configuração do portal; o Compose reinicia o proxy quando um serviço atrás dele é recriado |
| **Qualidade** | Testes de desenvolvimento do Resolver, da API de cadastro, do portal (unitários e de ponta a ponta no navegador), da página inicial, do instalador e do verificador de links; comparação com o GS1 Syntax Engine; aprovação na própria suíte de testes de Resolver da GS1 (31 de 31), que também roda nos testes de desenvolvimento |

## Arquitetura

```mermaid
flowchart LR
    client["Leitor / navegador"] -->|HTTPS| edge["nginx do host + Certbot<br/>(TLS, porta 443)"]
    edge -->|"127.0.0.1:8080"| proxy["frontend-proxy-service<br/>nginx"]
    proxy -->|"/  e  /home/"| home["Página inicial<br/>(estática, na imagem do proxy)"]
    proxy -->|"/{AI}/{valor}…"| web["web-service ×n<br/>Resolver"]
    proxy -->|"/api"| de["data-entry-service ×n<br/>API REST + Swagger"]
    proxy -->|"/portal/"| portal["portal-service ×n<br/>portal de gestão de links"]
    portal -->|"token bearer"| de
    web --> db[("MongoDB<br/>database-service")]
    de --> db
    portal -->|"usuário próprio: usuários, histórico"| db
    init["portal-db-init<br/>(roda uma vez)"] -.->|"cria o usuário do portal"| db
    worker["portal-worker ×n<br/>importações, verificações de links"] -->|"tarefas"| db
    worker -->|"token bearer"| de
```

| Serviço | Contêineres | Papel | Publicado |
|---|---|---|---|
| `frontend-proxy-service` | `frontend-proxy-server` | Encaminha `/`, `/api`, `/portal/` e todos os Digital Links a todas as réplicas dos serviços; serve a página inicial | `${PROXY_BIND_ADDRESS}:8080` |
| `web-service` | `WEB_SERVICE_REPLICAS` (1) | Resolve GS1 Digital Links (redirecionamentos, linksets, páginas HTML) | interno |
| `data-entry-service` | `DATA_ENTRY_SERVICE_REPLICAS` (1) | API REST para criar, ler, alterar e excluir cadastros | interno (via `/api`) |
| `portal-service` | `PORTAL_SERVICE_REPLICAS` (1) | Portal de gestão de links (Flask + front-end estático) | interno (via `/portal/`) |
| `portal-db-init` | um, a cada início | Cria ou atualiza o usuário do banco do portal e termina | — |
| `portal-worker` | `PORTAL_WORKER_REPLICAS` (1) | Executa as tarefas em segundo plano do portal (importações de planilhas, verificações de links, mensagens de e-mail) a partir do banco; a imagem do portal | — |
| `mailpit` | nenhum, a menos que iniciado (perfil `mail-test`) | Um relay de teste que guarda todos os e-mails, para experimentar o e-mail do portal antes de haver um relay real; nunca em produção | `127.0.0.1:8025` |
| `database-service` | `database-server` | MongoDB | `${DATABASE_BIND_ADDRESS}:27017` |

O portal é um back-end entre o navegador e a API de cadastro: o token da API nunca chega ao navegador, e o
portal lê antes de gravar para usar as operações da API com segurança (POST acrescenta, PUT mescla, DELETE
remove links, o tipo do destino principal é compartilhado por todos os cadastros de uma chave). Os dados
do próprio portal (usuários, metadados dos cadastros, histórico e auditoria) ficam num banco próprio no
mesmo MongoDB, `resolver_portal`, acessado por um usuário que só pode usar esse banco; o banco do Resolver
nunca é tocado ([ADR 0001](adr/0001-estado-do-portal-no-mongodb.md)). As importações de planilhas e as
verificações de muitos links são tarefas nesse banco, executadas pelo `portal-worker`: continuam quando o
portal reinicia, e uma tarefa interrompida por um reinício do worker continua de onde parou. Os detalhes estão no
[guia do desenvolvedor](guia-do-desenvolvedor.md).

Nenhum dos quatro serviços do meio da tabela guarda estado próprio, então cada um pode rodar em vários
contêineres (réplicas); a quantidade fica no `.env` (um de cada, por padrão). O Compose os chama de
`<projeto>-<serviço>-<n>`, por exemplo `gs1_digitallink_resolver_ce-web-service-2`. O proxy pergunta ao DNS
do Docker os endereços de cada serviço a cada 10 segundos e reparte as requisições entre eles, então réplicas
podem ser acrescentadas ou retiradas sem reiniciá-lo. Dentro de cada contêiner dos três serviços web, o
gunicorn roda dois processos por padrão (`*_PROCESSES`). O banco e o proxy rodam uma vez só, com os nomes
oficiais.

## O portal de gestão de links

As instruções passo a passo de cada tarefa estão no [guia do portal](guia-do-portal.md).

![Bloco da etiqueta com o QR Code e as opções](../images/guide/pt-BR/label-panel.png)

**Editor** — três passos:

1. **O que o código identifica:** tipo de identificador (GTIN, SSCC, GLN, GIAI…), valor e qualificadores
   (variante, lote, série…). Dígitos verificadores, o par de caracteres do GMN, o prefixo de empresa GS1 e
   as combinações permitidas são conferidos enquanto se digita.
2. **Descrição** do item.
3. **Destinos:** uma linha por endereço da web, com o tipo de link GS1 (por exemplo `gs1:pip`, `gs1:epil`,
   `gs1:recallStatus`), o idioma (qualquer tag BCP 47) e o título. O primeiro destino é o principal
   (`gs1:defaultLink`); cada destino pode repassar ou não a query string da leitura.

A prévia mostra o Digital Link com as partes coloridas, a **etiqueta com o QR Code** (download em PNG ou
SVG, módulo de 0,495 mm, zona de silêncio de 4X) e botões para testar ou copiar o link. Opções da
etiqueta: texto legível completo (cada element string), só da chave ou nenhum; versão do QR Code
(automática, a menor que couber, ou de 1 a 40) e nível de correção de erros (L, M — o padrão —, Q, H),
mostrados embaixo do código como usados. Se a versão escolhida for pequena demais para o conteúdo, uma
explicação com a versão necessária substitui a imagem. Quando a chave tem outros cadastros (o produto,
lotes, séries, variantes…), uma lista embaixo de *Abrir cadastro* os mostra de cinco em cinco, com busca,
filtro por qualificador e um botão para abrir cada um (com confirmação se o cadastro em edição tiver
alterações não salvas). O bloco da etiqueta fica embaixo do formulário, com o código e seus botões à
esquerda e as opções à direita.

![Atributos de dados no bloco da etiqueta](../images/guide/pt-BR/attributes.png)

**Atributos de dados** — marcar *Incluir atributos de dados* embaixo do QR Code acrescenta atributos de
dados GS1 Digital Link (URI Syntax §4.10), como validade (17), peso líquido (3103) ou preço, ao QR Code:
`https://id.example.org/01/…/10/B42?17=271231&3103=000500`. Os atributos são escolhidos por número ou nome
entre os cerca de 500 AIs que o padrão permite (a chave e os qualificadores do próprio cadastro ficam de
fora), numa lista que abre com um clique e filtra enquanto se digita, com o formato explicado, ordenados
com ↑ ↓ e conferidos pelo GS1 Barcode Syntax Engine enquanto se digita. Medidas e valores cujo último
dígito do AI é o número de casas decimais aparecem como famílias — (310n) peso líquido (kg), (392n) preço —
e aceitam o número como as pessoas escrevem, com vírgula ou ponto: `123,45` vira `3102=012345`. O dia 00
nas datas ("fim do mês" na sintaxe GS1) é recusado em favor do primeiro ou do último dia do mês
explícitos. Os atributos descrevem o item no qual o código é impresso, então **não são gravados**: vão só
no código gerado naquele momento e são limpos quando outro cadastro é aberto. O Resolver os repassa aos
destinos que repassam a query string. Um atributo nunca muda a identificação: lote, série ou variante de
um GTIN são qualificadores do seu próprio cadastro, não atributos.

![Registros cadastrados](../images/guide/pt-BR/records.png)

**Lista de registros** (`/portal/#records`) — todos os cadastros do Resolver com identificador,
qualificadores, número de links e última alteração (data e usuário); busca por identificador (zeros à
esquerda opcionais), descrição ou qualificador, ignorando maiúsculas e acentos; filtros por tipo de chave
primária (GTIN, SSCC, GLN…), por qualificador (lote, série, variante… ou nenhum) e por quem alterou; colar
um GS1 Digital Link ou uma element string como `(01)…(10)…` acha o cadastro exato e os relacionados;
abrir um cadastro no editor.

**Planilhas** — exportar todos os cadastros em XLSX (com abas de referência de tipos de link, chaves e
idiomas) ou CSV; importar em duas etapas: uma prévia valida cada linha com as regras do editor e mostra o
que será novo, alterado, sem mudança ou com erro (com a linha e o motivo), e nada é gravado até você
confirmar. Cadastros que não estão no arquivo nunca são excluídos. Limites por arquivo importado (também
mostrados na janela de importação):

| Formato | Arquivos aceitos | Linhas de dados (sem o cabeçalho) | Tamanho |
|---|---|---|---|
| Excel | `.xlsx` (primeira aba) | até 5.000 | até 700 KB |
| CSV ou texto | `.csv`, `.txt` | até 5.000 | até 700 KB |

Vale o limite que for atingido primeiro. 5.000 linhas ocupam cerca de 200–300 KB em XLSX, então ali conta
o limite de linhas; em CSV cada linha ocupa cerca de 180–370 bytes, então os 700 KB costumam ser atingidos
antes, por volta de 2.000–3.900 linhas. Use XLSX ou divida o arquivo para lotes maiores. O limite de
tamanho vem do limite de 1 MB por requisição do portal (o arquivo viaja em base64); os valores ficam em
`FORMATS`, no `portal/sheet.py`. Arquivos CSV e texto podem ser separados por `;`, `,` ou tabulação e
codificados em UTF-8, UTF-16 ou Windows-1252.

![Prévia da importação](../images/guide/pt-BR/import.png)

**Verificador de links** — depois de cada salvamento, sob demanda no editor, para todos os cadastros em segundo plano (com filtro dos
cadastros com problema) e, opcionalmente, na prévia da importação. Aponta erros HTTP, endereços que não
respondem, redirecionamentos de HTTPS para HTTP e redirecionamentos sem fim; sites que recusam robôs (401,
403, 429) são indicados como tal. Só endereços públicos são contatados, então o portal não pode ser usado
para sondar a rede do próprio servidor. Sites que respondem "200" para páginas inexistentes ("soft 404")
não podem ser detectados.

**Usuários e sessões** — senha por usuário (hashes scrypt com sal), bloqueio da entrada depois de falhas
repetidas, sessões que terminam após 30 minutos sem uso (com aviso antes) e no máximo 12 horas depois da
entrada. A interface segue o idioma do navegador (pt-BR ou
en-GB) e pode ser trocada a qualquer momento.

### Governança

| Perfil | Pode |
|---|---|
| **Administrador** | tudo, inclusive administrar usuários e ver a auditoria |
| **Editor** | criar, alterar e excluir cadastros, importar planilhas, verificar links |
| **Leitor** | consultar cadastros e a lista, exportar planilhas, baixar etiquetas |

- **Prefixos de empresa GS1 por usuário** — um usuário limitado a um ou mais prefixos só vê e altera
  identificadores desses prefixos (o prefixo é procurado depois do dígito indicador de um GTIN-14, do dígito
  de extensão de um SSCC e do zero inicial de um GRAI); sem prefixos, todos os identificadores.
- **Tela de usuários** (administradores, menu do usuário → *Usuários*): criar usuários com **senha
  temporária** mostrada uma vez e trocada no primeiro acesso; mudar perfil e prefixos; redefinir senha (o
  que encerra as sessões abertas do usuário); desativar, reativar ou excluir. O último administrador ativo
  não pode ser excluído nem rebaixado, e ninguém consegue se trancar para fora.
- **Histórico** de cada cadastro (editor → *Histórico*): quem alterou, quando e como, com o conteúdo
  completo de cada versão; *Restaurar esta versão* traz uma versão anterior (ou um cadastro excluído) de
  volta ao formulário para revisão antes de salvar.
- **Auditoria** (administradores, menu do usuário → *Auditoria*): entradas, entradas recusadas, alterações
  de cadastros, importações, exportações e administração de usuários, filtradas por usuário, período e
  identificador, com exportação CSV.

Usuários, organizações, histórico e auditoria ficam no banco MongoDB próprio do portal, que o backup diário
inclui. Usuários criados antes de existirem perfis viram administradores. A ferramenta de linha de comando também
aceita perfis e organizações: `docker compose exec portal-service python create_user.py maria --role editor --prefixes 7891234`.

- **Organizações** (administradores do servidor, menu do usuário → *Organizações*): uma instalação pode atender
  várias organizações, cada uma dona dos seus prefixos de empresa GS1, com seus usuários e sua auditoria. Os
  administradores do operador são administradores do servidor; só chegam aos cadastros de uma organização pelo
  acesso de suporte, só de leitura e registrado na auditoria dela. Uma instalação sem organizações funciona como
  antes ([ADR 0002](adr/0002-organizacoes.md)).

![Administração de usuários](../images/guide/pt-BR/users.png)

## Cobertura do GS1 Digital Link

**Chaves primárias de identificação** (URI Syntax 1.7, §4.3):

| AI | Chave | AI | Chave |
|---|---|---|---|
| 01 | GTIN | 8017 / 8018 | GSRN (prestador / beneficiário) |
| 8006 | ITIP | 255 | GCN |
| 8013 | GMN | 00 | SSCC |
| 8010 | CPID | 253 | GDTI |
| 414 | GLN (local físico) | 401 | GINC |
| 415 | GLN (parte faturadora) | 402 | GSIN |
| 417 | GLN (empresa ou organização) | 8003 / 8004 | GRAI / GIAI |

**Qualificadores** (§4.4, formatos da §4.6, ordem e caminhos compostos da §4.9):

| Chave | Qualificadores, na ordem do caminho |
|---|---|
| GTIN (01) | 22 variante → 10 lote → 21 série, **ou** 235 (TPX) |
| ITIP (8006) | 10 lote → 21 série |
| CPID (8010) | 8011 série do CPID |
| GLN (414) | 254 extensão do GLN, **ou** 7040 (FID) |
| GLN (415) | 8020 referência de pagamento (**obrigatório**) |
| GLN (417), GIAI (8004) | 7040 (EOID, MID) |
| GSRN (8017, 8018) | 8019 instância da relação de serviço |

A validação acompanha o [GS1 Barcode Syntax Engine](https://github.com/gs1/gs1-syntax-engine), que o
Resolver usa para aceitar cada requisição (os testes de desenvolvimento comparam os dois caso a caso). Dois
limites deliberados: valores alfanuméricos usam só letras, números, `.`, `-` (e `_` nos qualificadores),
porque o serviço de cadastro troca `/` por `_` nos ids dos documentos e outros símbolos exigiriam
percent-encoding; e o ITIP é oferecido sem o 22, que o Syntax Engine recusa sem um GTIN.

**Atributos de dados** (§4.10): todo AI que o GS1 Barcode Syntax Dictionary marca como atributo de dados
GS1 Digital Link, o que exclui (8200), (03) e (8014), como faz o padrão. O portal os valida com o próprio
GS1 Barcode Syntax Engine (versão 1.4.1, a mesma usada pelo Resolver), inclusive os pares inválidos e as
associações obrigatórias da §4.13 das GS1 General Specifications; valores com qualquer caractere do CSET 82
recebem percent-encoding quando preciso. Não há número fixo de atributos por QR Code: a etiqueta avisa
quando o conteúdo não cabe mais na versão escolhida.

## Referência das APIs

### Resolver (público)

| Requisição | Resultado |
|---|---|
| `GET /{AI}/{valor}[/{AI do qualificador}/{valor}…]` | Redirecionamento `307` para o destino principal; sobe pelos qualificadores (série → lote → variante → chave) quando um nível não tem cadastro |
| `…?linkType=gs1:pip` (também `pip`, `https://gs1.org/voc/pip`, `defaultLink`) | Redirecionamento para esse tipo de link; `404` se o cadastro não o tiver |
| `…?linkType=linkset` ou `Accept: application/linkset+json` | Linkset (RFC 9264, válido no schema de linkset da GS1); `application/ld+json` para JSON-LD |
| `Accept-Language`, `Accept`, `context` | Escolha entre links do mesmo tipo por idioma, tipo de mídia ou contexto |
| Navegador (`Accept: text/html`) num erro | Página HTML (não encontrado, informação indisponível com os links disponíveis, código inválido), pt-BR / en-GB |
| `GET /eh{hexadecimal}`, `GET /ex{base 64}` | EPC em binário (por exemplo, de uma etiqueta NFC) resolvido como o GS1 Digital Link que ele representa; atributos de dados que ele traz são repassados na query string; `400` se não decodificar |
| `GET /.well-known/gs1resolver` | Arquivo de descrição do Resolver; `resolverRoot` e `contact` vindos da configuração |
| `GET /` | Página inicial |

A query string da leitura é repassada ao destino exatamente como foi enviada (GS1-Conformant Resolver 2.12).

### API de cadastro (`/api`, token bearer)

Toda operação, exceto `/api/heartbeat`, exige `Authorization: Bearer <SESSION_TOKEN>`. Documentação
interativa: `https://<FQDN>/api/docs` (**Authorize** com `Bearer <token>`).

| Operação | Origem | Para quê |
|---|---|---|
| `POST /api/new` | oficial | Criar cadastros; acrescenta a um documento existente (formato v3, lista aceita, v2 convertido) |
| `GET /api/{AI}/{valor}` | oficial | Ler todos os cadastros (entradas) de uma chave |
| `GET /api/{AI}/{valor}/{qualificadores…}` | oficial | Ler a entrada de um conjunto de qualificadores |
| `PUT /api/{AI}/{valor}` | oficial | Alterar uma entrada mesclando (links casados por tipo, idioma e contexto) |
| `DELETE /api/{AI}/{valor}` | oficial | Excluir o documento, ou só os links enviados no corpo |
| `GET /api/index` | oficial, **agora protegida** | Identificadores de todos os documentos |
| `GET /api/summary[?links=true]` | **nova** | Uma linha por cadastro: âncora, qualificadores, descrição, tipo principal, número de links (e os links) |
| `GET /api/heartbeat` | oficial | Sinal de vida (pública) |

```bash
TOKEN=…   # SESSION_TOKEN do .env
curl -s -X POST https://id.example.org/api/new -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{
  "anchor": "/01/09506000134352", "qualifiers": [{"10": "L2026A"}], "itemDescription": "Açaí orgânico 500 g",
  "defaultLinktype": "gs1:pip",
  "links": [{"linktype": "gs1:pip", "href": "https://brand.example/acai", "title": "Informações do produto", "hreflang": ["pt"]}]
}'
curl -s -H "Authorization: Bearer $TOKEN" "https://id.example.org/api/summary?links=true"
curl -sI https://id.example.org/01/09506000134352/10/L2026A        # 307 → https://brand.example/acai
```

### API do portal (`/portal/api`, cookie de sessão)

Usada pelas páginas do próprio portal; a tabela completa, com perfis e parâmetros, está no
[guia do desenvolvedor](guia-do-desenvolvedor.md#7-api-do-portal). Gravações exigem requisição da mesma
origem com corpo JSON; as mensagens voltam como códigos neutros de idioma traduzidos pelo navegador. Toda
chamada confere o perfil e os prefixos de empresa GS1 do usuário.

### API das organizações (`/portal/api/v1`, chave de API)

Para os sistemas da própria organização (um ERP, um PIM, uma loja): as mesmas regras do portal, limitadas aos
cadastros da organização ([ADR 0005](adr/0005-api-das-organizacoes.md)). Um administrador cria uma chave no portal
(menu do usuário → **Chaves de API**: escopos, prefixos opcionais, validade) e a vê uma vez; toda chamada a envia
como `Authorization: Bearer rk_<id>.<segredo>`. A descrição é pública: `GET /portal/api/v1/openapi.json`
(OpenAPI 3.1). As requisições são limitadas por chave (120 por minuto por padrão; depois, 429 com `Retry-After`).

| Operação | Escopo | Para quê |
|---|---|---|
| `GET /portal/api/v1/` | qualquer | A chave, a sua organização, o seu limite |
| `GET /portal/api/v1/records?key=&limit=&after=` | `records:read` | Os cadastros ao alcance, uma página por vez |
| `GET /portal/api/v1/records/{key}/{value}?qualifiers=/10/L1` | `records:read` | Um cadastro: descrição, links, Digital Link |
| `PUT /portal/api/v1/records/{key}/{value}?qualifiers=` | `records:write` | Criar (201) ou substituir (200): `{description, links: [{linkType, url, title, hreflang}]}` |
| `DELETE /portal/api/v1/records/{key}/{value}?qualifiers=` | `records:write` | Excluir um cadastro |
| `GET /portal/api/v1/labels/{key}/{value}?format=svg\|png&…` | `labels:read` | A etiqueta com QR Code, com as opções da do portal |

```bash
curl -s -H "Authorization: Bearer $KEY" https://id.example.org/portal/api/v1/records/01/09506000134352
curl -s -X PUT -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"description":"Açaí orgânico 500 g","links":[{"linkType":"gs1:pip","url":"https://brand.example/acai","hreflang":["pt"]}]}' \
  https://id.example.org/portal/api/v1/records/01/09506000134352
```

## Requisitos do sistema

| | Requisito |
|---|---|
| **Sistema operacional** | Ubuntu Server 22.04 ou 24.04 LTS para o instalador; qualquer Linux (x86-64 ou ARM64) com Docker para instalação manual |
| **Software** | Docker Engine com o plugin Compose **2.24 ou superior** (o instalador instala os dois); nginx e Certbot quando o servidor termina o TLS; `git` |
| **Hardware** (orientação) | 2 vCPU, 2 GB de RAM (4 GB recomendados), 10 GB livres em disco para imagens, banco e backups |
| **Rede** | Um nome DNS (por exemplo `id.example.org`) apontando para o servidor; portas 80 e 443 acessíveis (ou um balanceador/proxy que termine o TLS); HTTPS de saída para montar as imagens (Docker Hub, PyPI, npm, NodeSource, GitHub para o GS1 Barcode Syntax Engine) e para o verificador de links |
| **Usuários do portal** | Um navegador atual (Chrome, Edge, Firefox, Safari) |
| **Desenvolvimento** (opcional) | Python 3.12, nginx, Playwright com Chromium; compilador C e `make` para o GS1 Barcode Syntax Engine; Node.js para a comparação com o GS1 Syntax Engine |

## Instalação com o script para Ubuntu

Num servidor com um nome DNS apontando para ele:

```bash
git clone https://github.com/ricardomelo/GS1_DigitalLink_Resolver_CE.git
cd GS1_DigitalLink_Resolver_CE
git switch gs1br/develop            # se não for o branch padrão
sudo scripts/install.sh
```

O script pergunta, validando cada resposta:

| Pergunta | Observações |
|---|---|
| Nome de domínio | Sem `https://` |
| Modo HTTPS | `letsencrypt` (nginx + certificado gratuito, renovado automaticamente), `certificate` (seus arquivos PEM), `external` (TLS num balanceador ou outro proxy) |
| E-mail / arquivos do certificado | Avisos do Let's Encrypt, ou os caminhos do seu certificado e da chave |
| Operador | Nome da organização (obrigatório), site, endereço, telefone — publicados em `/.well-known/gs1resolver` |
| Primeiro usuário do portal | Nome e senha; deixe a senha vazia para que uma seja gerada e mostrada uma vez |
| Backup diário, usuário do docker | Cron às 02:30; a conta que pode usar o `docker` sem `sudo` |

Depois de um resumo e da sua confirmação, ele instala o Docker e o nginx/Certbot se preciso, **gera a senha
do MongoDB e o token da API**, grava o `.env` (modo 600), monta e inicia os serviços, espera que respondam,
retira do `.env` a senha do primeiro usuário, configura o nginx e o certificado, agenda o backup e confere
o endereço público. O log fica em `/var/log/gs1-resolver-install.log` (nunca com as senhas).

**Rodar de novo** é o jeito de mudar configurações ou reparar uma instalação: os valores atuais são
oferecidos como padrão, segredos, usuários e dados são mantidos, um site que já tem certificado é mantido, o
`.env` anterior é guardado como `.env.bak-<data>`. Para automação:

```bash
sudo FQDN=id.example.org TLS_MODE=letsencrypt CERTBOT_EMAIL=ops@example.org \
     RESOLVER_ORG_NAME="Example Org" PORTAL_ADMIN_USERNAME=admin \
     scripts/install.sh --non-interactive
```

## Instalação manual

1. **Docker.** Instale o Docker Engine e o plugin Compose (≥ 2.24) seguindo
   [docs.docker.com/engine/install](https://docs.docker.com/engine/install/).
2. **Código.** Clone este repositório e mude para o `gs1br/develop`.
3. **Configuração.** Crie o `.env` ao lado do `docker-compose.yml` (os valores dele substituem os do
   `.env.example`):

   ```bash
   PASS=$(openssl rand -hex 24); TOKEN=$(openssl rand -hex 32)
   cat > .env <<EOF
   MONGO_INITDB_ROOT_USERNAME='gs1resolver'
   MONGO_INITDB_ROOT_PASSWORD='$PASS'
   MONGO_URI='mongodb://gs1resolver:$PASS@database-service:27017'
   SESSION_TOKEN='$TOKEN'
   FQDN='id.example.org'
   RESOLVER_ORG_NAME='Example Org'
   PORTAL_ADMIN_USERNAME='admin'
   PORTAL_ADMIN_PASSWORD='escolha-uma-senha-longa'
   PROXY_BIND_ADDRESS='127.0.0.1'
   DATABASE_BIND_ADDRESS='127.0.0.1'
   EOF
   chmod 600 .env
   ```

4. **Iniciar.** `docker compose up -d --build` e depois confira
   `curl -s http://127.0.0.1:8080/portal/healthz` (`{"portal":"ok","resolver":"ok","worker":"ok","mail":"off"}`) e uma requisição que
   chega ao Resolver pelo proxy: `curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/.well-known/gs1resolver`
   (`200`). A verificação de saúde fala direto com o servidor web, sem passar pela rota do Resolver no proxy.
5. **HTTPS.** Coloque um proxy reverso TLS na frente de `127.0.0.1:8080`. Com nginx: copie
   `scripts/templates/nginx-site-http.conf` para `/etc/nginx/sites-available/gs1resolver`, substitua
   `@FQDN@` e `@PROXY_PORT@` (8080), ative o site e rode `sudo certbot --nginx -d id.example.org --redirect`.
6. **Primeiro usuário.** Entre em `https://id.example.org/portal/` com `PORTAL_ADMIN_*`, troque a senha em
   Opções e depois apague `PORTAL_ADMIN_PASSWORD` do `.env`. Ou crie usuários com
   `docker compose exec portal-service python create_user.py <nome>`.
7. **Backup.** `sed "s|REPOSITORY|$PWD|" scripts/resolver-backup.cron | sudo tee /etc/cron.d/resolver-backup`.

Numa **máquina de desenvolvimento** não é preciso `.env`: `docker compose up -d --build` roda com os padrões
do `.env.example` (token `secret`, como no projeto oficial). Acrescente
`RESOLVER_PUBLIC_URL=http://localhost:8080` ao `.env` para usar o portal em HTTP simples e abra
http://localhost:8080/.

## Configuração

Todos os serviços leem o `.env.example` (padrões de desenvolvimento, versionados) e depois o `.env` (valores
da instalação, nunca versionados).

| Variável | Para quê |
|---|---|
| `MONGO_INITDB_ROOT_USERNAME`, `MONGO_INITDB_ROOT_PASSWORD` | Usuário root do MongoDB (aplicado quando o volume do banco é criado) |
| `MONGO_URI` | String de conexão dos serviços web e de cadastro |
| `SESSION_TOKEN` | Token bearer da API de cadastro (usado também pelo portal) |
| `FQDN` | Domínio do Resolver; a raiz do Resolver é `https://FQDN` |
| `RESOLVER_ORG_NAME`, `RESOLVER_ORG_URL`, `RESOLVER_CONTACT_*` | Operador no arquivo de descrição, na página inicial e nas páginas do Resolver (nome com link para `RESOLVER_ORG_URL`) |
| `RESOLVER_TERMS_URL` | Opcional: os termos de uso do operador, publicados como `termsOfUse` no arquivo de descrição (omitido quando vazio) |
| `RESOLVER_PUBLIC_URL` | Endereço público do portal quando não é `https://FQDN` (por exemplo, desenvolvimento) |
| `PORTAL_ADMIN_USERNAME`, `PORTAL_ADMIN_PASSWORD` | Primeiro usuário do portal, criado só enquanto não há nenhum |
| `PORTAL_DB_NAME`, `PORTAL_DB_USERNAME`, `PORTAL_DB_PASSWORD` | Banco e usuário próprios do portal (criado pelo `portal-db-init`); o instalador gera a senha |
| `PORTAL_SECRET_KEY` | Chave que assina as sessões do portal; todas as réplicas do portal precisam compartilhá-la (o instalador a gera; vazia: uma chave guardada no volume do portal) |
| `PORTAL_JOURNAL_SESSION_DAYS` (180), `PORTAL_JOURNAL_RECORD_DAYS` (0), `PORTAL_JOURNAL_ADMIN_DAYS` (0) | Dias que o diário guarda entradas, alterações de cadastros e eventos de administração (0 = para sempre) |
| `PORTAL_MAIL_HOST`, `PORTAL_MAIL_PORT`, `PORTAL_MAIL_SECURITY` (`starttls`), `PORTAL_MAIL_USERNAME`, `PORTAL_MAIL_PASSWORD`, `PORTAL_MAIL_FROM` | O relay de e-mail do portal ([ADR 0004](adr/0004-e-mail.md)): convites, recuperação de senha, avisos de segurança; servidor vazio: e-mail desligado. Porta 587 (STARTTLS) ou 465 (TLS); o instalador pergunta por eles; detalhes e um comando de teste na [documentação das extensões](../extensions/README.md#e-mail) (em inglês) |
| `PORTAL_API_RATE_PER_MINUTE` (120), `PORTAL_API_KEY_MAX_DAYS` (365) | A API das organizações: requisições por chave e minuto; a maior validade de uma chave de API |
| `RESOLVER_LOG_DAYS` (90), `RESOLVER_LOG_COUNTRY_HEADER` | O registro das requisições ao Resolver ([ADR 0006](adr/0006-registro-de-requisicoes.md)): dias em que cada evento (e cada chamada da API das organizações) é guardado, 0 o desliga; um cabeçalho com o país de duas letras posto por um proxy na frente (vazio: sem país) |
| `PORTAL_TIME_ZONE` (UTC), `PORTAL_STATS_DAYS` (800) | Os dias das contagens diárias de requisições (um nome IANA; o instalador grava o do servidor) e por quanto tempo as contagens ficam guardadas |
| `PORTAL_WORKER` (`external`) | Onde rodam as importações e verificações de links: `external`, o serviço `portal-worker`; `embedded`, uma thread do próprio portal, para uma instalação sem esse serviço |
| `PORTAL_SESSION_IDLE_MINUTES` (30), `PORTAL_SESSION_MAX_HOURS` (12), `PORTAL_COOKIE_SECURE` | Configurações opcionais do portal: minutos sem uso e horas depois da entrada até a sessão terminar, cookie Secure |
| `PROXY_BIND_ADDRESS`, `DATABASE_BIND_ADDRESS` | Endereços do host para as portas 8080 e 27017 (lidos pelo Compose só do `.env`) |
| `WEB_SERVICE_REPLICAS`, `DATA_ENTRY_SERVICE_REPLICAS`, `PORTAL_SERVICE_REPLICAS`, `PORTAL_WORKER_REPLICAS` (1) | Contêineres de cada serviço, de 1 a 20 (lidos pelo Compose só do `.env`; o instalador os grava) |
| `WEB_SERVICE_PROCESSES`, `DATA_ENTRY_SERVICE_PROCESSES`, `PORTAL_SERVICE_PROCESSES` (2) | Processos do gunicorn em cada contêiner dos três serviços web (lidos pelo Compose só do `.env`) |

## Operação

```bash
git pull && docker compose up -d --build                         # atualizar
curl -s http://127.0.0.1:8080/portal/healthz                     # {"portal":"ok","resolver":"ok","worker":"ok","mail":"off"}
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/.well-known/gs1resolver   # 200: Resolver pelo proxy
docker compose exec portal-service python create_user.py maria --role editor   # incluir ou redefinir um usuário
# quem alterou o quê: menu do usuário → Auditoria (administradores), ou o log do contêiner:
docker compose logs -f portal-service | grep portal.audit
docker compose logs --tail=60 portal-worker                      # importações e verificações de links (tarefas)
sudo scripts/resolver-backup.sh                                  # backup agora (todos os bancos + volume do portal)
# mais réplicas: mude, por exemplo, WEB_SERVICE_REPLICAS=2 no .env e depois
docker compose up -d                                             # cria ou remove contêineres; o proxy acompanha em até 10 s
docker compose ps                                                # uma linha por contêiner (…-web-service-1, …-web-service-2)
docker compose build --pull frontend-proxy-service && docker compose up -d   # a última correção de segurança do nginx 1.30
```

Defina o número de réplicas no `.env`, e não com `docker compose up --scale`: o próximo `docker compose up`
(toda atualização) volta aos números do `.env`. Os logs de um serviço mostram todas as réplicas, cada linha
com o nome do seu contêiner na frente.

Os backups vão para `/var/backups/resolver` (14 dias). Restaure o banco com
`mongorestore … --archive --gzip --drop` via `docker compose exec -T database-service` e depois rode
`docker compose up -d` (o usuário do banco do portal recebe de novo a senha do `.env`); o volume do portal
guarda só a chave de sessão reserva e cópias dos arquivos antigos. Os comandos exatos estão na
[documentação das extensões](../extensions/README.md#daily-backup). Guarde cópias em outra máquina.

## Desenvolvimento e testes

Os testes de [`dev-tests/`](../../dev-tests/README.md) rodam sem Docker nem MongoDB (o banco do portal é
substituído pelo `mongomock`; o CI também os roda num MongoDB real); a lista completa, com
o número de verificações e o que cada programa cobre, está no
[guia do desenvolvedor](guia-do-desenvolvedor.md#13-testes-de-desenvolvimento-dev-tests).

```bash
pip install -r web_server/src/requirements.txt -r portal/requirements.txt jsonschema playwright opencv-python-headless mongomock
playwright install chromium
python dev-tests/resolver/test_resolver.py
# GS1 Barcode Syntax Engine para os atributos de dados, como a imagem do portal o compila:
bash portal/tools/build-syntax-engine.sh /tmp/gs1se
GS1_SYNTAX_ENGINE_DIR=/tmp/gs1se python dev-tests/portal/test_data_attributes.py
# opcional, compara com o GS1 Syntax Engine usado pelo Resolver:
mkdir -p /tmp/se && (cd /tmp/se && npm init -y && npm pkg set type=module && npm install gs1encoder)
GS1_SYNTAX_ENGINE=/tmp/se python dev-tests/portal/test_keys.py
```

Todos os programas também rodam pelo pytest, por uma camada fina (`dev-tests/test_programs.py`) que executa
cada um como subprocesso e mostra o número de verificações de cada programa ao final; os grupos `resolver`,
`portal`, `e2e`, `home`, `install` e `database` podem ser escolhidos com `-m`:

```bash
pip install pytest
python -m pytest dev-tests                 # todos (os que não têm o que precisam são pulados)
python -m pytest dev-tests -m resolver     # um grupo
DEV_TESTS_STRICT=1 python -m pytest dev-tests -m portal   # como no CI: o que falta é falha, não pulo
```

**Integração contínua.** O workflow `.github/workflows/dev-tests.yml` roda os testes no GitHub Actions a cada
push e pull request para `gs1br/develop` (mudanças só de documentação não disparam), em seis jobs paralelos:
Resolver (com EPC binário, API de cadastro e a suíte da GS1), portal, portal num MongoDB real (um contêiner
de serviço `mongo:7`), portal no Chromium, página inicial com nginx e instalador. O portal no MongoDB é um
job informativo: uma falha nele aparece, mas não reprova a execução (o portal no Chromium e o instalador
começaram assim e são obrigatórios desde o item 2.3). O teste do proxy roda no nginx 1.30 do nginx.org,
como na imagem do proxy. As versões de Python, Node.js, engines, suíte da GS1, Docker Compose e nginx ficam
fixadas em `.github/actions/dev-tests-setup/action.yml`; engines, pacotes e o navegador ficam em cache. O resultado de cada job, com a contagem de verificações, aparece no resumo da execução.

As imagens do README e do guia do portal, nos dois idiomas, são geradas por `dev-tests/docs/screenshots.py`.

## Backlog em aberto

Situação em 14 de outubro de 2026. A fase 1, a base de conformidade, está concluída: a revisão cláusula a
cláusula, o modelo de cadastro do GS1-Conformant Resolver 2.5.9, um link padrão acima de todo cadastro, as
correções de resolução, o EPC em binário e a própria suíte de testes de Resolver da GS1 (aprovada numa
instalação de homologação). O item 2.1, os ajustes rápidos (limites da sessão, página inicial, aviso da
comunidade), o item 2.2, a integração contínua (os testes de desenvolvimento pelo pytest no GitHub
Actions), o item 2.3, a arquitetura para escala (os dados do portal no MongoDB, as tarefas em segundo plano
num serviço worker, réplicas de todos os serviços sem estado; [ADR 0001](adr/0001-estado-do-portal-no-mongodb.md)),
o item 2.4, os tenants (organizações donas de prefixos de empresa GS1, o administrador do servidor e o acesso
de suporte, uma trilha de auditoria por organização; [ADR 0002](adr/0002-organizacoes.md)), e o item 2.5, uma
fonte única para as regras GS1 (chaves, qualificadores e formatos do GS1 Barcode Syntax Dictionary, uma versão do
engine para todos os serviços, as mensagens do engine traduzidas, uma verificação semanal de atualizações;
[ADR 0003](adr/0003-regras-gs1-do-dicionario.md)), e o item 3.1, o e-mail (um relay autenticado, convites, recuperação
de senha por link de uso único, notificações com preferências por usuário; [ADR 0004](adr/0004-e-mail.md)), e o item
3.2, a API das organizações (uma API versionada do portal para os sistemas das próprias organizações, chaves de API
com escopos, validade e um limite de requisições; [ADR 0005](adr/0005-api-das-organizacoes.md)), e o item 4.1, o
registro das requisições ao Resolver (cada requisição registrada pelo Resolver sem dados pessoais, contagens diárias
por chave, uma tela Acessos; [ADR 0006](adr/0006-registro-de-requisicoes.md)), também estão
concluídos. O que foi feito está no [histórico](historico.md) e no
[changelog](../extensions/CHANGELOG.md). Os itens abaixo seguem a ordem combinada; os tamanhos são relativos
(P, M, G). A ordem põe primeiro aquilo em que os itens seguintes se apoiam: o armazenamento de dados do portal
e os tenants vêm antes da API, do e-mail e dos analytics, que precisam saber de quem são os dados que tratam.

| Fase | # | Item | Tam. | Depende de |
|---|---|---|---|---|
| Log de resolução e analytics | 4.2 | **Página inicial pós-login com indicadores**, cada tenant vendo só os seus prefixos e chaves (o administrador do servidor vê a instalação inteira): uso, qualidade da resolução (primeiro os 404 de códigos desconhecidos), qualidade dos cadastros, operação, governança; exportação para Excel e CSV | G | 4.1, 2.4 |
| | 4.3 | **Monitoramento e alertas** por e-mail: Resolver fora do ar (verificado pelo proxy), falha de backup, picos de 404, vencimento do certificado | M | 4.2, 3.1 |
| | 4.4 | **Resumo semanal por e-mail** por tenant | P | 4.2, 3.1 |
| Domínios próprios e estúdio de etiquetas | 5.1 | **O domínio do próprio tenant no QR Code** (URI Syntax 4.11): domínios cadastrados por tenant e comprovados por um registro DNS; padrão por prefixo, escolhido ao gerar a etiqueta (domínio da instalação quando não houver); ou o domínio aponta para o Resolver (certificado emitido por domínio) ou o servidor do tenant redireciona para ele mantendo caminho e query string; um domínio só responde pelos prefixos do seu tenant; caminho-base opcional | G | 2.4, 2.5 |
| | 5.2 | **Escolha da dimensão X e exportação em PDF** | M | 5.1 |
| | 5.3 | **QR Code com EAN-13/UPC-A (e EAN-8/UPC-E)** para a transição ao 2D, com as regras de texto legível das GS1 General Specifications | M | 5.2 |
| | 5.4 | **Todos os formatos de etiqueta num único zip** | P | 5.3 |
| Página de destinos | 6.1 | **Página com os links do item** como destino padrão: gerada pelo Resolver, pensada primeiro para o celular, um ícone por tipo de link, logotipo e cores por prefixo, idiomas, cliques registrados | G | 4.1, 5.1 |
| | 6.2 | **Verified by GS1 na página de destinos**: um link que consulta a chave no Verified by GS1, para os tipos de chave que o serviço aceita; ligado ou desligado por instalação e por tenant; só na página, sem entrar no linkset (o tipo de link `gs1:verificationService` designa um serviço GS1 Lightweight Messaging, não uma página web) | P | 6.1 |
| Produção | 7.1 | **Login único (SSO)** no portal, por tenant; limites de exportação por perfil | M | 2.4 |
| | 7.2 | **Prontidão para produção**: troca de segredos, instalação numa máquina limpa (com verificação pelo proxy no final), cópia do backup fora do servidor e ensaio de restauração, checklist do domínio de produção | M | — |
| | 7.3 | **Acabamento**: revisão dos nomes de AIs em português, logotipo na página inicial e nas páginas do Resolver, títulos padrão no idioma do link (achado F21 da revisão de conformidade) | P | — |
| | 7.4 | **Teste de carga e ensaio de escala**: carga-alvo combinada, várias réplicas do Resolver e do portal, replica set do MongoDB, resultados registrados | M | 2.3 |
| Padrões | 8.1 | **Erratas e Work Requests à GS1**: E1–E12 da [revisão de conformidade](revisao-de-conformidade.md), e uma issue na suíte de testes de Resolver da GS1 sobre a errata E12 | P | — |

Mais adiante, quando for conveniente:

- Busca por código lendo os dados brutos do leitor (sem parênteses, FNC1/GS, identificadores de simbologia
  `]d2`/`]Q3`) pelo engine, e EPC em binário (`eh…`, `ex…`, hexadecimal) lido de um leitor RFID.
- Uma opção de etiqueta EPC/NFC: o SGTIN de um cadastro como `eh…`/`ex…` para gravar etiquetas NFC ou
  híbridas (exige um codificador).
- Exportar só os registros filtrados; filtros que podem ser salvos como favoritos.
- Um jeito de corrigir cadastros feitos antes de a regra 2 do 2.5.9 ser aplicada (hoje só são sinalizados).
- API de cadastro: conferir também os valores pelo engine, não só a estrutura (restante do achado F11).
- Uma versão em português da documentação de extensões.

## Licença e créditos

Licenciado sob a [Apache License 2.0](../../LICENSE), como o projeto oficial.

- **GS1 Resolver Community Edition** — a GS1 Resolver Community (projeto e código originais de Nick
  Lansley e colaboradores).
- **GS1 Barcode Syntax Engine** e **GS1 Barcode Syntax Dictionary** — GS1 AISBL (Terry Burton), usados pelo
  Resolver para validar cada requisição e pelo portal para validar atributos de dados (Apache License 2.0,
  baixados e compilados quando as imagens são montadas).

GS1, o logotipo GS1 e GS1 Digital Link são marcas da GS1 AISBL.
