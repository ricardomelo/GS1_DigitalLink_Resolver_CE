# GS1 Digital Link Resolver CE — Expansion Pack (documentação em português)

*English version: [README](../../README.md).*

> **Aviso importante (do projeto oficial).** Este software livre e de código aberto não é mantido pela
> GS1. Questões levantadas aqui podem ser respondidas pela comunidade, mas não serão tratadas pela própria
> GS1. Quem usa este software não deve supor que ele esteja totalmente conforme o padrão publicado
> [GS1-Conformant Resolver](https://ref.gs1.org/standards/resolver/).

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
13. [Licença e créditos](#licença-e-créditos)

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
| **Portal** (`/portal/`) | Entrada com senha por usuário (com botão de mostrar/ocultar); editor para qualquer chave primária e qualificadores, com conferências GS1 enquanto se digita; destinos por tipo de link GS1, idioma e título; destino principal; repasse da query string por link; etiquetas com QR Code (PNG/SVG) nas dimensões do guia *QR Codes powered by GS1*, com escolha de versão, correção de erros e texto legível, opcionalmente com atributos de dados GS1 Digital Link (validade, peso, preço…); lista de registros com busca e filtros por tipo de chave e qualificador; importação/exportação de planilhas (XLSX, CSV) com prévia; verificador de links |
| **Governança** | Perfis (administrador, editor, leitor); acesso limitado a prefixos de empresa GS1 por usuário; tela de administração de usuários com senhas temporárias; histórico de cada cadastro com restauração; auditoria com filtros e exportação CSV |
| **Chaves e qualificadores** | As 16 chaves primárias da URI Syntax §4.3 e todos os qualificadores da §4.4, com os formatos da §4.6, a ordem e os caminhos compostos da §4.9, validados como faz o GS1 Barcode Syntax Engine |
| **Atributos de dados** | Todos os atributos de dados da URI Syntax §4.10 nos QR Codes, validados pelo GS1 Barcode Syntax Engine (formatos, dígitos verificadores, datas, listas de códigos e as regras de associação das General Specifications); repassados pelo Resolver aos destinos |
| **Resolver** | Subida na hierarquia de qualificadores (série → lote → variante → chave), regras de 404, formas de `linkType`, `defaultLink`, linkset RFC 9264 válido no schema da GS1, JSON-LD sob pedido, `fwqs` por link, páginas HTML em pt-BR / en-GB para navegadores |
| **API de cadastro** | `GET /api/summary` (todos os cadastros numa requisição); `GET /api/index` passou a exigir o token; o "Authorize" do Swagger funciona em todas as operações protegidas |
| **Configuração** | Padrões no `.env.example` + `.env` opcional para todos os serviços; arquivo de descrição (`/.well-known/gs1resolver`) montado a partir da configuração; endereços de bind para as portas publicadas |
| **Página inicial** (`/`) | Menu para o portal, a documentação da API, o padrão GS1 Digital Link, gs1.org e este código; independente do domínio |
| **Operação** | Instalador interativo para Ubuntu 22.04 / 24.04; backup diário do banco e da configuração do portal; o Compose reinicia o proxy quando um serviço atrás dele é recriado |
| **Qualidade** | Testes de desenvolvimento do Resolver, da API de cadastro, do portal (unitários e de ponta a ponta no navegador), da página inicial, do instalador e do verificador de links; comparação com o GS1 Syntax Engine |

## Arquitetura

```mermaid
flowchart LR
    client["Leitor / navegador"] -->|HTTPS| edge["nginx do host + Certbot<br/>(TLS, porta 443)"]
    edge -->|"127.0.0.1:8080"| proxy["frontend-proxy-service<br/>nginx"]
    proxy -->|"/  e  /home/"| home["Página inicial<br/>(estática, na imagem do proxy)"]
    proxy -->|"/{AI}/{valor}…"| web["web-service<br/>Resolver"]
    proxy -->|"/api"| de["data-entry-service<br/>API REST + Swagger"]
    proxy -->|"/portal/"| portal["portal-service<br/>portal de gestão de links"]
    portal -->|"token bearer"| de
    web --> db[("MongoDB<br/>database-service")]
    de --> db
    portal -.->|"usuários, histórico"| vol[("volume<br/>resolver-portal-config")]
```

| Serviço | Contêiner | Papel | Publicado |
|---|---|---|---|
| `frontend-proxy-service` | `frontend-proxy-server` | Encaminha `/`, `/api`, `/portal/` e todos os Digital Links; serve a página inicial | `${PROXY_BIND_ADDRESS}:8080` |
| `web-service` | `resolver-web-server` | Resolve GS1 Digital Links (redirecionamentos, linksets, páginas HTML) | interno |
| `data-entry-service` | `data-entry-server` | API REST para criar, ler, alterar e excluir cadastros | interno (via `/api`) |
| `portal-service` | `resolver-portal` | Portal de gestão de links (Flask + front-end estático) | interno (via `/portal/`) |
| `database-service` | `database-server` | MongoDB | `${DATABASE_BIND_ADDRESS}:27017` |

O portal é um back-end entre o navegador e a API de cadastro: o token da API nunca chega ao navegador, e o
portal lê antes de gravar para usar as operações da API com segurança (POST acrescenta, PUT mescla, DELETE
remove links, o tipo do destino principal é compartilhado por todos os cadastros de uma chave). Os
detalhes estão no [guia do desenvolvedor](guia-do-desenvolvedor.md).

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
repetidas, sessões de 8 horas renovadas a cada uso. A interface segue o idioma do navegador (pt-BR ou
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

Usuários, histórico e auditoria ficam no volume de configuração do portal, que o backup diário inclui.
Usuários criados antes de existirem perfis viram administradores. A ferramenta de linha de comando também
aceita perfis: `docker compose exec portal-service python create_user.py maria --role editor --prefixes 7891234`.

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
| `GET /.well-known/gs1resolver` | Arquivo de descrição do Resolver; `resolverRoot` e `contact` vindos da configuração |
| `GET /` | Página inicial |

A query string da leitura é repassada ao destino, a não ser que o link tenha `"fwqs": false`.

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
   `curl -s http://127.0.0.1:8080/portal/healthz` (`{"portal":"ok","resolver":"ok"}`).
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
| `PORTAL_SESSION_HOURS`, `PORTAL_SECRET_KEY`, `PORTAL_COOKIE_SECURE` | Configurações opcionais do portal |
| `PROXY_BIND_ADDRESS`, `DATABASE_BIND_ADDRESS` | Endereços do host para as portas 8080 e 27017 (lidos pelo Compose só do `.env`) |

## Operação

```bash
git pull && docker compose up -d --build                         # atualizar
docker compose exec portal-service python create_user.py maria --role editor   # incluir ou redefinir um usuário
# quem alterou o quê: menu do usuário → Auditoria (administradores), ou o log do contêiner:
docker compose logs -f portal-service | grep portal.audit
sudo scripts/resolver-backup.sh                                  # backup agora (banco + usuários do portal)
```

Os backups vão para `/var/backups/resolver` (14 dias). Restaure o banco com
`mongorestore … --archive --gzip --drop` via `docker compose exec -T database-service`, e a configuração do
portal extraindo o arquivo dela em `/app/config` do `portal-service`; os comandos exatos estão na
[documentação das extensões](../extensions/README.md#daily-backup). Guarde cópias em outra máquina.

## Desenvolvimento e testes

Os testes de [`dev-tests/`](../../dev-tests/README.md) rodam sem Docker nem MongoDB; a lista completa, com
o número de verificações e o que cada programa cobre, está no
[guia do desenvolvedor](guia-do-desenvolvedor.md#13-testes-de-desenvolvimento-dev-tests).

```bash
pip install -r web_server/src/requirements.txt -r portal/requirements.txt jsonschema playwright opencv-python-headless
playwright install chromium
python dev-tests/resolver/test_resolver.py
# GS1 Barcode Syntax Engine para os atributos de dados, como a imagem do portal o compila:
bash portal/tools/build-syntax-engine.sh /tmp/gs1se
GS1_SYNTAX_ENGINE_DIR=/tmp/gs1se python dev-tests/portal/test_data_attributes.py
# opcional, compara com o GS1 Syntax Engine usado pelo Resolver:
mkdir -p /tmp/se && (cd /tmp/se && npm init -y && npm pkg set type=module && npm install gs1encoder)
GS1_SYNTAX_ENGINE=/tmp/se python dev-tests/portal/test_keys.py
```

As imagens do README e do guia do portal, nos dois idiomas, são geradas por `dev-tests/docs/screenshots.py`.

## Licença e créditos

Licenciado sob a [Apache License 2.0](../../LICENSE), como o projeto oficial.

- **GS1 Resolver Community Edition** — a GS1 Resolver Community (projeto e código originais de Nick
  Lansley e colaboradores).
- **GS1 Barcode Syntax Engine** e **GS1 Barcode Syntax Dictionary** — GS1 AISBL (Terry Burton), usados pelo
  Resolver para validar cada requisição e pelo portal para validar atributos de dados (Apache License 2.0,
  baixados e compilados quando as imagens são montadas).

GS1, o logotipo GS1 e GS1 Digital Link são marcas da GS1 AISBL.
