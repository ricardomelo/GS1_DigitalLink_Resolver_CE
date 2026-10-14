# ADR 0003 — Uma fonte única para as regras GS1: o GS1 Barcode Syntax Dictionary

| | |
|---|---|
| Situação | **Aceito** (13 de outubro de 2026) e **implementado** em quatro etapas: 1 (este registro), 2 (uma versão do motor), 3 (regras geradas do dicionário, a verificação semanal), 4 (mensagens do motor traduzidas, AIs novos nomeados); veja a seção 3.6 |
| Item do backlog | 2.5 — uma fonte única para as regras GS1 |
| Decidido por | o responsável pelo branch, sobre as opções da seção 4 (as quatro recomendadas) |
| Inglês | [ADR 0003 in English](../../adr/0003-gs1-rules-from-the-dictionary.md) (versão de referência) |

## 1. Contexto

Hoje há regras GS1 em três lugares:

| Onde | O quê | Versão |
|---|---|---|
| `portal/gs1.py` | as 16 chaves primárias da GS1 Digital Link URI Syntax 1.7 e seus formatos, os qualificadores de chave e seus caminhos, escritos à mão espelhando o GS1 Barcode Syntax Engine (o `test_keys.py` compara) | nenhuma: o que foi copiado |
| `portal/syntax.py` | atributos de dados (§4.10): títulos, formatos e os AIs permitidos no caminho de cada chave, lidos do `gs1-syntax-dictionary.txt` do motor; valores conferidos pela biblioteca C do motor | 1.4.1, fixada em `portal/tools/build-syntax-engine.sh` |
| `web_server/` (o Resolver) e `data_entry_server/` | todo caminho de requisição, e todo cadastro que a API de entrada de dados recebe, conferidos pela versão WebAssembly do motor (`callGS1encoder.js`) | **não fixada**: os dois Dockerfiles rodam `npm install gs1encoder`, e cada build pega a versão mais nova |

Consequências: uma mudança do dicionário (um AI novo, um qualificador novo, um formato novo) chega ao Resolver no
próximo build, sem aviso, enquanto as tabelas escritas à mão do portal ficam como estavam; o portal pode aceitar
um cadastro que o Resolver recusa, ou recusar um que ele aceita. Os testes de desenvolvimento e o CI fixam a 1.4.1
para os dois motores num terceiro lugar (`.github/actions/dev-tests-setup/action.yml`). As mensagens do motor só
existem em inglês, e o portal as mostra como vêm (`attr.invalid`), num portal que de resto fala português e
inglês.

O dicionário da 1.4.1 (release 2026-01-27) já descreve os AIs (7041) UFRGT UNIT TYPE e (8040)–(8043) IMEI, IMEI2,
ESIM, PSIM. Nenhum é atributo de dados de GS1 Digital Link (sem a marca `?`), nem chave, nem qualificador; por isso
o portal hoje nunca os nomeia.

## 2. Decisão

1. **As regras de chaves, qualificadores e formatos vêm do dicionário**, por um arquivo gerado a partir dele,
   `portal/gs1_dictionary.json`, guardado no git: todo AI com título, marcas, componentes (tipo, tamanho,
   linters), `req`, `ex` e `dlpkey`, e a versão. Um script (`portal/tools/gen_dictionary.py`) o escreve a partir do
   dicionário do motor; um teste de desenvolvimento falha quando o arquivo difere do dicionário da versão fixada.
   O `gs1.py` monta suas tabelas a partir do arquivo; o portal continua funcionando sem o motor.
2. **O que o portal faz diferente de propósito continua, numa lista única de exceções** no `gs1.py`, cada uma com
   o motivo: ITIP sem (22) (errata E2), os conjuntos de caracteres mais estreitos de chaves e qualificadores, os
   nomes curtos das chaves (da URI Syntax §4.3, que o dicionário não traz). Uma chave ou um qualificador cujo
   formato o portal ainda não sabe conferir (um linter que ele não conhece) faz o gerador e os testes falharem, em
   vez de ser aceito sem conferência.
3. **Uma versão do motor para o portal, o Resolver e a API de entrada de dados, escrita uma vez, no
   `docker-compose.yml`** (um campo de extensão passado às imagens como argumento de build). O Resolver e a API de
   entrada de dados instalam `gs1encoder@<versão>`; o script de build do portal compila essa versão; a ação de
   preparação do CI e os testes de desenvolvimento a leem do arquivo do compose; um teste falha quando algum deles
   diverge.
4. **Toda mensagem do motor fixado é traduzida.** Uma tabela gerada a partir do código-fonte do motor (seus modelos
   de erro em inglês e as mensagens dos linters) transforma uma mensagem do motor num código de mensagem com
   parâmetros; o portal a mostra no idioma do usuário (chaves `engine.*` no `i18n.js`, sendo a inglesa o próprio
   texto do motor). Um teste falha quando a versão fixada tem uma mensagem sem tradução.
5. **Uma tarefa agendada semanal propõe atualizações**: um workflow do GitHub Actions procura uma versão mais nova
   do motor; quando há, regenera o arquivo do dicionário e a tabela de mensagens para ela, roda os testes do portal
   com ela e abre uma issue (uma por versão) dizendo o que mudou: AIs acrescentados, removidos ou alterados,
   atributos de dados novos, mensagens sem tradução, resultado dos testes. A atualização continua sendo uma mudança
   revisada da versão única.
6. **AIs (7041) e (8040)–(8043)**: nomeados onde o portal nomeia AIs (títulos do dicionário, nomes em português ao
   lado dos outros 216) e aceitos pelo portal exatamente como o dicionário diz: hoje nem como atributos de dados
   nem como qualificadores. Quando uma versão do dicionário fizer deles atributos de dados, eles aparecem no editor
   sem mudança de código.

## 3. Projeto

### 3.1 `portal/gs1_dictionary.json`

```json
{"release": "1.4.1", "dictionary": "2026-01-27",
 "ais": {"01": {"title": "GTIN", "flags": "*?", "components": [{"type": "N", "min": 14, "max": 14,
          "optional": false, "linters": ["csum", "gcppos2"]}], "req": [], "ex": [["255"], ["37"]],
          "dlpkey": [["22", "10", "21"], ["235"]]}, …}}
```

As faixas (`3100-3105`) são expandidas. `req` e `ex` mantêm os grupos do dicionário (`01+21` é um grupo). O arquivo
é escrito ordenado, para que uma versão nova apareça como uma diferença legível.

### 3.2 Chaves e qualificadores montados a partir do arquivo

- **Chaves primárias**: os AIs com `dlpkey`. O validador de cada chave é escolhido pela forma dos seus
  componentes: um componente numérico com `csum` (GLN, SSCC, GSRN, GSIN, GTIN com suas formas mais curtas); uma
  base numérica com `csum` e um serial opcional (GDTI, GCN, GRAI com o `zero` inicial); GTIN + `pieceoftotal`
  (ITIP); alfanumérica com `gcppos1` (GINC, GIAI), com `csumalpha` (GMN), no conjunto de caracteres 39 (CPID).
  Tamanhos, máximos e tamanhos de serial vêm dos componentes. Os códigos de mensagem do portal continuam os mesmos.
- **Qualificadores**: os AIs das sequências `dlpkey`, na ordem do dicionário; cada sequência é uma forma de
  qualificadores opcionais; um qualificador que o `req` da chave nomeia passa a ser obrigatório (415 exige 8020).
  Formatos pelos seus componentes, com os linters `nozeroprefix` (8011) e `importeridx` (7040).
- **Linters que o portal implementa**: `csum`, `csumalpha`, `gcppos1`, `gcppos2`, `zero`, `pieceoftotal`,
  `nozeroprefix`, `importeridx`. Qualquer outro linter numa chave ou qualificador faz o gerador falhar.
- **Exceções** (`PORTAL_EXCEPTIONS`): ITIP sem (22) (errata E2, o motor recusa 22 sem 01); chaves alfanuméricas em
  letras, dígitos, `.` e `-`; qualificadores em letras, dígitos, `.`, `_` e `-`; CPID sem `#` e `/`; os nomes curtos
  das chaves.
- O `syntax.py` lê títulos, atributos de dados e AIs de caminho do mesmo arquivo, de modo que o editor oferece os
  atributos de dados do dicionário fixado mesmo antes de o motor carregar (os valores continuam conferidos pelo
  motor).

### 3.3 Uma versão

O `docker-compose.yml` ganha `x-gs1-syntax-engine: &gs1-syntax-engine "1.4.1"`, usado como argumento de build
`GS1_SYNTAX_ENGINE_RELEASE` do `web-service`, do `data-entry-service` e dos três serviços montados de `./portal`.
Os Dockerfiles do Resolver e da API de entrada de dados instalam `gs1encoder@${GS1_SYNTAX_ENGINE_RELEASE}`; o
Dockerfile do portal passa a versão ao `build-syntax-engine.sh`. A ação de preparação do CI lê a versão do arquivo
do compose. Um teste de desenvolvimento confere que todos os lugares concordam e que o `gs1_dictionary.json` foi
gerado dessa versão.

### 3.4 Mensagens do motor

O `portal/tools/gen_engine_messages.py` lê o `tr_EN.h` do motor fixado (cerca de 95 modelos) e as mensagens dos
seus linters (cerca de 85) e escreve o `portal/engine_messages.json`: para cada uma, um código e um padrão que
recupera os parâmetros (`AI (%.*s) value is too long` → `engine.AI_VALUE_IS_TOO_LONG` com `ai`). O `syntax.py`
reconhece a mensagem do motor e responde `attr.engine` com o código e os parâmetros (o texto em inglês fica no
log); o navegador mostra `engine.*` a partir do `i18n.js`. Uma mensagem que nenhum padrão reconhece aparece como
hoje, em inglês.

### 3.5 A tarefa semanal

`.github/workflows/engine-update.yml`: semanal e sob demanda; lê a versão fixada; pergunta ao GitHub a versão mais
nova de `gs1/gs1-syntax-engine`; se for mais nova e não houver issue aberta com o título dela, compila a versão,
regenera os dois arquivos numa pasta de trabalho, compara com os do repositório
(`portal/tools/dictionary_diff.py`), roda o grupo portal dos testes de desenvolvimento com ela e abre uma issue com
o resumo. Permissões: `contents: read`, `issues: write`. Nunca altera o branch.

### 3.6 Como implementado

- A etapa 2 pôs a versão no `docker-compose.yml` e os argumentos de build no lugar; a tarefa semanal veio com a
  etapa 3, porque precisa do gerador e da comparação (`portal/tools/dictionary_diff.py`), que também diz se o portal
  consegue montar suas regras com o dicionário novo. A tarefa usa a versão nova na sua própria cópia do repositório
  (o valor do compose reescrito ali), de modo que a ação de preparação do CI compila e instala essa versão sem
  mudança; só versões numeradas contam (o repositório também tem tags antigas com datas).
- O `gs1dict.py` reúne o leitor do texto e do arquivo; o `gs1_dictionary.json` tem um AI por linha. A imagem do
  portal copia todo `*.json` de `portal/` com os módulos (o `test_deploy.py` sobe o portal a partir dos arquivos da
  imagem).
- Além da seção 3.2: o navegador também deixou de repetir tamanhos e formatos. O `/config` manda `rules`
  (`gs1.browser_rules()`: a conferência de cada chave como um tipo e seus números, o padrão e o tamanho máximo de
  cada qualificador, a ordem), e o `app.js` confere a partir delas; um Pay-to GLN (415), que não tinha conferência
  ao vivo no navegador, passou a ter. Os nomes dos qualificadores em `QUALIFIER_FORMATS` agora são os títulos do
  dicionário (não aparecem na tela).
- As formas de duas chaves ficaram escritas de outro jeito e aceitam exatamente os mesmos cadastros: 417 e 8004
  eram "sozinhas, ou com 7040 obrigatório" e agora são "7040 opcional", como o dicionário escreve.
- Etapa 4, as mensagens (a seção 3.4 como construída): a versão 1.4.1 tem 94 modelos e 117 mensagens de linters,
  todos traduzidos. O script de build também copia as fontes das mensagens do motor (`source/`) para a compilação.
  Os parâmetros são numerados (`{p1}`, `{p2}`… na ordem do modelo), não nomeados, porque um modelo não diz o que
  cada um é; a mensagem de um linter, ou de outro modelo, dentro de uma mensagem é reconhecida como mensagem própria
  (`AI (17): The date contains an illegal month of the year.` → `engine.AI_LINTER_ERROR` com `p1` `17` e `p2`
  `engine.lint.ILLEGAL_MONTH`), e o modelo mais específico é tentado primeiro. A recusa mantém o código
  `attr.invalid` e o `detail` em inglês, e ganha `message` (código e parâmetros); o navegador mostra o texto
  traduzido no lugar do `detail` (`i18n.js`). As regras de associação mantêm as mensagens próprias
  (`attr.requires`, `attr.pair`, `attr.unknown`), que dão o nome do AI como o usuário o escolheu. Quem reconhece é o
  `portal/engine_messages.py`; o `gen_engine_messages.py --summary` dá à issue semanal as mensagens que precisam de
  tradução.
- Os AIs novos ganharam nomes em português (221 nomeados ao todo); como na 1.4.1 não são atributos de dados nem
  qualificadores, só aparecem onde uma mensagem os cita.

## 4. Opções consideradas

| Ponto | Escolhida (recomendada) | Não escolhidas |
|---|---|---|
| De onde vêm as regras do portal | um arquivo gerado do dicionário, no git, conferido por um teste | o dicionário lido na partida (o motor passaria a ser obrigatório); o motor validando tudo (as conferências em Python e suas mensagens sairiam, o portal dependeria do motor) |
| Onde a versão fica escrita | `docker-compose.yml`, um valor | um padrão em cada Dockerfile e script, comparados por um teste; o `.env` (cada servidor com sua versão) |
| Quais mensagens do motor são traduzidas | todas as da versão fixada, conferidas por um teste | as frequentes; nenhuma |
| Como as atualizações são propostas | uma tarefa semanal que abre uma issue | um pull request aberto pela tarefa (mais permissões; o CI não roda no pull request de um bot com o token padrão); um script rodado à mão |
| Entregas | quatro etapas | duas etapas maiores |

## 5. Consequências

- Uma versão nova do dicionário chega ao portal, ao Resolver e à API de entrada de dados juntos, só quando a versão
  no `docker-compose.yml` muda, depois de revisada; nenhum serviço muda de comportamento por ser recompilado.
- Fixar o `gs1encoder` nos Dockerfiles oficiais é uma mudança deliberada no código oficial (CHANGELOG).
- As tabelas escritas à mão do `gs1.py` desaparecem; acrescentar uma chave ou um qualificador que o dicionário já
  descreve não exige código, a não ser que traga um formato que o portal não sabe conferir, o que os testes então
  apontam.
- As mensagens do motor aparecem em português; uma versão nova com mensagens novas é apontada pela issue semanal e
  pelos testes antes de ser adotada.
- A tarefa semanal usa a API do GitHub sem um token do responsável: o `GITHUB_TOKEN` padrão com `issues: write`.

## 6. Configuração acrescentada

Nenhuma no `.env`. O `docker-compose.yml` guarda a versão (um campo de extensão, lido pelo próprio Compose).

## 7. Entregas

1. Este registro (nos dois idiomas).
2. Uma versão (`docker-compose.yml`, os três Dockerfiles, o script de build, a ação de preparação do CI, um teste
   de consistência) e o workflow semanal.
3. `gs1_dictionary.json`, seu gerador e teste; `gs1.py` e `syntax.py` montados a partir dele.
4. Mensagens do motor traduzidas; AIs (7041) e (8040)–(8043) nomeados; documentação.
