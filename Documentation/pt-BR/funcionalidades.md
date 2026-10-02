# Funcionalidades

Todas as funcionalidades do GS1 Digital Link Resolver CE — Expansion Pack, agrupadas por componente, com o
que cada uma faz e o commit que a introduziu (no branch `gs1br/develop`; a ordem cronológica está no
[histórico](historico.md)). As funcionalidades do GS1 Resolver CE v3 oficial que o fork mantém sem mudança
aparecem no fim, para completar o quadro.

*English version: [features](../features.md).* Como usar o portal: [guia do portal](guia-do-portal.md).
Como cada funcionalidade é construída: [guia do desenvolvedor](guia-do-desenvolvedor.md).

## Sumário

- [Resolver (resolução pública)](#resolver-resolução-pública)
- [API de cadastro (data entry)](#api-de-cadastro-data-entry)
- [Portal: acesso e contas](#portal-acesso-e-contas)
- [Portal: editor](#portal-editor)
- [Portal: chaves de identificação e qualificadores](#portal-chaves-de-identificação-e-qualificadores)
- [Portal: etiquetas com QR Code](#portal-etiquetas-com-qr-code)
- [Portal: atributos de dados](#portal-atributos-de-dados)
- [Portal: lista de registros](#portal-lista-de-registros)
- [Portal: planilhas](#portal-planilhas)
- [Portal: verificador de links](#portal-verificador-de-links)
- [Portal: governança](#portal-governança)
- [Portal: robustez e segurança](#portal-robustez-e-segurança)
- [Portal: idiomas e aparência](#portal-idiomas-e-aparência)
- [Página inicial e navegação](#página-inicial-e-navegação)
- [Configuração, instalação e operação](#configuração-instalação-e-operação)
- [Testes de desenvolvimento e documentação](#testes-de-desenvolvimento-e-documentação)
- [Mantido do projeto oficial](#mantido-do-projeto-oficial)

## Resolver (resolução pública)

| Funcionalidade | O que faz | Desde |
|---|---|---|
| Subida na hierarquia (walk-up) | Um nível sem cadastro recorre ao seguinte: série → lote → variante → chave, em vez de erro 500 | `766a652` |
| Série antes do lote | Quando um cadastro de série e um de lote ou variante se aplicam juntos, responde o da série (GS1-Conformant Resolver 2.5.9, regra 4: 01+21 antes de 01+22+10) | `61babe1` |
| 404 para tipo de link ausente | Um cadastro sem o `linkType` pedido responde 404, como exige o GS1-Conformant Resolver 2.6.2 (antes era 200 com erro dentro) | `766a652` |
| Barra no final | `/10/123/` é tratado como `/10/123` (antes era 400) | `766a652` |
| Formas de `linkType` | Aceita `x`, `gs1:x`, `https://gs1.org/voc/x`, `https://ref.gs1.org/voc/x`, sem diferenciar maiúsculas; `defaultLink` redireciona ao destino principal | `766a652` |
| Linkset conforme | `?linkType=linkset` / `Accept: application/linkset+json` devolve RFC 9264 puro, válido no schema de linkset da GS1; JSON-LD só sob pedido; cabeçalho `Link` do contexto JSON-LD correto e exposto ao CORS | `766a652` |
| Repasse da query string | A query string da leitura (atributos de dados incluídos) é repassada exatamente como enviada — com o separador `;` e chaves sem valor — sempre (`"fwqs": false` de cadastros antigos é ignorado, Resolver 2.12); unida com `&` quando o destino já tem parâmetros | `766a652`, `4f81234` |
| Resposta padrão | Sem `linkType`, o link padrão, salvo quando a requisição indica uma versão de idioma (Resolver 2.6.3, exemplos 5 a 7; antes, 300 para dois idiomas sem correspondência); vários links do tipo principal publicados como `gs1:defaultLinkMulti` | `4f81234` |
| Escolha entre links de um tipo | Tipo de mídia, depois idioma (pesos q, `pt-BR` → `pt`), depois contexto (exemplos 8 a 13); o 300 devolve um linkset válido daquele nível, ou uma página HTML | `4f81234` |
| Caminhos conferidos pelo engine | O leitor de Digital Link do GS1 Barcode Syntax Engine confere o caminho: qualificadores fora de ordem, atributos de dados ou AIs desconhecidos no caminho → 400 | `4f81234` |
| Valores com `/` | Um `%2F` num valor fica dentro dele: o proxy repassa a URI original e o Resolver decodifica cada segmento separadamente | `4f81234` |
| EPC em binário | `/eh…` e `/ex…` (um EPC lido de uma etiqueta NFC ou híbrida UHF/NFC) são descomprimidos e resolvidos como o GS1 Digital Link equivalente: todos os esquemas EPC que têm Digital Link, os esquemas `+` com seus dados +AIDC e os esquemas `++` (com o hostname ignorado); qualificadores vindos da etiqueta vão para o caminho, atributos de dados para a query string repassada ao destino; 400 quando a cadeia não decodifica (Resolver 2.3, EPCB 1.0.0) | `51a0da8`, `895c4b1` |
| Páginas HTML para navegadores | Erros (400, 404, tipo de link indisponível — com a lista dos links disponíveis) e o linkset como páginas no estilo do gs1.org, em pt-BR / en-GB, com o mesmo status HTTP e menu de idioma | `766a652` |
| Nomes dos níveis no linkset | Cada nível nomeado pela sua âncora: a chave, variante, lote, série, extensão do GLN… | `b33def6` |
| Links seguros nas páginas HTML | Só destinos `http(s)` viram links; `javascript:`, `data:` e outros aparecem sem link | `92bfb5d` |
| Arquivo de descrição configurável | `/.well-known/gs1resolver` usa `resolverRoot` e `contact` (nome, endereço, telefone, `hasURL`) do `.env`, e `termsOfUse` de `RESOLVER_TERMS_URL`; validado por schema nos testes | `766a652`, `764e360`, `cc72145`, `4f81234` |
| Rodapé do operador | "Serviço GS1 Digital Link operado por …" a partir de `RESOLVER_ORG_NAME`, por instalação | `766a652`, `764e360` |

## API de cadastro (data entry)

| Funcionalidade | O que faz | Desde |
|---|---|---|
| `GET /api/summary[?links=true]` | Uma linha por cadastro (âncora, qualificadores, descrição, tipo principal, número de links e, opcionalmente, os links): o portal lê todos os cadastros numa chamada só | `db56b22` |
| Token em `/api/index` | O `GET /api/index` oficial, que era público e listava todos os identificadores do Resolver, passou a exigir o token | `1941e75` |
| `BearerAuth` no Swagger | Toda operação protegida declara o esquema bearer, então **Authorize** em `/api/docs` funciona | `1941e75` |
| Regras de cadastro | `POST /new` e `PUT` recusam qualificador que a chave não aceita, 415 sem 8020, 235 com outros qualificadores e 22 ou 10 junto com 21 (GS1-Conformant Resolver 2.5.9, regras 1 e 2); uma lista é recusada inteira, indicando o item | `61babe1` |
| `informativeQualifiers` | Um cadastro de série de GTIN ou ITIP guarda variante e lote da unidade como informação: gravados, devolvidos pelo `GET` e pelo `/summary`, substituídos pelo `PUT`; nunca usados para escolher o cadastro nem publicados no linkset | `61babe1` |

## Portal: acesso e contas

| Funcionalidade | O que faz | Desde |
|---|---|---|
| Página de entrada | Usuário e senha, cookie de sessão (HttpOnly, SameSite, Secure em HTTPS), validade renovada a cada uso (`PORTAL_SESSION_HOURS`, padrão 8 horas) | `126f507` |
| Limite de tentativas | 5 falhas → 15 minutos de espera, por nome de usuário e por endereço | `126f507` |
| Troca de senha | Janela Opções; exige a senha atual; pelo menos 12 caracteres; encerra as outras sessões | `126f507` |
| Impressão digital da sessão | Trocar ou redefinir a senha encerra todas as outras sessões da conta | `126f507` |
| Botão de mostrar senha | Um olho em cada campo de senha (entrada, troca de senha) | `1525f82` |
| Primeiro usuário pelo `.env` | `PORTAL_ADMIN_USERNAME` / `PORTAL_ADMIN_PASSWORD` criam o primeiro administrador enquanto não há usuários | `126f507` |
| Usuários pela linha de comando | `create_user.py`: criar, definir senha, perfil, prefixos, excluir | `126f507`, `71b15f2` |

## Portal: editor

| Funcionalidade | O que faz | Desde |
|---|---|---|
| Formulário em três passos | Identificar → descrever → destinos, com validação imediata e a etiqueta ao lado | `126f507` |
| Abrir cadastro | Lê o cadastro no Resolver; informa se existe e quais outros cadastros a chave tem; bloqueia os passos 2 e 3 quando o identificador muda depois | `126f507` |
| Destinos | Tipo de link (29 tipos GS1 com explicações), idioma, URL, título, destino principal, até 20 por cadastro (a opção de repasse de parâmetros por destino saiu em `db8e342`) | `126f507` |
| Tipo principal compartilhado | Explica e garante que todos os cadastros de uma chave usem o mesmo tipo de destino principal | `126f507` |
| Sequência segura na API | POST acrescenta, PUT mescla, DELETE parcial remove só os destinos que o usuário tirou; excluir um cadastro mantém os outros da chave (restaurados em caso de falha) | `126f507` |
| Outros cadastros da chave | Lista embaixo de *Abrir cadastro*: a que cada um se aplica, descrição, links, última alteração; busca, filtro por qualificador, cinco linhas à vista, *Abrir* com confirmação se houver alterações não salvas | `08570e4` |
| Lote e variante informativos | Com número de série, os campos de variante e lote de GTIN ou ITIP ficam marcados como *informativos*: guardados no cadastro da série e impressos no QR Code, mas fora do cadastro (GS1-Conformant Resolver 2.5.9, regra 2); abrir uma série sem eles preenche os gravados; um valor digitado diferente é apontado | `83d1ba0` |
| "Este cadastro vale para" | Um quadro abaixo dos qualificadores diz, em linguagem simples, para que o cadastro vale e para onde vão os códigos sem cadastro próprio | `83d1ba0` |
| Cadastro da chave ao salvar | Salvar um lote, série ou extensão de uma chave sem cadastro próprio oferece criar esse cadastro com os mesmos destinos (recomendado), com outro destino, ou não (GS1-Conformant Resolver 2.5.9) | `3a49ca9` |
| Copiar destinos de… | Busca qualquer cadastro e acrescenta os destinos dele ao formulário ou os substitui | `3a49ca9` |
| Confirmação no *Abrir cadastro* | Pergunta antes de descartar alterações não salvas, também depois de mudar a chave ou os qualificadores | `3a49ca9` |
| Singular | "Este identificador tem mais um cadastro" | `d11c369` |
| Modo leitura | O leitor vê todos os campos bloqueados e um aviso | `71b15f2` |

## Portal: chaves de identificação e qualificadores

| Funcionalidade | O que faz | Desde |
|---|---|---|
| Todas as chaves primárias da URI Syntax 1.7 §4.3 | GTIN, ITIP, GMN, CPID, GLN (414, 415, 417), GSRN (8017, 8018), GCN, SSCC, GDTI, GINC, GSIN, GRAI, GIAI, cada uma com rótulo, dica e conferências próprias (dígito verificador, par de caracteres do GMN, peça/total do ITIP, zero inicial do GRAI…) | `e181ccc` |
| Todos os qualificadores da §4.4/4.6/4.9 | 22, 10, 21, 235 (TPX), 8011, 254, 7040, 8020, 8019, com as combinações e a ordem que o padrão permite e os obrigatórios (8020 para 415) | `67d40bb` |
| Espelha o Syntax Engine | Validação em Python e JavaScript comparada com o GS1 Barcode Syntax Engine nos testes | `e181ccc`, `67d40bb` |
| Comodidades do GTIN | 8, 12, 13 ou 14 dígitos digitados, gravados como GTIN-14; GTIN-13 de circulação restrita (prefixo 2) recusado | `126f507` |

## Portal: etiquetas com QR Code

| Funcionalidade | O que faz | Desde |
|---|---|---|
| Prévia ao vivo | QR Code, Digital Link colorido e legenda enquanto se digita; *Publicado* / *Ainda não cadastrado* | `126f507` |
| PNG e SVG | SVG em milímetros com X = 0,495 mm, zona de silêncio de 4X, HRI de 2,2 mm em contornos (não precisa de fonte); PNG para telas | `126f507` |
| Sem marca GS1 | As etiquetas não levam arte da GS1 | `7e7a62a` |
| Modos de HRI | Completo (cada elemento numa linha), só a chave, nenhum | `1525f82` |
| Versão do QR | Automática (a menor que couber) ou de 1 a 40 | `1525f82` |
| Correção de erros | L, M (padrão), Q, H, aplicada exatamente como escolhida | `1525f82` |
| Painel "não cabe" | Explica a versão necessária ou o nível que cabe, em vez de uma imagem quebrada (422 `qr.tooSmall` / `qr.tooLong`) | `1525f82` |
| Layout do bloco da etiqueta | Embaixo do formulário em qualquer largura: código e botões à esquerda, opções à direita; uma coluna no celular | `1746f19` |
| Testar o link, Copiar endereço | Abre ou copia o Digital Link | `126f507` |

## Portal: atributos de dados

| Funcionalidade | O que faz | Desde |
|---|---|---|
| Atributos no QR Code | Validade, peso, preço… (URI Syntax §4.10) acrescentados ao código gerado agora; nunca gravados; limpos quando outro cadastro é aberto | `4b42c6f` |
| GS1 Barcode Syntax Engine | Validação pela própria biblioteca C da GS1, versão 1.4.1, e o binding Python (compilados num estágio do Docker); a opção some quando o engine não está instalado | `4b42c6f` |
| Caixa de combinação | Escolher em *Mais usados* / *Todos os atributos* ou digitar número ou nome; funciona no celular | `1525f82` |
| Ordem | Botões para subir e descer | `1525f82` |
| Dia 00 recusado | Com sugestão do primeiro ou último dia do mês | `1525f82` |
| Famílias decimais | (310n), (392n)… aceitam `123,45` ou `123.45` e codificam `3102=012345`; a linha da URI mostra as casas decimais usadas | `e71384d` |
| Sem limite de 10 | Teto de 100 por requisição; o QR Code é o limite real | `e71384d` |
| Mensagens traduzidas | Erros de associação (`requires`, `pair`) nos dois idiomas | `08570e4` |
| Nomes dos AIs em português | 216 nomes, como "(17) Data de validade (USE BY or EXPIRY)", no campo e na lista; buscar na lista mantém o atributo escolhido | `08570e4`, `cf5ce10` |

## Portal: lista de registros

| Funcionalidade | O que faz | Desde |
|---|---|---|
| Registros cadastrados | Todos os cadastros que o usuário pode ver, os alterados mais recentemente primeiro, com identificador, abrangência, links e última alteração | `db56b22` |
| Busca por texto | Identificador (com ou sem zeros à esquerda), nome da chave, descrição, qualificador; ignora acentos e maiúsculas | `db56b22` |
| Filtro por autor | *Alterado por* | `db56b22` |
| Filtro por tipo de chave | *Tipo de identificador*, com contagens | `f4f3071` |
| Filtro por qualificador | *Qualificador*: qualquer qualificador, nenhum ou conjuntos criados fora; acompanha o tipo de chave | `f4f3071` |
| Busca por código | Um GS1 Digital Link colado ou uma element string com parênteses mostra o cadastro exato (marcado), os mais gerais e os mais específicos; nomeia os AIs ignorados | `f4f3071` |
| Limpar busca e filtros | Um botão | `f4f3071` |
| Cadastros feitos fora | Listados (modelos como `{lotnumber}`), sem abrir | `db56b22`, `7339e3c` |
| Qualificadores informativos nas listas | Filtros, busca por texto e busca por código encontram uma série pelo lote ou variante informativos; o escopo os mostra | `83d1ba0` |
| Filtro de situação e alerta | *Situação*: registros de chaves sem cadastro próprio (com alerta e *Mostrar só esses*) e séries cadastradas com lote antes da regra 2; selo em cada um | `3a49ca9` |

## Portal: planilhas

| Funcionalidade | O que faz | Desde |
|---|---|---|
| Exportação | XLSX (com as abas Tipos de link, Chaves e Idiomas) ou CSV, uma linha por destino, títulos no idioma do usuário | `429dce7` |
| Importação em duas etapas | Prévia com Novos / Alterados / Sem mudança / Com erro e cada linha errada explicada; depois a gravação em segundo plano com progresso | `429dce7`, `7339e3c` |
| Nunca exclui | Cadastros que não estão no arquivo continuam | `429dce7` |
| Qualquer idioma BCP 47 | `pt-BR`, `en-US`, `vi`, `und`… aceitos e mantidos | `7339e3c` |
| Limites por formato | XLSX e CSV/TXT: 5.000 linhas e 700 KB, mostrados na janela | `9d12f9d` |
| Amigável ao Excel | Arquivos Windows-1252, UTF-8 e UTF-16 ("Texto Unicode"); separador detectado; notação científica detectada; proteção contra fórmulas na exportação | `429dce7`, `1b58bfd` |
| Qualificadores informativos nas planilhas | `(10)B42(21)S1` é exportado para uma série com lote informativo e importado de volta do mesmo jeito; a troca de lote aparece na prévia | `83d1ba0` |
| Chaves sem cadastro próprio | A prévia as lista e, marcada por padrão, cria o cadastro de cada chave com os destinos da primeira linha dela | `3a49ca9` |

## Portal: verificador de links

| Funcionalidade | O que faz | Desde |
|---|---|---|
| Verificar destinos (editor) | Depois de cada salvamento e sob demanda; resultado embaixo de cada destino | `0da20ee` |
| Verificar links (todos os cadastros) | Tarefa em segundo plano; resumo guardado; aviso por cadastro; *Só com problemas* | `0da20ee` |
| Verificação na prévia da importação | Opcional, não impede a importação | `0da20ee` |
| Proteção contra SSRF | Só endereços públicos são contatados, a cada redirecionamento | `0da20ee` |
| Motivos claros | Erros HTTP, verificação bloqueada (401/403/429), site fora do ar, rebaixamento de HTTPS, redirecionamentos demais, endereço privado, inválido | `0da20ee` |

## Portal: governança

| Funcionalidade | O que faz | Desde |
|---|---|---|
| Perfis | Leitor < editor < administrador, conferidos em toda chamada | `71b15f2` |
| Prefixos de empresa GS1 por usuário | O usuário só vê e altera identificadores dos seus prefixos (lidos depois do dígito indicador do GTIN-14/ITIP, do dígito de extensão do SSCC, do zero inicial do GRAI) | `71b15f2` |
| Tela de usuários | Criar com senha temporária mostrada uma vez, mudar perfil e prefixos, redefinir senha, desativar, excluir; pelo menos um administrador ativo | `71b15f2` |
| Histórico do cadastro | Toda versão salva pelo portal, com restauração | `71b15f2` |
| Auditoria | Entradas, alterações, importações, exportações, administração; filtros; CSV | `71b15f2` |
| Diário | `journal.jsonl` no volume de configuração, incluído no backup | `71b15f2` |

## Portal: robustez e segurança

| Funcionalidade | O que faz | Desde |
|---|---|---|
| Back-end entre o navegador e a API | O token da API nunca chega ao navegador | `126f507` |
| Gravações da mesma origem | Gravações exigem corpo JSON e a origem do próprio portal | `126f507` |
| Cabeçalhos de segurança | `nosniff`, bloqueio de frames, referrer da mesma origem, `no-store` | `126f507` |
| Caracteres especiais | Só dígitos ASCII nos identificadores; caracteres invisíveis removidos; texto NFC sem caracteres de controle; endereços com espaço ou quebra de linha recusados; nomes de usuário digitados registrados com segurança | `1b58bfd` |
| Proteção contra fórmulas | Exportações CSV/XLSX e o CSV da auditoria não executam fórmulas no Excel | `1b58bfd` |
| Células grandes | Uma célula de CSV acima de 128 KB é avisada, não vira erro do servidor | `9d12f9d` |

## Portal: idiomas e aparência

| Funcionalidade | O que faz | Desde |
|---|---|---|
| pt-BR e en-GB | Todo texto nos dois idiomas, troca ao vivo; idioma do navegador detectado; escolha compartilhada com as páginas do Resolver e a página inicial | `126f507` |
| Códigos de mensagem | O servidor responde com códigos; o navegador traduz | `126f507` |
| Estilo parecido com o gs1.org | Montserrat, azul e laranja GS1; responsivo até o celular | `126f507` |
| Sem nomes de organização | Dados do operador só pelo `.env` | `7e7a62a`, `764e360` |

## Página inicial e navegação

| Funcionalidade | O que faz | Desde |
|---|---|---|
| Página inicial em `/` | O que é o Resolver, como usar, links para o portal e para a documentação da API; operador lido do arquivo de descrição | `ec1f1d7` |
| Link do operador | O nome do operador leva a `RESOLVER_ORG_URL` | `cc72145` |
| Navegação | Logotipo → página inicial; *Página inicial* no menu do usuário do portal | `a49f24d` |

## Configuração, instalação e operação

| Funcionalidade | O que faz | Desde |
|---|---|---|
| Configuração em camadas | `.env.example` (padrões versionados) + `.env` opcional (valores da instalação) em todos os serviços | `d51e398` |
| Endereços de bind | `PROXY_BIND_ADDRESS`, `DATABASE_BIND_ADDRESS` tiram as portas 8080 e 27017 da rede atrás de um proxy TLS | `d51e398` |
| Instalador para Ubuntu | `scripts/install.sh`: verificações, perguntas, Docker, nginx + Certbot ou certificado existente ou proxy externo, `.env` com segredos gerados, inicialização, cron de backup; pode ser rodado de novo; `--non-interactive` | `e11f630` |
| Instalador mais robusto | Senhas com caracteres especiais; recusa aspas simples na senha do primeiro usuário | `3f1ff37` |
| Reinício do proxy | O Compose reinicia o proxy quando um serviço atrás dele é recriado | `5f8c7d7` |
| Backup diário | Dump do MongoDB + volume de configuração do portal, 14 dias guardados, cron às 02:30 | `ba0c293` |
| Verificação de saúde | `/portal/healthz` | `126f507` |

## Testes de desenvolvimento e documentação

| Funcionalidade | O que faz | Desde |
|---|---|---|
| Testes de desenvolvimento | Resolver, decodificador de EPC em binário (conferido com o anexo E.3 do TDS e com a biblioteca `epc-tds`), API de cadastro, chaves, governança, planilhas, caracteres especiais, atributos de dados, verificador de links, portal de ponta a ponta no Chromium (desktop e celular), página inicial com nginx, instalador com simulações | `0733a3f` e seguintes |
| Screenshots | `dev-tests/docs/screenshots.py` regenera as imagens do README e do guia do portal nos dois idiomas | `f14d8c4`, sessão 4 |
| Documentação | README, guia do portal, funcionalidades, histórico, guia do desenvolvedor (em inglês e em português), documentação das extensões, changelog | `539bab0` e seguintes |

## Mantido do projeto oficial

Resolução de URIs GS1 Digital Link com negociação de conteúdo (idioma, tipo de mídia, contexto), a API de
cadastro (criar, ler, alterar, excluir; documentos v2 convertidos para v3), a validação de toda requisição
pelo GS1 Barcode Syntax Engine (Node), o banco MongoDB, o front-end nginx e os testes oficiais em `tests/`.
