# Revisão de conformidade

*English version: [Conformance review](../conformance-review.md).*

Revisão, cláusula a cláusula, deste branch frente aos dois padrões GS1 que ele implementa:

- **GS1 Digital Link Standard: URI Syntax**, release 1.7.0 (ratificado, agosto de 2026) — "URI Syntax" abaixo;
- **GS1-Conformant Resolver Standard**, release 1.2.1 (ratificado, agosto de 2026) — "padrão do Resolver"
  abaixo.

Código revisado: branch `gs1br/develop` em `115a054` (1º de outubro de 2026). Só revisão: nada no código foi
alterado. Cada lacuna encontrada vira um item do backlog (seção 7), para que as correções partam de
evidências.

## 1. Resumo

O Resolver atende corretamente ao núcleo do padrão: métodos HTTP, CORS, redirecionamento para um tipo de
link pedido, 404 para entidades desconhecidas e tipos de link ausentes, linkset (JSON, JSON-LD, HTML) reunido
de todos os níveis da hierarquia sem redirecionamentos HTTP, arquivo de descrição do Resolver e tolerância à
barra final. O portal monta URIs GS1 Digital Link conformes para os rótulos.

A revisão encontrou **cinco lacunas em requisitos SHALL** que importam na prática:

| Achado | Cláusula | Em uma frase |
|---|---|---|
| [F9](#f9) | Resolver 2.6.1, 2.5.8 | Sem `linkType`, um registro com dois links do seu tipo padrão em idiomas diferentes responde **300** em vez de redirecionar para o link padrão quando o idioma da requisição não coincide com nenhum, ou quando ela não indica idioma. |
| [F1](#f1) | Resolver 2.5.9 | Um registro qualificado (lote, série…) pode existir sem registro da chave, e então os outros lotes e séries dessa chave respondem 404. |
| [F2](#f2) | Resolver 2.5.9, regra 2 | Registros de série também podem levar lote ou variante, o que o padrão proíbe. |
| [F6](#f6) | Resolver 2.3 | Strings EPC binary (`/eh…`, `/ex…`) não são descomprimidas; respondem 500. |
| [F10](#f10) | Resolver 2.4.1; URI Syntax 4.9, 4.10 | Caminhos com qualificadores fora de ordem ou com atributos de dados no caminho são redirecionados em vez de recusados com 400. |

e várias lacunas menores (seções 3 a 5). Encontrou também **sete candidatos a errata** nos padrões e nos
schemas publicados (seção 6); um deles (ITIP com Consumer Product Variant) é um conflito real entre a URI
Syntax e as GS1 General Specifications.

Contagens (tabelas das seções 4 e 5; uma linha por requisito normativo ou grupo de requisitos próximos):

| Situação | Padrão do Resolver | URI Syntax |
|---|---|---|
| Conforme | 32 | 10 |
| Parcial | 11 | 2 |
| Não conforme | 5 | 0 |
| Não se aplica / recurso opcional não implementado | 3 | 4 |
| A verificar | 1 | 1 |

### Desde a revisão

A revisão descreve o branch em `115a054`. Achados corrigidos desde então, com os commits:

| Achado | Situação | Commits |
|---|---|---|
| [F1](#f1) | Corrigido (item 1.3): salvar um cadastro qualificado de uma chave sem cadastro próprio oferece criá-lo; a lista de registros e a importação sinalizam essas chaves | `83d1ba0`, `3a49ca9` |
| [F2](#f2) | Corrigido (item 1.2): com o AI 21, os AIs 22 e 10 são informativos, fora do cadastro; a API de cadastro os recusa como qualificadores | `61babe1`, `83d1ba0` |
| [F4](#f4) | Revisto e corrigido: quando um cadastro de série e um de lote ou variante se aplicam juntos, o Resolver agora redireciona com o da série (ver F4) | `61babe1` |
| F11 | Corrigido em parte (item 1.2): a API de cadastro confere quais qualificadores cada chave aceita e as regras do 2.5.9; os valores continuam sendo conferidos só pelo portal | `61babe1` |
| [F6](#f6) | Corrigido (item 1.6): `/eh…` e `/ex…` descomprimidos e resolvidos como o GS1 Digital Link equivalente — todos os esquemas EPC que têm Digital Link, esquemas `+` com dados +AIDC, esquemas `++` (hostname ignorado); o linkset é o da URI descomprimida; 400 quando a cadeia não decodifica | `51a0da8`, `895c4b1` |
| F7 | Corrigido (itens 1.5 e 1.6): sem `_id`; `termsOfUse` de `RESOLVER_TERMS_URL`; `validatesAIcombinations` agora verdadeiro (F10); as chaves `"all"` agora valem também para EPC binary (F6) | `4f81234`, `51a0da8`, `895c4b1` |
| F9 | Corrigido (item 1.5): sem `linkType`, o link padrão, salvo quando a requisição indica uma variante; `gs1:defaultLinkMulti` publicado; o primeiro link do tipo principal é o padrão | `4f81234` |
| F10 | Corrigido (item 1.5): caminhos conferidos pelo leitor de Digital Link do engine | `4f81234` |
| F12 | Corrigido (item 1.5): URI original pelo proxy e pelo Resolver; upstream do proxy renomeado (o nome `resolver_web`, enviado como cabeçalho Host, fazia o Werkzeug recusar toda requisição) | `4f81234`, `b9a7631` |
| F13 | Corrigido (item 1.5): query string repassada exatamente como enviada | `4f81234` |
| F14 | Corrigido (item 1.5, decisão do responsável): a opção por destino saiu; `fwqs: false` ignorado | `4f81234`, `db8e342` |
| F15 | Corrigido (item 1.5): 400 em vez de 500 | `4f81234` |
| F16 | Corrigido (item 1.5): 300 como linkset válido, ou página HTML | `4f81234` |
| F17 | Corrigido (item 1.5): JSON-LD na página HTML; HTML sem cabeçalho `Accept` | `4f81234` |
| F18 | Corrigido (item 1.5): links sem tipo de mídia tratados | `4f81234` |
| F19 | Corrigido (item 1.5): pesos q e busca da RFC 4647 | `4f81234` |
| F22 | Resolvido (item 1.4, decisão do responsável): a suíte de testes da GS1 aceita os dois namespaces; os linksets e o contexto JSON-LD agora escrevem os tipos de link `gs1:` em `https://ref.gs1.org/voc/`, como o 2.14 define; documentos gravados sem alteração (seção 8) | `bc573c4` |

Ainda em aberto: F20 e F23 (erratas E2 e E4), F21 (item 7.3).

## 2. Método

1. Todos os requisitos normativos dos dois padrões foram listados — SHALL, SHALL NOT, SHOULD, SHOULD NOT,
   RECOMMENDED e MAY quando restringe —, com a cláusula, incluindo a declaração de conformidade do padrão do
   Resolver (seção 5 daquele padrão), a ABNF da URI Syntax e os schemas normativos indicados pelo padrão do
   Resolver (schema do linkset, schema do arquivo de descrição).
2. Cada requisito foi conferido no código (arquivo e função) e, quando o comportamento importava, com uma
   requisição: o código real do Resolver pelo test client do Flask com o GS1 Barcode Syntax Engine 1.4.1 real
   (a estrutura de `dev-tests/resolver/test_resolver.py`), e a regra `proxy_pass` do proxy num nginx local. A
   seção 8 lista as requisições para que possam ser repetidas, inclusive numa instalação.
3. Cada requisito recebeu um **lado** e uma **situação**:

| Lado | Significado |
|---|---|
| Consulta | o Resolver respondendo a um GS1 Digital Link (`web_server/`, proxy) |
| Cadastro | o que pode ser cadastrado: portal (`portal/`) e API de cadastro (`data_entry_server/`) |
| Descrição | o arquivo de descrição do Resolver (`/.well-known/gs1resolver`) |
| Rótulos | as URIs GS1 Digital Link que o portal grava nos QR codes |
| Implantação | a instalação (TLS, proxy) |

| Situação | Significado |
|---|---|
| Conforme | o comportamento atende ao requisito |
| Parcial | atende no caso comum mas não em todos, ou o portal atende e a API não |
| Não conforme | o comportamento contraria o requisito |
| Não se aplica | o requisito não se aplica, ou descreve um recurso opcional não implementado |
| A verificar | precisa de evidência que esta revisão não tem (suíte de testes de conformidade da GS1, item 1.4) |

Os testes de desenvolvimento existentes (`dev-tests/`) foram rodados antes da revisão; as 128 verificações
do Resolver passam.

## 3. Achados

Os achados F1 a F8 já eram conhecidos antes da revisão e são confirmados ou descartados aqui; do F9 em diante
são novos.

### <a id="f1"></a>F1 — Nenhum link padrão acima de um registro qualificado (Resolver 2.5.9) — não conforme

> For any entry point, that is, for any GS1 Digital Link URI, no matter how granular, there SHALL be a
> default link available either at the entry level or at a higher level.

O portal aceita um registro de lote ou série de uma chave que não tem registro próprio. Então a própria
chave e todos os outros lotes ou séries dela respondem 404: com apenas `/01/09506000134369/10/L1`
cadastrado, `/01/09506000134369` e `/01/09506000134369/10/L2` respondem 404. É isso que o teste da GS1
"Resolver does not handle unknown value for a valid key qualifier" detecta. O requisito é sobre os dados,
então a correção é no cadastro. Lado: cadastro. **Ação: item 1.3.** *Corrigido em `83d1ba0` e `3a49ca9`.*

### <a id="f2"></a>F2 — Registros de série com lote ou variante (Resolver 2.5.9, regra 2) — não conforme

> If a link is associated with AI 01 (GTIN) or AI 8006 (ITIP) plus AI 21 (serial), then AI 22 (CPV) or AI 10
> (batch/lot number) SHALL NOT be defined for that association.

`KEY_SHAPES` em `portal/gs1.py` dá ao GTIN o formato `22, 10, 21` com todos os qualificadores opcionais,
então 01+10+21 e 01+22+10+21 podem ser cadastrados (o ITIP também, com 10+21). A API de cadastro aceita
quaisquer qualificadores (F11). A regra 1 (01+235 sozinho) já é aplicada pelo formato `235`. Lado: cadastro.
**Ação: item 1.2.** A instalação de homologação não tinha nenhum registro de série com lote ou variante
(verificado em 1º de outubro de 2026), então o 1.2 não precisa de ferramenta de migração: recusa a combinação
em todas as entradas (formulário, importação de planilha, API) e lista os registros desse tipo já gravados,
para instalações com dados anteriores à regra. *Corrigido em `61babe1` e `83d1ba0`, com o desenho escolhido
pelo responsável: lote e variante de uma série ficam guardados no cadastro dela como informação
(`informativeQualifiers`), e continuam podendo ser buscados, filtrados, exportados e impressos.*

### F3 — O link padrão leva título e nada mais (Resolver 2.5.8) — conforme

`_author_db_linkset_document()` em `data_entry_server/src/data_entry_logic.py` grava
`https://gs1.org/voc/defaultLink` só como `{"href", "title"}`; `_public_link()` e
`format_linkset_for_external_use()` em `web_server/src/web_logic.py` o publicam sem mudança. O portal nunca
envia título vazio: um título em branco vira o título do tipo de link no vocabulário (`build_document()` em
`portal/app.py`). Qual link vira o padrão é outro problema: ver F9.

### <a id="f4"></a>F4 — O linkset da consulta é a união dos cadastros correspondentes (Resolver 2.5.9, regra 4) — conforme; escolha do redirecionamento corrigida

`read_document()` reúne toda entrada cujos qualificadores estão todos presentes na requisição
(`_entry_applies()`), da mais específica para a menos, e o linkset as junta, cada nível com sua própria
âncora. Esse conjunto contém os seis conjuntos da regra 4 e, além deles, entradas como 01+10+21 — que a regra
2 proíbe cadastrar. Corrigido o F2, os dois conjuntos ficam iguais. A correspondência é literal: uma entrada
01+22+10 não volta numa requisição sem a CPV, como diz o padrão. **Ação: o item 1.2 acrescenta um teste com
os seis conjuntos.**

*Correção encontrada ao implementar o item 1.2:* o linkset estava certo, mas o redirecionamento não. A
entrada mais específica era a de mais qualificadores, então com cadastros 01+10 e 01+21 uma requisição
`/10/B42/21/S1` (os dois se aplicam, com um qualificador cada) podia ser redirecionada com o link do lote. A
regra 4 lista 01+21 primeiro, e uma série identifica uma unidade. Desde `61babe1` um cadastro com AI 21 ou
AI 235 vem antes de qualquer cadastro de lote ou variante (teste "informative qualifiers: … → u-serial" em
`test_resolver.py`).

### F5 — Subir na hierarquia sem redirecionamento HTTP (Resolver 2.5.9) — conforme

Os níveis são resolvidos dentro de uma única requisição; não há redirecionamento para uma URI menos granular.

### <a id="f6"></a>F6 — Strings EPC binary não são descomprimidas (Resolver 2.3) — não conforme

> A GS1-Conformant resolver SHALL decompress EPC binary strings [EPCB].

Caminhos de um só segmento vão para `uncompress_gs1_digital_link()`, que chama `GS1DigitalLinkToolkit.js`.
O toolkit só implementa o algoritmo de compressão legado do GS1 Digital Link 1.1 (opcional desde o Resolver
1.2.0) e nada do padrão de EPC binary: as strings `/eh…` e `/ex…` são lidas como compressão legada e
recusadas ("No optimisation defined for hex code…"). A recusa produz então **500** (ver F15). Lado: consulta.
**Ação: novo item 1.6.**

### F7 — Arquivo de descrição do Resolver (Resolver 3) — parcial

O arquivo é servido em `/.well-known/gs1resolver`, valida no schema oficial (teste "description: validates
against the official description file schema"), pega a raiz e o operador do ambiente e declara o contexto
JSON-LD. Mas:

- `"supportedPrimaryKeys": ["all"]` promete todos os qualificadores de todas as chaves (2.1, 2.5.9), o que
  não vale para EPC binary (F6) nem para ITIP com CPV (F20);
- `"validatesAIcombinations": true` (propriedade do arquivo legado) não é verdade enquanto o F10 existir;
- o campo interno `"_id"` é publicado;
- `"termsOfUse"` aponta para uma página da GS1 em toda instalação, enquanto os dados do operador vêm do
  `.env` de cada instalação.

Lado: descrição. **Ação: item 1.5** (tirar `_id`, tornar `termsOfUse` configurável ou retirá-lo, manter
`validatesAIcombinations` verdadeiro só depois de corrigido o F10); o `"all"` passa a ser verdade com o 1.6.

### F8 — URIs dos rótulos do portal (URI Syntax 4) — conforme

`gs1.digital_link()` e `syntax.digital_link()` montam a URI do rótulo com valores validados: GTIN com 14
dígitos, qualificadores na ordem do caminho (`KEY_SHAPES`), valores com percent-encoding
(`quote(v, safe='')`), atributos de dados colocados na query string pelo GS1 Barcode Syntax Engine, sem barra
final e com o radical do operador (`RESOLVER_PUBLIC_URL`). Quando o 1.2 restringir o que um registro pode
cadastrar, a URI do QR code e o cadastro passam a ser coisas diferentes; o 1.2 deixa a primeira livre
(qualquer URI válida).

### <a id="f9"></a>F9 — A resposta padrão nem sempre é o link padrão (Resolver 2.6.1, 2.5.8) — não conforme

> Resolvers SHALL redirect to the default link unless there is information in the request that can be used
> to determine a better response.

Sem `linkType`, `_handle_link_type()` não usa o `gs1:defaultLink` gravado: pega todos os links do
`defaultLinktype` da chave e compara os idiomas com `Accept-Language`. Quando nada corresponde e há dois ou
mais desses links, o último recurso de `_get_appropriate_linktype_docs_list()` devolve todos e o Resolver
responde **300** com uma lista em JSON — também para navegadores. Exemplo: `gs1:pip` em inglês e em francês,
requisição sem `Accept-Language` ou com `de` → 300; os exemplos 5 e 7 do padrão esperam redirecionamento para
o padrão. Os registros do portal sempre têm idioma, então todo registro com dois idiomas no tipo padrão é
afetado.

Dois defeitos relacionados:

- o `defaultLink` gravado é o **último** link do tipo padrão (o laço de `_author_db_linkset_document()` o
  sobrescreve), enquanto o portal diz ao usuário que o primeiro link é o padrão;
- escolher entre os links do tipo padrão pelo idioma é o comportamento de `gs1:defaultLinkMulti`, e o 2.5.8
  diz que, se o recurso existe, "the link types for these links SHALL include gs1:defaultLinkMulti". Esses
  links só recebem esse tipo quando um único link lista dois idiomas, e mesmo assim sob a chave
  `defaultLinkMulti` (que não é uma URI), descartada por `format_linkset_for_external_use()`.

Lado: consulta e cadastro. **Ação: item 1.5** — sem `linkType`: melhor correspondência de idioma entre links
`gs1:defaultLinkMulti` explícitos, senão 307 para o `gs1:defaultLink`; o link padrão é o primeiro do tipo
padrão; `defaultLinkMulti` gravado sob a sua URI e publicado.

### <a id="f10"></a>F10 — Os caminhos das requisições não são validados como URIs GS1 Digital Link (Resolver 2.4, 2.4.1; URI Syntax 4.9, 4.10) — parcial

`_test_gs1_digital_link_syntax()` transforma o caminho numa element string e pede ao motor que a aceite. Uma
element string não tem ordem de caminho e admite atributos de dados, então estas requisições são
redirecionadas (307) para o padrão da chave em vez de recusadas:

| Caminho | Problema | Resposta |
|---|---|---|
| `/01/{gtin}/21/S1/10/L1` | qualificadores fora de ordem (4.9) | 307 |
| `/01/{gtin}/17/261231` | atributo de dados no caminho (4.10: atributos SHALL ficar na query string) | 307 |
| `/01/{gtin}/99/ABC` | um AI que não é qualificador da chave | 307 |

O mesmo motor, recebendo a própria URI (`dataStr`, o seu parser de GS1 Digital Link), recusa as três ("The
AIs in the path are not a valid key-qualifier sequence for the key") e também faz os testes 4 e 5 do 2.4
(chave primária, qualificadores válidos para a chave). Ele aceita `%2F` num valor e recusa barra final, então
a barra precisa ser retirada antes (2.13). Lado: consulta. **Ação: item 1.5.**

### F11 — A API de cadastro grava sem validar o identificador (Resolver 2.4) — parcial

> it SHOULD be impossible to register a link against an invalid GS1 identifier or set of identifiers.

O portal valida toda chave e qualificador (`gs1.py`, comparado com o motor por `test_keys.py`). A API de
cadastro — código oficial — não valida nada: `_test_gs1_digital_link_syntax()` existe em
`data_entry_logic.py` mas nunca é chamada, e `_validate_data()` é um gancho vazio. A API exige o token, que
só o portal tem, então o risco se limita a quem usa a API diretamente. Lado: cadastro. **Ação: item 1.2** (a
API aplica as mesmas regras do portal, incluindo os conjuntos de cadastro do 2.5.9). *Corrigido em parte em
`61babe1`: estrutura e regras do 2.5.9; a API não confere os valores, para que modelos como `{lotnumber}`
continuem funcionando.*

### F12 — `%2F` num valor quebra a resolução (Resolver 2.4.1) — parcial

`/` faz parte do conjunto de 82 caracteres e se escreve `%2F` numa URI (4.2). O
`proxy_pass http://web-service:4000/api/;` do proxy repassa o caminho *decodificado* (verificado no nginx
1.24: `/10/A%2FB` chega como `/10/A/B`), e o Werkzeug também decodifica o `PATH_INFO`. A requisição fica com
número ímpar de segmentos e responde 400, embora a URI seja válida. O portal não deixa `/` entrar nos valores
cadastrados, então só a subida na hierarquia a partir desses lotes ou séries é afetada. Lado: consulta,
implantação. **Ação: item 1.5** (repassar a URI original pelo proxy e lê-la no servidor web).

### F13 — A query string é remontada, não repassada (Resolver 2.12) — parcial

`_extract_query_strings()` decodifica a query string e a codifica de novo com `urlencode()`. O separador `;`,
que a URI Syntax permite (`queryStringDelim`, 4.11), não é entendido: `?17=261231;3103=000189` chega ao
destino como `?17=261231%3B3103%3D000189`; uma chave sem valor (`?flag`) vira `?flag=`. Lado: consulta.
**Ação: item 1.5** (acrescentar a query string original).

### F14 — Desligar o repasse da query string por link (Resolver 2.12) — não conforme quando usado; opção a retirar

> When redirecting, by default, a resolver SHALL transmit the entirety of the query string in the request
> URI to the target destination.

e, no changelog da release 1.2.0: "The option to omit incoming query string parameters when redirecting to a
target URL has been removed." O portal oferece *Repassar os parâmetros do endereço para este destino* em
cada link (gravado como `"fwqs": false`, respeitado em `_process_response()`), e as colunas de importação e
exportação o levam. O repasse é o padrão, então só os registros em que alguém desmarcou a opção são
afetados. O atributo `fwqs` continua no schema oficial do linkset da GS1, por isso se propõe a errata E3.
Lado: cadastro, consulta. **Ação: item 1.5**, conforme decisão do mantenedor em 1º de outubro de 2026: a
opção sai do editor de links e da importação e exportação de planilhas, e o Resolver ignora `fwqs: false` nos
registros que já o têm, de modo que todo redirecionamento repasse a query string.

### F15 — Caminhos de um segmento não reconhecidos respondem 500 (Resolver 2.4.1) — parcial

Quando o toolkit recusa um caminho de um só segmento (`/foo`, uma string EPC binary), ele termina com erro e
`uncompress_gs1_digital_link()` devolve um dicionário sem `SUCCESS`; `_handle_request()` em
`web_namespace.py` então gera `KeyError` e responde 500. Uma requisição que não é URI GS1 Digital Link
válida deveria receber 400 (2.4.1). Não é um 200, então o item 9 da declaração de conformidade é atendido.
Lado: consulta. **Ação: item 1.5** (com o 1.6 para EPC binary).

### F16 — O corpo do 300 Multiple Choices não é um linkset (Resolver 2.6.3, 2.10) — parcial

O status está certo, mas o corpo é `{"linkset": [ …links… ]}`: os links sem âncora e sem o tipo de link, o
que não é um linkset RFC 9264 válido, e em JSON também quando o navegador pediu HTML. Lado: consulta.
**Ação: item 1.5** (um linkset de verdade com os links candidatos e a página HTML para navegadores).

### F17 — Linkset em HTML sem JSON-LD embutido; JSON quando nenhum tipo é pedido (Resolver 2.10) — parcial

O 2.10 diz que, para `text/html` "or unspecified", o Resolver SHOULD devolver uma página HTML e SHOULD
embutir nela o linkset em JSON-LD. A página HTML (`web_pages.render_linkset()`) não tem JSON-LD; uma
requisição sem cabeçalho `Accept` recebe JSON (decisão desde `766a652`, para que ferramentas como o `curl`
continuem recebendo JSON). Lado: consulta. **Ação: item 1.5** (embutir o JSON-LD; manter JSON para
requisições sem `Accept` e documentar a escolha).

### F18 — Um link sem tipo de mídia pode causar 400 (Resolver 2.4.1) — parcial

`_match_media_type()` avalia `'und' in linktype_doc['type']`; num link criado pela API sem `type` o valor é
`None` e o `TypeError` vira 400 para uma requisição válida (por exemplo, `linkType` informado e
`Accept-Language` sem correspondência). O portal sempre grava um tipo de mídia (`gs1.guess_media_type()`),
então só links criados pela API são afetados. Lado: consulta. **Ação: item 1.5.**

### F19 — Os idiomas são comparados literalmente (Resolver 2.6.3) — parcial

`Accept-Language: pt-BR` não encontra um link em `pt` a menos que o navegador também envie `pt`; os valores
q são descartados em vez de usados para ordenar. O 2.6.3 pede a correspondência mais próxima possível. Lado:
consulta. **Ação: item 1.5**, junto com o F9 (busca BCP 47: `pt-BR` → `pt`).

### <a id="f20"></a>F20 — ITIP com Consumer Product Variant (URI Syntax 4.9; Resolver 2.5.10) — conflito entre padrões

O `itip-path` do 4.9 permite `/8006/{itip}/22/{cpv}`, e o 2.5.10 do padrão do Resolver lista a CPV entre os
qualificadores do ITIP. O GS1 Barcode Syntax Engine, seguindo o Syntax Dictionary, recusa: "Required AIs for
AI (22) are not satisfied: 01". O Resolver responde então 400, e o portal não oferece 22 para ITIP (decisão
de `67d40bb`). O comportamento segue as GS1 General Specifications; os padrões é que discordam entre si.
**Ação: errata E2** (item 8.1); nenhuma mudança de código.

### F21 — Títulos padrão em inglês (Resolver 2.5.3) — parcial

Um título em branco vira o título do vocabulário em inglês (`LINK_TYPE_DEFAULT_TITLES`), qualquer que seja o
idioma do link; o 2.5.3 diz que o título SHOULD estar no idioma do destino. Lado: cadastro. **Ação: item
7.3** (títulos padrão no idioma do link quando o portal os conhece).

### F22 — Namespace `gs1:` escrito como `https://gs1.org/voc/` (Resolver 2.14) — a verificar

O 2.14 define `gs1:` como `https://ref.gs1.org/voc/`; os linksets usam chaves `https://gs1.org/voc/…`
(código oficial), enquanto o arquivo de descrição declara `https://ref.gs1.org/voc/`. Os dois endereços levam
ao vocabulário e o schema oficial aceita qualquer um. Não se sabe se a suíte de testes da GS1 ou os clientes
comparam as strings. **Ação: item 1.4** (conferir com a suíte); se preciso, item 1.5.

### F23 — Tags de idioma que o schema do linkset recusa (Resolver 2.5.4, 2.10) — parcial

Desde `7339e3c` o portal aceita qualquer tag BCP 47, como exige o 2.5.4. O schema oficial do linkset, no qual
o linkset SHALL validar, só aceita `ll` ou `ll-CC` (`(^\w{2}$)|(^\w{2}-\w{2}$)`): um link em `es-419`,
`zh-Hant` ou `fil` torna o linkset inválido. Lado: consulta, cadastro. **Ação: errata E4**; enquanto isso, o
item 1.5 decide se o portal avisa sobre essas tags.

## 4. GS1-Conformant Resolver 1.2.1, cláusula a cláusula

Os números na primeira coluna remetem à declaração de conformidade (seção 5 do padrão) quando o requisito
aparece lá.

| Cláusula | Requisito (resumo) | Lado | Situação | Evidência | Ação |
|---|---|---|---|---|---|
| 2.1, 2.5.9; §5.1 | Para cada chave suportada, todo qualificador SHALL ser suportado | Consulta | Parcial | toda chave e caminho qualificado resolve (`test_resolver.py`, "resolves …" com o motor real); ITIP+CPV recusado | F20 |
| 2.2; §5.2 | HTTP 1.1 GET, HEAD e OPTIONS | Consulta | Conforme | `web_namespace.py`; HEAD responde 307 sem corpo; OPTIONS responde `Allow: GET, HEAD, OPTIONS` | — |
| 2.2; §5.3 | HTTP sobre TLS | Implantação | Conforme | o instalador configura o nginx do host com Certbot ou certificado (`scripts/install.sh`, `TLS_MODE`); a pilha Compose escuta em 127.0.0.1 | — |
| 2.2; §5.4 | CORS | Consulta | Conforme | `flask_cors.CORS(app)` e `add_headers()`; preflight respondido; `Link` e `Location` expostos (teste "CORS exposes Link") | — |
| 2.2 (3b) | Redirecionar para o padrão salvo indicação em contrário | Consulta | Não conforme | ver F9 | 1.5 |
| 2.2 (3c), 2.9 | `linkType=linkset` ou `Accept: application/linkset+json` → sem redirecionamento, linkset | Consulta | Conforme | `_get_request_parameters()`; testes "linkset …" | — |
| 2.3; §5.5 | Descomprimir strings EPC binary | Consulta | Não conforme | F6 | 1.6 |
| 2.3 | MAY implementar a descompressão legada | Consulta | Conforme | `uncompress_gs1_digital_link()` (toolkit oficial) | — |
| 2.3; §5.10 | Âncoras do linkset com a URI descomprimida | Consulta | Conforme | `DocOperationsNonGS1DigitalLinkRequest` resolve os identificadores descomprimidos | — |
| 2.3; §5.6 | Redirecionar a URI descomprimida para outro Resolver | Consulta | Não se aplica | não há redirecionamento para outros Resolvers | — |
| 2.4 | SHOULD ser impossível cadastrar link para identificador inválido | Cadastro | Parcial | portal: `gs1.normalise_key()`, `normalise_qualifiers()`, `test_keys.py`; API: sem validação | F11 → 1.2 |
| 2.4, testes 1–3 | Validação básica (estrutura, tamanho dos AIs, conjuntos de caracteres, dígitos verificadores, duplicados) | Consulta | Parcial | element string conferida pelo motor (`_test_gs1_digital_link_syntax()`; testes "wrong SSCC check digit…"); estrutura do caminho não conferida | F10 |
| 2.4, testes 4–5 | MAY conferir chave primária e qualificadores válidos para a chave | Consulta | Não implementado | — | F10 (vem com a correção) |
| 2.4.1; §5.7 | SHALL responder 400 quando a requisição falha nos testes | Consulta | Parcial | 400 para dígitos verificadores e combinações recusadas; 307 para os caminhos do F10; 400 para caminhos válidos com `%2F` (F12); 500 para segmentos únicos (F15) | 1.5 |
| 2.4.1; §5.8 | URI válida, nada conhecido → 404 simples | Consulta | Conforme | GTIN desconhecido → 404 | — |
| 2.4.1; §5.9 | Nenhum 200 para condição de erro | Consulta | Conforme | páginas de erro HTML mantêm o status (`render_error()`); erros são 4xx/5xx | — |
| 2.5.1 | A URL de destino SHALL ser informada | Cadastro | Conforme | `gs1.normalise_url()`; o modelo da API exige `href` | — |
| 2.5.1 | Modelos MAY ser suportados; SHOULD NOT usar a query string | Consulta | Conforme | os modelos oficiais `{0}`/`{1}` e de qualificadores usam só valores do caminho | — |
| 2.5.2 | Links SHALL ter tipo de link, SHOULD do vocabulário GS1 | Cadastro | Conforme | `gs1.LINK_TYPES` (só vocabulário GS1) | — |
| 2.5.3; §5.11 | Um título SHALL ser informado | Cadastro | Conforme | título em branco → título do vocabulário (`build_document()`); o schema do linkset exige `title` | — |
| 2.5.3 | O título SHOULD estar no idioma do destino | Cadastro | Parcial | títulos padrão em inglês | F21 → 7.3 |
| 2.5.4 | Tags de idioma SHALL seguir BCP 47, num array | Cadastro, consulta | Parcial | `gs1.normalise_language()`; arrays no linkset; o schema recusa tags válidas | F23 |
| 2.5.5; §5.11 | Tipos de mídia SHALL ser tipos IANA | Cadastro | Conforme | `gs1.guess_media_type()` (tipos IANA pela extensão) | — |
| 2.5.6 | Valores de contexto SHOULD ser declarados no arquivo de descrição | Descrição | Conforme | `supportedContextValuesExternal` (ISO 3166) | — |
| 2.5.8; §5.14 | Exatamente um link padrão por entidade, só com título | Cadastro | Conforme | F3 | — |
| 2.5.8 | Links `gs1:defaultLinkMulti` SHALL ter esse tipo se o recurso existe | Consulta, cadastro | Não conforme | F9 | 1.5 |
| 2.5.8; §5.12 | Links padrão SHALL ter também um tipo descritivo | Cadastro | Conforme | o `href` do padrão também aparece sob o seu tipo de link | — |
| 2.5.9; §5.16 | Um link padrão no nível de entrada ou acima para qualquer URI | Cadastro | Não conforme | F1 | 1.3 |
| 2.5.9; §5.22 | As chaves primárias suportadas SHALL ser declaradas no arquivo de descrição | Descrição | Conforme | `"supportedPrimaryKeys": ["all"]` (mas ver F7) | — |
| 2.5.9 | SHOULD NOT redirecionar para subir na hierarquia | Consulta | Conforme | F5 | — |
| 2.5.9 regra 1 | 01+235: nenhum outro AI | Cadastro | Conforme | formato `235` em `KEY_SHAPES`; o motor recusa UPUI com lote (teste) | — |
| 2.5.9 regra 2; §5.23 | 01/8006 + 21: sem 22 nem 10 | Cadastro | Não conforme | F2 | 1.2 |
| 2.5.9 regra 3 | Sem 235 nem 21: 22 e/ou 10 permitidos | Cadastro | Conforme | `KEY_SHAPES` | — |
| 2.5.9 regra 4 | O linkset da consulta SHALL ser a união de seis conjuntos | Consulta | Conforme | F4 | teste no 1.2 |
| 2.6.2; §5.17 | Tipo de link pedido disponível → redirecionar | Consulta | Conforme | testes "redirection …", inclusive níveis herdados | — |
| 2.6.2; §5.18 | Tipo de link pedido ausente → 404 (MAY listar os links) | Consulta | Conforme | 404 com os links disponíveis na página HTML (teste "HTML 404 page …") | — |
| 2.6.3; §5.20 | SHOULD usar `Accept-Language`, MAY usar `Accept` e `context` | Consulta | Parcial | `_get_appropriate_linktype_docs_list()`; comparação literal de idioma | F19 |
| 2.6.3 (7) | Escolha indecidível → 300 com os links | Consulta | Parcial | status certo, corpo não é linkset | F16 |
| 2.8 | Redirecionamento por padrão MAY; o rel SHALL ser `gs1:handledBy` se exposto | Consulta | Não se aplica | não implementado | — |
| 2.10 | `application/linkset+json` → JSON RFC 9264; SHALL validar no schema do linkset | Consulta | Conforme | os testes validam todo linkset no schema oficial (exceto as tags do F23) | — |
| 2.10 | Mesma resposta RECOMMENDED para `application/json` | Consulta | Conforme | `_process_response()` | — |
| 2.10; §5.13 | Cabeçalho Link para o contexto JSON-LD SHOULD; arquivo de contexto SHOULD ser declarado | Consulta, descrição | Conforme | `JSON_LD_CONTEXT` em toda resposta de linkset; `jsonLdContextLocation` | — |
| 2.10 | `application/ld+json` SHOULD embutir o contexto | Consulta | Conforme | teste "JSON-LD on request" | — |
| 2.10 | HTML SHOULD ser devolvido para `text/html` ou sem tipo, com JSON-LD embutido | Consulta | Parcial | página HTML sem JSON-LD; JSON sem `Accept` | F17 |
| 2.11 | Tipo de link padrão `linkset`: MAY, SHOULD ser declarado | Descrição | Conforme | não suportado; `linkTypeDefaultCanBeLinkset: false` | — |
| 2.12; §5.19 | SHALL repassar a query string inteira ao redirecionar | Consulta | Parcial | repassada por padrão, mas remontada (F13) e desligável por link (F14) | 1.5 |
| 2.13; §5.25 | SHOULD tolerar barra final | Consulta | Conforme | `strict_slashes = False`; teste "trailing slash" | — |
| 2.14; §5.24 | SHALL reconhecer tipos de link `gs1:`; outros namespaces SHOULD ser declarados | Consulta | Conforme | `normalise_linktype()` aceita `gs1:`, `https://gs1.org/voc/` e `https://ref.gs1.org/voc/` | F22 |
| 2.14; §5.24 | Tipos de link de outras origens SHALL NOT duplicar os da GS1 | Cadastro | Conforme | só vocabulário GS1 | — |
| 3; §5.21 | Arquivo de descrição em `/.well-known/gs1resolver`, válido no schema | Descrição | Conforme | teste "description: validates …" | — |
| 3 | Conteúdo do arquivo de descrição | Descrição | Parcial | F7 | 1.5, 1.6 |
| 2.14 | URI do namespace `gs1:` | Consulta, descrição | A verificar | F22 | 1.4 |

## 5. GS1 Digital Link URI Syntax 1.7, cláusula a cláusula

Este padrão restringe as URIs que o portal grava nos rótulos (lado *rótulos*) e define o que o Resolver
precisa aceitar (lado *consulta*).

| Cláusula | Requisito (resumo) | Lado | Situação | Evidência | Ação |
|---|---|---|---|---|---|
| 2 | Aplicações SHALL NOT supor que uma URI GS1 Digital Link aponta para um Resolver | Cadastro | Conforme | a busca por código do portal interpreta URIs de qualquer domínio sem acessá-las | — |
| 4.1 | GTIN-8/12/13 SHALL ser escritos com 14 dígitos | Rótulos | Conforme | `gs1.normalise_gtin()` | — |
| 4.1 | Só a infraestrutura existente SHOULD continuar aceitando formas legadas | Consulta | Conforme | o Resolver completa um GTIN de 13 dígitos (comportamento oficial); inofensivo | — |
| 4.2 | Caracteres reservados com percent-encoding | Rótulos | Conforme | `quote(v, safe='')`; valores cadastrados limitados a letras, dígitos, `.`, `-`, `_` | — |
| 4.3–4.6 | Chaves primárias, qualificadores e formatos | Cadastro | Conforme | `PRIMARY_KEYS`, `QUALIFIER_FORMATS`, comparados com o motor (`test_keys.py`); conjunto de caracteres deliberadamente mais estreito (decisão 4) | — |
| 4.7–4.9 | Ordem do caminho e caminhos permitidos (inclusive UPUI, EOID, FID, MID; 415 exige 8020) | Rótulos | Conforme | `KEY_SHAPES`, `QUALIFIER_ORDER` | — |
| 4.9 | Ordem do caminho | Consulta | Parcial | não conferida nas requisições | F10 |
| 4.9 | `itip-path` com CPV | Consulta | A verificar | recusado pelo motor | F20, E2 |
| 4.10 | Atributos de dados SHALL ficar na query string | Rótulos | Conforme | `get_dl_uri()` do motor; o caminho tem de continuar sendo o do registro (`syntax.digital_link()`) | — |
| 4.10 | Atributos de dados SHALL ficar na query string | Consulta | Parcial | `/01/{gtin}/17/…` aceito | F10 |
| 4.10 | Um segundo identificador SHALL ser atributo de dados | Rótulos | Conforme | a lista de atributos é a do Syntax Dictionary (com as chaves), menos a chave e os qualificadores do próprio registro | — |
| 4.10.1 | Chaves de extensão SHALL NOT ser só numéricas; `linkType` e `context` reservados | Rótulos, consulta | Conforme | o portal não grava chaves de extensão; o Resolver usa as duas palavras como definido | — |
| 4.11 | `customURIstem` com segmentos opcionais | Rótulos | Conforme | `RESOLVER_PUBLIC_URL` | — |
| 4.11 | `customURIstem` com segmentos opcionais | Consulta | Não se aplica | o Resolver atende na raiz do domínio; um radical importa para o item 5.1 | 5.1 |
| 4.12 | Regras da URI canônica (HTTPS, `id.gs1.org`, chaves de AI ordenadas, sem barra final) | Rótulos | Não se aplica | o portal nunca apresenta uma URI como canônica | — |
| 6.1 | Um leitor SHALL repassar só URIs GS1 Digital Link plausíveis | — | Não se aplica | não há software de leitura no projeto | — |
| 6.2 | A HRI segue as GS1 General Specifications | Rótulos | Não se aplica | conferir quando os rótulos com EAN/UPC forem desenhados | 5.3 |

## 6. Candidatos a errata e Work Requests

Para o item 8.1. Cada um foi conferido no texto dos padrões nesta revisão.

| # | Documento | Problema | Proposta |
|---|---|---|---|
| E1 | URI Syntax 1.7, 4.10 | A lista de parâmetros da query string cita `shipToaAdd1Parameter` e `shipToaAdd2Parameter`; as regras se chamam `shipToAdd1Parameter` e `shipToAdd2Parameter` (AIs 4302, 4303). | Corrigir os nomes na lista. |
| E2 | URI Syntax 1.7, 4.9; Resolver 1.2.1, 2.5.10 | `itip-path` permite `/22/` depois de um ITIP e o 2.5.10 lista a CPV entre os qualificadores do ITIP, mas o GS1 Syntax Dictionary faz o AI 22 exigir o AI 01, e o GS1 Barcode Syntax Engine recusa `(8006)…(22)…`. | Retirar `[cpv-comp]` do `itip-path` (e a CPV do 2.5.10 para ITIP), ou admitir 8006 na exigência do AI 22. |
| E3 | Resolver 1.2.1, 2.12 e changelog 7.2; schema do linkset | A opção de não repassar a query string foi removida na 1.2.0, mas o schema normativo do linkset ainda define `fwqs`. | Retirar `fwqs` do schema ou definir o seu significado (por exemplo, apenas informativo). |
| E4 | Schema do linkset; Resolver 2.5.4 | `hreflang` precisa casar com `(^\w{2}$)|(^\w{2}-\w{2}$)`, o que recusa tags BCP 47 válidas (`es-419`, `zh-Hant`, `fil`, `sr-Latn-RS`); os padrões de `anchor` e `href` usam a faixa `A-z`, que também admite `[`, `\`, `]`, `^`, `_` e `` ` ``. | Aceitar tags BCP 47 (por exemplo, o padrão da RFC 5646 ou um mais frouxo); usar `A-Za-z`. |
| E5 | Resolver 1.2.1, seção 3, exemplo | O arquivo de descrição de exemplo não é JSON válido: `},` sobrando antes de `jsonLdContextLocation`, a URL sem aspas e `hasTelepone` em vez de `hasTelephone`. | Corrigir o exemplo. |
| E6 | Resolver 1.2.1, seção 5 e 2.7 | Os itens 7 e 9 da declaração de conformidade remetem à "section 0"; o exemplo 3 escreve `gs1:smp` em vez de `gs1:smpc` e ainda usa o obsoleto `all`. | Correções editoriais. |
| E7 | Resolver 1.2.1, 2.5.9 | O SHALL de um link padrão "at the entry level or higher" recai sobre os dados, mas o padrão não orienta o lado do cadastro (recusar, avisar ou criar o registro do nível acima). | Orientação informativa para ferramentas de cadastro (o que o 1.3 implementa). |

Acrescentados depois da revisão, durante o item 1.6 (cada um conferido decodificando os bits):

| # | Documento | Problema | Proposta |
|---|---|---|---|
| E8 | EPCB 1.0.0, 4.2.2 | A opção B manda acrescentar os caracteres base 64 a 'eh' (é 'ex'), e o passo 2 da decodificação fala em 6 bits por caractere "hexadecimal" (são caracteres base 64). | Correções editoriais. |
| E9 | TDS 2.3, anexo E.3 | Os exemplos de SSCC++ e ITIP++ começam com os cabeçalhos F9 e F3, de SSCC+ e ITIP+; com EF e ED (Tabela 14-1) os mesmos bits dão as URIs mostradas. Os exemplos de SGTIN++ e DSGTIN++ mostram o hostname example.com, mas os bits codificam id.example.com, como todos os outros exemplos `++`. A EPC URI do exemplo de SGTIN-96 termina em `1234567896789`; o número de série é `123456789`. | Corrigir os cabeçalhos, as duas URIs e a EPC URI. |
| E10 | TDS 2.3, Tabelas 14-14 e 14-15 | Na Tabela 14-14 (B3), as linhas `.org.cn` e `.net.cn` trazem o prefixo `0000000`, da Tabela B1, em vez de `0000010`; a legenda da Tabela 14-15 (B4) diz que os valores começam com `0000010`, mas começam com `0000011`. | Corrigir os prefixos e a legenda. |
| E11 | Artefato do TDT 2.2 `CPI-var.json` (rascunho de 18/11/2024) | A gramática do nível GS1_AI_JSON cita um campo `serial`; o campo é `cpiserial` (o nível GS1_DIGITAL_LINK está certo). | Corrigir o artefato antes da publicação. |

Acrescentado durante o item 1.4, a partir da suíte de testes da GS1 (seção 8):

| # | Documento | Problema | Proposta |
|---|---|---|---|
| E12 | Resolver 1.2.1, 2.5.8, 2.5.9, 2.6.3; suíte de testes de Resolver da GS1 | Quando um nível qualificado (um lote) tem link padrão próprio e um nível acima (o GTIN) tem links `gs1:defaultLinkMulti`, o padrão não diz se essas variantes valem para uma requisição no nível qualificado. A suíte da GS1 trata `gs1:defaultLinkMulti` como qualquer tipo de link herdado e espera que a URI do lote com `Accept-Language` correspondente vá para a variante do GTIN, passando por cima do link padrão do próprio lote. O 2.5.8 dá a cada entidade identificada exatamente um link padrão, do qual as variantes são refinamentos. | Dizer que o link padrão e as suas variantes `gs1:defaultLinkMulti` vêm do mesmo nível: o mais granular que tem link padrão. Alinhar a suíte de testes (uma issue no repositório dela, item 8.2). |

A questão do namespace (F22) não virou errata: a suíte de testes aceita as duas formas. O próprio padrão é
um pouco inconsistente — o 2.14 expande `gs1:` para `https://ref.gs1.org/voc/`, enquanto a referência
\[GS1Voc\] traz `https://gs1.org/voc/` —, mas a referência indica o endereço do vocabulário, não o
namespace.

## 7. Efeito no backlog

| Item | Mudança |
|---|---|
| 1.2 Modelo de cadastro do 2.5.9 | Também: a API de cadastro valida chaves e qualificadores com as mesmas regras do portal (F11); um teste com os seis conjuntos da regra 4 (F4); sem ferramenta de migração (ver F2). Corrige o F2. |
| 1.3 Link padrão num nível acima | Sem mudança; corrige o F1. |
| **1.5 Correções de resolução (novo, M)** | F9 resposta padrão e `defaultLinkMulti`; F10 caminho validado pelo parser de GS1 Digital Link do motor; F12 URI original pelo proxy e pelo servidor web; F13 query string original; F14 retirada da opção por link; F15 400 em vez de 500; F16 300 como linkset (e HTML); F17 JSON-LD na página HTML; F18 links sem tipo de mídia; F19 busca BCP 47; F7 limpeza do arquivo de descrição; decisão do F23. Depende do 1.2 (mesmos registros e testes). |
| **1.6 Descompressão de EPC binary (novo, M–L)** | F6 e o restante do F7. Implementação a escolher quando o item começar (GS1 Digital Link URI: Compression Technical Standard for EPC binary strings 1.0.0, Tag Data Standard / Tag Data Translation); o 500 para segmentos não reconhecidos é corrigido no 1.5. |
| 1.4 Suíte de testes de conformidade da GS1 | Roda depois do 1.5 e do 1.6, para que o registro mostre o Resolver corrigido; resolve também o F22. |
| 7.3 Acabamento | F21 (títulos padrão no idioma do link). |
| 8.1 Work Requests / erratas | E1–E7 (seção 6); E8–E11 acrescentados no item 1.6; E12 no item 1.4. |

Ordem proposta da fase 1: 1.2 → 1.3 → 1.5 → 1.6 → 1.4.

## 8. Como reproduzir as verificações

**Num ambiente de desenvolvimento** (ver [`dev-tests/README.md`](../../dev-tests/README.md)): a estrutura no
início de `dev-tests/resolver/test_resolver.py` cria documentos com o código real da API de cadastro e os
resolve com o servidor web real; com `GS1_SYNTAX_ENGINE` definido, a conferência de sintaxe do Resolver é o
motor real. Os casos desta revisão são as requisições citadas nos achados acima, com um registro que tenha
`gs1:pip` em dois idiomas para o F9.

**O motor como parser de GS1 Digital Link** (F10, F20), com o pacote npm `gs1encoder` 1.4.1:

```js
import {GS1encoder} from "gs1encoder";
const g = new GS1encoder(); await g.init();
g.dataStr = "https://example.org/01/09506000134352/21/S1/10/L1";   // erro: sequência de qualificadores inválida
```

**O proxy** (F12): qualquer nginx com `location / { proxy_pass http://127.0.0.1:4000/api/; }` na frente de
um servidor que imprima o caminho recebido mostra `/10/A%2FB` chegando como `/10/A/B`.

**Numa instalação**, trocando os valores de `R` (o endereço do Resolver) e `G` (um GTIN cadastrado, com 14
dígitos, sem chaves). As respostas esperadas nas linhas do F10 supõem um GTIN cuja própria requisição
redireciona; para um GTIN afetado pelo F9 elas também dão 300, o que ainda mostra que o caminho não foi
recusado. Cada linha imprime o status e o cabeçalho `Location`.

```bash
R=https://resolver.example; G=09506000134352
show() { curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' "$@"; }
show -H 'Accept-Language: de' "$R/01/$G"            # F9:  300 hoje; esperado 307 para o link padrão
show "$R/01/$G/17/261231"                            # F10: 307 hoje; esperado 400
show "$R/01/$G/21/S1/10/L1"                          # F10: 307 hoje; esperado 400
show "$R/01/$G/10/A%2FB"                             # F12: 400 hoje; esperado 307 (sobe até o GTIN)
show "$R/01/$G?17=261231;3103=000189"                # F13: hoje o Location termina em %3B3103%3D000189
show "$R/eh3074257bf7194e4000001a85"                 # F6, F15: 500 hoje
```

Resultados na instalação de homologação (1º de outubro de 2026), com um GTIN cujo tipo de link padrão tem
links em mais de um idioma:

| Linha | Resposta | Leitura |
|---|---|---|
| F9, `Accept-Language: de` | 300 | F9 confirmado |
| F10, `/17/261231` | 300 | não recusado: o caminho subiu até o GTIN e caiu no F9 — F10 confirmado |
| F10, `/21/S1/10/L1` | 300 | o mesmo — F10 confirmado |
| F12, `/10/A%2FB` | 400 | F12 confirmado passando pelo nginx do host e pelo proxy |
| F13, `?17=…;3103=…` | 300 | de novo o F9; sem redirecionamento não se vê a query string repassada (o F13 se apoia na verificação do ambiente de desenvolvimento) |
| F6, F15, `/eh…` | 500 | F6 e F15 confirmados |

As linhas do F10 e do F13 também responderam 300 sem nenhum cabeçalho `Accept-Language`, ou seja, o exemplo
5 do padrão (sem informação de idioma → link padrão) falha do mesmo jeito que o exemplo 7.

Resultados na instalação de homologação depois dos itens 1.5 e 1.6 (2 de outubro de 2026, em `4b9a7be`,
pelo proxy):

| Requisição | Resposta | Leitura |
|---|---|---|
| `/01/{G}` | 307 para o link padrão do GTIN | a resolução pelo proxy voltou a funcionar (`b9a7631`) |
| SGTIN-96 de G, série 1001, como `eh…` e como `ex…` | 307, mesmo destino | F6 corrigido; as duas formas dão `/01/{G}/21/1001` |
| SGTIN+ de G com +AIDC (10) 123 e (17) 261231 | 307 para o destino do cadastro do lote, com `?17=261231` | qualificador no caminho, atributo de dados repassado |
| GID-96 (`/eh3500e86f8000a9e000000586`) | 400, "GID-96 has no GS1 Digital Link equivalent" | comportamento do F15 para cadeias que não decodificam |

### Resultados da suíte de testes da GS1 (item 1.4)

A suíte da GS1 (https://ref.gs1.org/test-suites/resolver/, para o Resolver 1.2.1; código em
[GS1DL-resolver-testsuite](https://github.com/gs1/GS1DL-resolver-testsuite) `32597c1`, 7 de agosto de 2026)
recebe uma URI GS1 Digital Link e deriva dela, e do linkset que o Resolver devolve, todas as requisições:

- a URI seguida de `/foo` (espera 400), de `/10/KL8G` ou `/254/KL8G` (subida na hierarquia: qualquer coisa
  menos 404), de uma barra final (mesma resposta) e com `?foo=bar` (repassado);
- o linkset por `?linkType=linkset` e por `Accept: application/linkset+json` (200, válido no schema do
  linkset, cabeçalho `Link` do contexto JSON-LD, tipo de conteúdo); a âncora precisa ser igual à URI;
- a URI sozinha (307 para o `href` do `gs1:defaultLink`); `?linkType=` com cada tipo de link do linkset,
  com `Accept` e `Accept-Language` tirados do tipo e do idioma de cada link quando um tipo tem vários links
  (espera 300 para links que ela não consegue distinguir); `?linkType=gs1:nosuchlt` (404);
- OPTIONS para o CORS e os métodos; o arquivo de descrição, buscado pelo próprio navegador e validado no
  schema publicado; os tipos de link comparados com a lista ratificada.

A maior parte das requisições é feita pelo auxiliar PHP da GS1 (HEAD, `Accept: */*`, sem
`Accept-Language`). A suíte não testa compressão; o item 1.6 se apoia nos seus próprios testes e nas
verificações de homologação acima.

**Homologação, 2 de outubro de 2026**, em `ef96276` (antes do `bc573c4`), URI
`https://idhml.gs1br.org/01/07898357410022`, cadastro criado no portal para o teste: tipo de link padrão
`gs1:pip`, com links em português e inglês; `gs1:instructions` em português e inglês; todos `text/html`.

| Resultado | Testes |
|---|---|
| **31 de 31 aprovados** | URL válida, URI GS1 Digital Link, HTTPS, TLS, subida na hierarquia, arquivo de descrição válido no schema, HTTP 1.1, CORS, GET/HEAD/OPTIONS, 400 para URI inválida, nenhum erro com 200, barra final, nenhum link legado no cabeçalho `Link`, query string repassada, linkset por `linkType` e por `Accept`, linkset válido, cabeçalho do contexto JSON-LD, tipo de conteúdo, um único link padrão, redirecionamento ao padrão, `gs1:pip` e `gs1:instructions` em cada idioma, as duas variantes `gs1:defaultLinkMulti`, tipos de link ratificados, 404 para tipo de link ausente |

**Ambiente de desenvolvimento** (`dev-tests/resolver/test_gs1_suite.py`, o mesmo código da suíte, sem
alteração, no Chromium contra o código do Resolver): sete cenários — o GTIN acima com um par que dá 300 (o
portal não consegue criar um: recusa dois links do mesmo tipo e idioma), um GTIN com cadastro de lote, um
número de série com lote informativo, o GTIN com variantes de idioma sob um lote, um GLN (subida por
`/254/`) e nomes de cabeçalho em minúsculas, como no HTTP/2 — passam em todos os testes, exceto uma
divergência conhecida:

- **Variantes de idioma de um nível acima sob um lote (errata E12).** Com um cadastro de lote que tem link
  padrão próprio, sob um GTIN cujo link padrão tem variantes de idioma, a suíte espera que `/10/LOT1` com
  `Accept-Language: pt` ou `en` vá para a variante do GTIN. O Resolver responde com o link padrão do lote:
  cada entidade identificada tem exatamente um link padrão, do qual os links `gs1:defaultLinkMulti` são
  refinamentos (2.5.8); um nível abaixo pode definir o seu próprio padrão (2.5.9); o passo 3 do 2.6.3
  restringe a escolha ao link padrão e às suas variantes sem dizer de qual nível. O Resolver mantém as
  variantes junto do padrão que elas refinam. O padrão não resolve a questão, então isto é uma errata e uma
  issue para a suíte (item 8.2), não uma mudança de código. O caso não aparece na homologação, onde não há
  lote cadastrado sob esse GTIN.

**O F22 está encerrado.** A suíte transforma `https://gs1.org/voc/`, `https://ref.gs1.org/voc/` e
`https://www.gs1.org/voc/` em `gs1:` antes de toda verificação, então o namespace nunca muda o veredito; o
próprio linkset-modelo da suíte usa `https://ref.gs1.org/voc/`, que é como o 2.14 expande `gs1:`. Desde o
`bc573c4` os linksets usam esse namespace (decisão do responsável).

Depois da instalação do `bc573c4` (2 de outubro de 2026, em `e86d120`), a suíte deu de novo **31 de 31**
com a mesma URI, os tipos de link do linkset estavam todos em `https://ref.gs1.org/voc/` (`defaultLink`,
`defaultLinkMulti`, `instructions`, `pip`) e as linhas do F9 ao F13 desta seção, com esse GTIN, deram:

| Linha | Resposta | Leitura |
|---|---|---|
| F9, `Accept-Language: de` | 307 para o link padrão (`…/pip-pt`) | F9 corrigido: idioma sem correspondência → link padrão (exemplo 7) |
| F10, `/17/261231` | 400 | F10 corrigido: atributo de dados no caminho é recusado |
| F10, `/21/S1/10/L1` | 400 | F10 corrigido: qualificadores fora de ordem são recusados |
| F12, `/10/A%2FB` | 307 para o link padrão | F12 corrigido: o valor mantém a `/` e o lote desconhecido sobe até o GTIN |
| F13, `?17=…;3103=…` | 307 para `…/pip-pt?17=261231;3103=000189` | F13 corrigido: a query string é repassada exatamente como enviada |
