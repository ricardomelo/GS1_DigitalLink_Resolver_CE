"use strict";

/*
 * Message catalogue and translation engine for the portal.
 *
 * Every user-facing string lives here. Elements opt in declaratively:
 *   data-i18n="key"              → textContent
 *   data-i18n-params='{"n":1}'   → placeholder values for {n}
 *   data-i18n-attr="placeholder:key;aria-label:key"
 *   data-i18n-type="gs1:pip"     → <option> text "gs1:pip — label"
 *   data-i18n-lang="pt"          → <option> text with the language name in the UI language
 * Calling I18N.apply() re-renders all of them, which is how the language menu switches live.
 *
 * To add a locale: copy one block below, translate it, add it to SUPPORTED and to LOCALE_MATCHERS.
 */
const I18N = (() => {
  const SUPPORTED = ["pt-BR", "en-GB"];
  const DEFAULT_LOCALE = "en-GB";
  const STORAGE_KEY = "gs1resolver.portal.locale";
  // Also written as a cookie on the whole domain, so the resolver's own pages follow the same choice.
  const COOKIE_NAME = "gs1resolver_lang";
  // First matching prefix of navigator.languages wins (e.g. "pt-PT" → pt-BR, "en-US" → en-GB).
  const LOCALE_MATCHERS = [["pt", "pt-BR"], ["en", "en-GB"]];

  const CATALOGUE = {
    "pt-BR": {
      "locale.name": "Português (Brasil)",
      "app.title": "Links do produto | GS1 Resolver Community Edition",
      "header.language": "Idioma",
      "header.home": "Página inicial do Resolver",
      "menu.home": "Página inicial",
      "menu.records": "Registros cadastrados",
      "records.title": "Registros cadastrados",
      "records.lede": "Todos os produtos e lotes publicados neste Resolver. Busque e clique em um registro para editá-lo.",
      "records.link": "Ver registros cadastrados →",
      "records.back": "← Voltar ao cadastro",
      "records.search": "Buscar registros",
      "records.searchPlaceholder": "Buscar por GTIN, descrição ou lote",
      "records.changedBy": "Alterado por",
      "records.anyone": "Qualquer pessoa",
      "records.new": "Novo cadastro",
      "records.col.product": "Produto",
      "records.col.gtin": "GTIN",
      "records.col.scope": "Vale para",
      "records.col.links": "Links",
      "records.col.changed": "Última alteração",
      "records.scope.product": "Todas as unidades",
      "records.scope.lot": "Lote {value}",
      "records.scope.other": "Outros qualificadores: {value}",
      "records.otherHint": "Criado fora do portal com qualificadores que o portal não edita; altere-o pela API.",
      "records.noDescription": "(sem descrição)",
      "records.noHistory": "sem histórico",
      "records.loading": "Carregando registros…",
      "records.count": "Registros: {shown} de {total}",
      "records.none": "Nenhum registro cadastrado ainda.",
      "records.noMatch": "Nenhum registro corresponde à busca.",
      "records.exportXlsx": "Exportar planilha (Excel)",
      "records.exportCsv": "Exportar CSV",
      "records.import": "Importar planilha",
      "sheet.col.gtin": "GTIN",
      "sheet.col.lot": "Lote",
      "sheet.col.description": "Descrição",
      "sheet.col.linkType": "Tipo de link",
      "sheet.col.url": "URL",
      "sheet.col.language": "Idioma",
      "sheet.col.title": "Título",
      "sheet.col.default": "Principal",
      "sheet.col.forward": "Repassar parâmetros",
      "sheet.yes": "sim",
      "sheet.no": "não",
      "sheet.links": "Links",
      "sheet.linkTypes": "Tipos de link",
      "sheet.languages": "Idiomas",
      "sheet.code": "Código",
      "sheet.name": "Nome",
      "sheet.description": "Descrição",
      "import.title": "Importar planilha",
      "import.intro": "Use o formato da planilha exportada: uma linha por destino; as linhas com o mesmo GTIN e lote formam um cadastro, e a coluna Principal indica o destino que abre primeiro. Cadastros que já existem são substituídos pelo conteúdo da planilha; os que não estão nela não mudam. Nada é gravado antes da sua confirmação.",
      "import.file": "Arquivo (Excel .xlsx ou CSV)",
      "import.checking": "Verificando a planilha…",
      "import.summary": "Novos: {create} · Alterados: {update} · Sem mudança: {unchanged} · Com erro: {error}",
      "import.col.rows": "Linhas",
      "import.col.result": "Resultado",
      "import.action.create": "Novo",
      "import.action.update": "Alterado",
      "import.action.unchanged": "Sem mudança",
      "import.action.error": "Com erro",
      "import.action.created": "Criado",
      "import.action.updated": "Alterado",
      "import.action.failed": "Falhou",
      "import.row": "Linha {row}:",
      "import.apply": "Importar cadastros ({count})",
      "import.errorsSkipped": "Os cadastros com erro serão ignorados; corrija a planilha e importe de novo se quiser incluí-los.",
      "import.running": "Importando… {done} de {total}",
      "import.done": "Importação concluída. Criados: {created} · Alterados: {updated} · Com falha: {failed}",
      "import.close": "Fechar",
      "import.tooBig": "O arquivo passa de {max} KB. Divida a planilha em partes menores.",
      "import.format": "Formato não reconhecido. Use uma planilha do Excel (.xlsx) ou um arquivo CSV.",
      "import.unreadable": "Não foi possível ler o arquivo. Salve-o de novo como .xlsx ou CSV e tente outra vez.",
      "import.empty": "A planilha está vazia.",
      "import.missingColumns": "Faltam colunas obrigatórias na primeira linha: {columns}. Use a planilha exportada como modelo.",
      "import.tooManyRows": "A planilha tem mais de {max} linhas. Divida-a em partes menores.",
      "import.gtinScientific": "o GTIN “{value}” foi convertido pelo Excel em notação científica. Formate a coluna GTIN como Texto e digite o código de novo.",
      "import.yesNo": "“{value}” não é um valor aceito nas colunas Principal ou Repassar parâmetros. Use sim ou não.",
      "import.descriptionConflict": "as linhas {rows} são do mesmo cadastro, mas têm descrições diferentes.",
      "import.defaultMany": "mais de um destino marcado como principal no mesmo cadastro (linhas {rows}).",
      "import.defaultConflict": "o destino principal deste GTIN é {linkType} na linha {row}; todos os cadastros do mesmo GTIN precisam usar o mesmo tipo.",
      "import.expired": "A verificação expirou. Escolha o arquivo de novo.",
      "import.alreadyApplied": "Esta planilha já foi importada.",
      "import.err.link.typeRequired": "tipo de link ausente ou desconhecido. Use um código da aba “Tipos de link”, como gs1:pip.",
      "import.err.link.urlRequired": "a URL está vazia.",
      "import.err.link.urlInvalid": "o endereço “{url}” não é válido. Use um endereço completo que comece com https://",
      "import.err.link.languageRequired": "idioma inválido. Use os códigos da aba “Idiomas”, como pt ou en.",
      "import.err.link.duplicate": "as linhas {first} e {second} têm o mesmo tipo de link e o mesmo idioma.",
      "import.err.description.required": "falta a descrição do produto.",
      "import.err.links.tooMany": "o cadastro tem mais de {max} destinos.",
      "menu.account": "Conta do usuário",
      "menu.signedInAs": "Conectado como",
      "menu.options": "Opções",
      "menu.logout": "Sair",
      "options.title": "Opções",
      "options.close": "Fechar",
      "options.cancel": "Cancelar",
      "password.title": "Alterar senha",
      "password.current": "Senha atual",
      "password.new": "Nova senha",
      "password.confirm": "Repita a nova senha",
      "password.hint": "Pelo menos {min} caracteres. As outras sessões abertas com esta conta serão encerradas.",
      "password.save": "Salvar senha",
      "password.missing": "Preencha a senha atual e a nova senha.",
      "password.mismatch": "As duas digitações da nova senha não conferem.",
      "password.tooShort": "A nova senha precisa ter pelo menos {min} caracteres.",
      "password.sameAsCurrent": "A nova senha deve ser diferente da atual.",
      "password.currentWrong": "A senha atual está incorreta.",
      "password.storeReadOnly": "O servidor não conseguiu gravar a nova senha. Avise o administrador.",
      "password.changed": "Senha alterada. As outras sessões desta conta foram encerradas.",
      "login.pageTitle": "Entrar | GS1 Resolver Community Edition",
      "login.heroTitle": "GS1 Resolver Community Edition",
      "login.heroLede": "Gerencie para onde levam os QR Codes GS1 Digital Link dos seus produtos.",
      "login.title": "Entrar",
      "login.username": "Usuário",
      "login.password": "Senha",
      "login.submit": "Entrar",
      "login.submitting": "Entrando…",
      "login.help": "Não tem acesso ou esqueceu a senha? Fale com o administrador do Resolver.",
      "login.missing": "Informe o usuário e a senha.",
      "login.expired": "Sua sessão terminou. Entre novamente.",
      "login.signedOut": "Você saiu do portal.",
      "login.passwordChanged": "Senha alterada. Entre com a nova senha.",
      "auth.invalid": "Usuário ou senha incorretos.",
      "auth.locked": "Muitas tentativas sem sucesso. Tente de novo em {minutes} minuto(s).",
      "auth.required": "Sua sessão terminou. Entre novamente.",
      "auth.welcome": "Bem-vindo.",
      "auth.loggedOut": "Você saiu do portal.",
      "intro.title": "Para onde o código do seu produto leva",
      "intro.lede": "Quem escanear o QR Code da embalagem será levado aos endereços que você cadastrar aqui. Você pode trocar os destinos quando quiser, sem reimprimir a embalagem.",

      "step1.title": "Qual produto?",
      "gtin.label": "Código de barras (GTIN)",
      "gtin.placeholder": "Ex.: 7891234567895",
      "gtin.hint": "Os números que aparecem embaixo do código de barras.",
      "gtin.valid": "Código válido.",
      "gtin.typedLength": "{length} dígitos digitados. O GTIN tem 8, 12, 13 ou 14.",
      "scope.legend": "Estes links valem para",
      "scope.product": "Todas as unidades deste produto",
      "scope.lot": "Somente um lote",
      "lot.label": "Número do lote",
      "lot.placeholder": "Ex.: L2026A",
      "lot.hint": "Letras sem acento, números, ponto, hífen ou sublinhado. Até 20 caracteres.",
      "lot.required": "Informe o número do lote.",
      "open.button": "Abrir cadastro",
      "open.loading": "Consultando o Resolver…",
      "open.found": "Cadastro encontrado. Altere o que precisar e salve.",
      "open.new": "Ainda não há cadastro. Preencha os passos abaixo.",
      "open.others": "Este GTIN também tem: {entries}.",
      "open.changed": "Você mudou o código. Clique em Abrir cadastro para ver os destinos dele.",
      "entry.product": "Produto (todos os lotes)",
      "entry.lot": "Lote {value}",
      "entry.other": "Outro cadastro {value}",

      "step2.title": "Nome do produto",
      "description.label": "Como o produto é chamado",
      "description.placeholder": "Ex.: Seringa descartável 5 ml",

      "step3.title": "Destinos",
      "links.hint": "Cada destino é uma página ou documento na internet. O primeiro é o que abre quando alguém escaneia o código (gs1:defaultLink). Os demais ficam disponíveis para aplicativos que pedirem um tipo específico. Se tiver versões em outros idiomas, cadastre uma linha para cada.",
      "links.add": "Adicionar destino",
      "links.minOne": "O produto precisa de pelo menos um destino. Para tirar tudo, use Excluir este cadastro.",
      "link.defaultBadge": "Destino principal",
      "link.type": "Tipo",
      "link.language": "Idioma",
      "link.url": "Endereço (URL)",
      "link.urlPlaceholder": "https://www.suamarca.com.br/produto",
      "link.title": "Título",
      "link.optional": "(opcional)",
      "link.forward": "Repassar os parâmetros do endereço para este destino",
      "link.forwardHint": "Ex.: quem acessar ?linkType=gs1:pip chega em destino?linkType=gs1:pip. Desmarque para enviar só o endereço cadastrado.",
      "link.makeDefault": "Tornar principal",
      "link.remove": "Remover",
      "link.removeAria": "Remover este destino",
      "default.shared": "Tipo do destino principal compartilhado com os outros cadastros deste GTIN: {linkType}.",
      "default.sharedLocal": "Este GTIN tem outros cadastros (produto ou lotes) cujo destino principal é do tipo {linkType}. O primeiro destino precisa ser desse tipo.",

      "save.button": "Salvar links",
      "save.saving": "Salvando…",
      "delete.button": "Excluir este cadastro",
      "delete.confirm": "Excluir o cadastro de {target}?\n\nQuem escanear o código deixará de ser levado a estes destinos.",
      "delete.targetLot": "o lote {lot} do GTIN {gtin}",
      "delete.targetGtin": "o GTIN {gtin} (inclusive os cadastros por lote)",

      "preview.aria": "Prévia do código",
      "preview.qrPlaceholder": "O QR Code aparece quando o GTIN estiver correto.",
      "preview.qrAlt": "QR Code do endereço {uri}",
      "preview.dlAria": "Abrir o endereço GS1 Digital Link",
      "legend.host": "Endereço do Resolver",
      "legend.hostHelp": "onde as regras ficam guardadas",
      "legend.key": "01 + GTIN",
      "legend.keyHelp": "identifica o produto",
      "legend.lot": "10 + lote",
      "legend.lotHelp": "restringe a um lote",
      "state.live": "Publicado",
      "state.draft": "Ainda não cadastrado",
      "preview.test": "Testar o link",
      "preview.copy": "Copiar endereço",
      "preview.copied": "Endereço copiado",
      "preview.png": "Baixar PNG",
      "preview.svg": "Baixar SVG",
      "label.options": "Opções da etiqueta",
      "label.hri": "Texto legível (HRI) abaixo do código",
      "label.brand": "Marca GS1® (piloto)",
      "label.brandHint": "“GS1®” acima do canto superior esquerdo, conforme as diretrizes QR Codes powered by GS1.",

      "error.network": "Sem conexão com o servidor. Verifique a internet e tente de novo.",
      "error.unexpected": "Erro inesperado (código {status}).",
      "error.config": "Não foi possível carregar o portal: {detail}",

      "gtin.required": "Informe o código de barras (GTIN) do produto.",
      "gtin.digitsOnly": "O GTIN deve conter apenas números.",
      "gtin.length": "O GTIN tem {length} dígitos. Os tamanhos válidos são 8, 12, 13 ou 14.",
      "gtin.checkDigit": "O último dígito não confere: para este código ele deveria ser {expected}.",
      "gtin.restricted": "Códigos que começam com 2 são de uso interno de loja e não podem ser publicados no Resolver.",
      "lot.invalid": "O lote aceita até 20 caracteres: letras sem acento, números, ponto, hífen e sublinhado.",
      "description.required": "Informe o nome do produto.",
      "description.tooLong": "O nome do produto deve ter no máximo {max} caracteres.",
      "links.required": "Cadastre pelo menos um destino.",
      "links.tooMany": "O limite é de {max} destinos por cadastro.",
      "link.typeRequired": "Escolha o tipo do destino {position}.",
      "link.urlRequired": "Preencha o endereço (URL) do destino {position}.",
      "link.urlInvalid": "O endereço “{url}” não é válido. Use um endereço completo que comece com https://",
      "link.languageRequired": "Escolha o idioma do destino {position}.",
      "link.duplicate": "Os destinos {first} e {second} têm o mesmo tipo e idioma. Troque o idioma de um deles ou remova um.",
      "default.required": "Escolha qual destino abre primeiro quando alguém escanear o código.",
      "default.sharedMismatch": "Este GTIN tem outros cadastros ({entries}) que abrem primeiro em {linkType}. O destino principal vale para todos: mantenha esse tipo no primeiro destino.",
      "record.notFound": "Não há cadastro para este código.",
      "request.forbiddenOrigin": "Origem não autorizada.",
      "request.jsonRequired": "Envie os dados em JSON.",
      "upstream.unavailable": "O Resolver não respondeu. Tente novamente em alguns minutos.",
      "upstream.unauthorised": "O portal não tem autorização no Resolver. Avise o administrador (token de acesso incorreto).",
      "upstream.readFailed": "Não foi possível ler o cadastro atual no Resolver.",
      "upstream.createRejected": "O Resolver recusou o cadastro.",
      "upstream.updateRejected": "O Resolver recusou a atualização.",
      "upstream.partialUpdate": "Os destinos novos foram salvos, mas {count} destino(s) antigo(s) não puderam ser removidos. Tente salvar de novo.",
      "upstream.deleteFailed": "O Resolver não conseguiu excluir o cadastro.",
      "upstream.deleteRestored": "A exclusão falhou e o cadastro original foi restaurado.",
      "save.created": "Cadastro criado. O código já leva aos destinos informados.",
      "save.updated": "Alterações salvas. O código já leva aos novos destinos.",
      "delete.done": "Cadastro excluído. O código deixou de levar a estes destinos.",

      "group.common": "Mais usados",
      "group.health": "Saúde",
      "group.aftersales": "Uso e pós-venda",
      "group.consumer": "Consumidor",
      "group.food": "Alimentos",
      "group.b2b": "Entre empresas",
      "linkTypes": {
        "gs1:pip": ["Página do produto", "Página com informações gerais do produto no site da marca."],
        "gs1:instructions": ["Instruções de uso", "Manual, modo de usar, montagem."],
        "gs1:support": ["Atendimento (SAC)", "Canal de suporte: telefone, chat, e-mail."],
        "gs1:certificationInfo": ["Certificados e conformidade", "Certificados, registros e documentos de conformidade regulatória."],
        "gs1:safetyInfo": ["Informações de segurança", "Advertências, riscos e cuidados."],
        "gs1:epil": ["Bula eletrônica (paciente)", "Informações ao paciente em formato eletrônico."],
        "gs1:smpc": ["Informações ao profissional de saúde", "Bula do profissional / características do produto."],
        "gs1:recallStatus": ["Situação de recolhimento (recall)", "Informa se o produto foi recolhido."],
        "gs1:quickStartGuide": ["Guia rápido", "O essencial para começar a usar."],
        "gs1:tutorial": ["Tutoriais", "Aulas e vídeos de como fazer."],
        "gs1:relatedVideo": ["Vídeo do produto", "Qualquer vídeo sobre o produto."],
        "gs1:serviceInfo": ["Manutenção e assistência técnica", "Instruções de manutenção e rede autorizada."],
        "gs1:whatsInTheBox": ["Conteúdo da embalagem", "O que vem dentro da caixa."],
        "gs1:faqs": ["Perguntas frequentes", "Dúvidas comuns sobre o produto."],
        "gs1:registerProduct": ["Registrar produto ou garantia", "Cadastro do comprador para garantia."],
        "gs1:purchaseSuppliesOrAccessories": ["Comprar acessórios e refis", "Onde comprar peças, refis e acessórios."],
        "gs1:promotion": ["Promoção", "Campanha ou promoção vigente."],
        "gs1:hasRetailers": ["Onde comprar", "Lista de lojas que vendem o produto."],
        "gs1:review": ["Avaliações", "Avaliações de outros compradores."],
        "gs1:leaveReview": ["Deixar uma avaliação", "Página para o consumidor avaliar."],
        "gs1:socialMedia": ["Redes sociais", "Perfil da marca em rede social."],
        "gs1:sustainabilityInfo": ["Sustentabilidade e reciclagem", "Descarte, reciclagem e impacto ambiental."],
        "gs1:nutritionalInfo": ["Informação nutricional", "Tabela nutricional."],
        "gs1:ingredientsInfo": ["Ingredientes", "Lista de ingredientes."],
        "gs1:allergenInfo": ["Alergênicos", "Informações sobre alergênicos."],
        "gs1:recipeInfo": ["Receitas", "Receitas que usam o produto."],
        "gs1:masterData": ["Dados cadastrais (B2B)", "Dados estruturados do produto para parceiros comerciais."],
        "gs1:traceability": ["Rastreabilidade", "Informações de rastreamento do produto."],
        "gs1:epcis": ["Repositório EPCIS", "Endpoint de eventos EPCIS."]
      }
    },

    "en-GB": {
      "locale.name": "English (UK)",
      "app.title": "Product links | GS1 Resolver Community Edition",
      "header.language": "Language",
      "header.home": "Resolver home page",
      "menu.home": "Home page",
      "menu.records": "Registered records",
      "records.title": "Registered records",
      "records.lede": "Every product and batch published on this resolver. Search and select a record to edit it.",
      "records.link": "See registered records →",
      "records.back": "← Back to the editor",
      "records.search": "Search records",
      "records.searchPlaceholder": "Search by GTIN, description or batch",
      "records.changedBy": "Changed by",
      "records.anyone": "Anyone",
      "records.new": "New record",
      "records.col.product": "Product",
      "records.col.gtin": "GTIN",
      "records.col.scope": "Applies to",
      "records.col.links": "Links",
      "records.col.changed": "Last change",
      "records.scope.product": "Every unit",
      "records.scope.lot": "Batch {value}",
      "records.scope.other": "Other qualifiers: {value}",
      "records.otherHint": "Created outside the portal with qualifiers the portal does not edit; change it through the API.",
      "records.noDescription": "(no description)",
      "records.noHistory": "no history",
      "records.loading": "Loading records…",
      "records.count": "Records: {shown} of {total}",
      "records.none": "No records yet.",
      "records.noMatch": "No record matches the search.",
      "records.exportXlsx": "Export spreadsheet (Excel)",
      "records.exportCsv": "Export CSV",
      "records.import": "Import spreadsheet",
      "sheet.col.gtin": "GTIN",
      "sheet.col.lot": "Batch/lot",
      "sheet.col.description": "Description",
      "sheet.col.linkType": "Link type",
      "sheet.col.url": "URL",
      "sheet.col.language": "Language",
      "sheet.col.title": "Title",
      "sheet.col.default": "Default",
      "sheet.col.forward": "Forward query string",
      "sheet.yes": "yes",
      "sheet.no": "no",
      "sheet.links": "Links",
      "sheet.linkTypes": "Link types",
      "sheet.languages": "Languages",
      "sheet.code": "Code",
      "sheet.name": "Name",
      "sheet.description": "Description",
      "import.title": "Import spreadsheet",
      "import.intro": "Use the layout of the exported spreadsheet: one row per target; rows with the same GTIN and batch form one record, and the Default column marks the target that opens first. Existing records are replaced by the spreadsheet's content; records not in it do not change. Nothing is saved before you confirm.",
      "import.file": "File (Excel .xlsx or CSV)",
      "import.checking": "Checking the spreadsheet…",
      "import.summary": "New: {create} · Changed: {update} · Unchanged: {unchanged} · With errors: {error}",
      "import.col.rows": "Rows",
      "import.col.result": "Result",
      "import.action.create": "New",
      "import.action.update": "Changed",
      "import.action.unchanged": "Unchanged",
      "import.action.error": "Error",
      "import.action.created": "Created",
      "import.action.updated": "Updated",
      "import.action.failed": "Failed",
      "import.row": "Row {row}:",
      "import.apply": "Import records ({count})",
      "import.errorsSkipped": "Records with errors will be skipped; correct the spreadsheet and import it again to include them.",
      "import.running": "Importing… {done} of {total}",
      "import.done": "Import finished. Created: {created} · Updated: {updated} · Failed: {failed}",
      "import.close": "Close",
      "import.tooBig": "The file is larger than {max} KB. Split the spreadsheet into smaller parts.",
      "import.format": "Format not recognised. Use an Excel spreadsheet (.xlsx) or a CSV file.",
      "import.unreadable": "The file could not be read. Save it again as .xlsx or CSV and retry.",
      "import.empty": "The spreadsheet is empty.",
      "import.missingColumns": "Required columns are missing from the first row: {columns}. Use the exported spreadsheet as a template.",
      "import.tooManyRows": "The spreadsheet has more than {max} rows. Split it into smaller parts.",
      "import.gtinScientific": "Excel turned the GTIN “{value}” into scientific notation. Format the GTIN column as Text and type the code again.",
      "import.yesNo": "“{value}” is not accepted in the Default or Forward query string columns. Use yes or no.",
      "import.descriptionConflict": "rows {rows} belong to the same record but have different descriptions.",
      "import.defaultMany": "more than one target marked as default in the same record (rows {rows}).",
      "import.defaultConflict": "this GTIN's default target is {linkType} on row {row}; every record of the same GTIN must use the same type.",
      "import.expired": "The check has expired. Choose the file again.",
      "import.alreadyApplied": "This spreadsheet has already been imported.",
      "import.err.link.typeRequired": "missing or unknown link type. Use a code from the “Link types” sheet, such as gs1:pip.",
      "import.err.link.urlRequired": "the URL is empty.",
      "import.err.link.urlInvalid": "“{url}” is not a valid address. Use a full address starting with https://",
      "import.err.link.languageRequired": "invalid language. Use the codes from the “Languages” sheet, such as pt or en.",
      "import.err.link.duplicate": "rows {first} and {second} have the same link type and language.",
      "import.err.description.required": "the product description is missing.",
      "import.err.links.tooMany": "the record has more than {max} targets.",
      "menu.account": "User account",
      "menu.signedInAs": "Signed in as",
      "menu.options": "Options",
      "menu.logout": "Sign out",
      "options.title": "Options",
      "options.close": "Close",
      "options.cancel": "Cancel",
      "password.title": "Change password",
      "password.current": "Current password",
      "password.new": "New password",
      "password.confirm": "Repeat the new password",
      "password.hint": "At least {min} characters. Any other open sessions for this account will be signed out.",
      "password.save": "Save password",
      "password.missing": "Enter your current password and the new one.",
      "password.mismatch": "The two entries of the new password do not match.",
      "password.tooShort": "The new password must be at least {min} characters long.",
      "password.sameAsCurrent": "The new password must differ from the current one.",
      "password.currentWrong": "The current password is incorrect.",
      "password.storeReadOnly": "The server could not store the new password. Please tell the administrator.",
      "password.changed": "Password changed. Other sessions for this account have been signed out.",
      "login.pageTitle": "Sign in | GS1 Resolver Community Edition",
      "login.heroTitle": "GS1 Resolver Community Edition",
      "login.heroLede": "Manage where your products' GS1 Digital Link QR codes lead.",
      "login.title": "Sign in",
      "login.username": "Username",
      "login.password": "Password",
      "login.submit": "Sign in",
      "login.submitting": "Signing in…",
      "login.help": "No access, or forgotten your password? Contact the resolver administrator.",
      "login.missing": "Enter your username and password.",
      "login.expired": "Your session has ended. Please sign in again.",
      "login.signedOut": "You have signed out.",
      "login.passwordChanged": "Password changed. Sign in with the new password.",
      "auth.invalid": "Incorrect username or password.",
      "auth.locked": "Too many unsuccessful attempts. Try again in {minutes} minute(s).",
      "auth.required": "Your session has ended. Please sign in again.",
      "auth.welcome": "Welcome.",
      "auth.loggedOut": "You have signed out.",
      "intro.title": "Where your product's code takes people",
      "intro.lede": "Anyone who scans the QR code on the pack will be taken to the addresses you register here. You can change the targets whenever you like without reprinting the packaging.",

      "step1.title": "Which product?",
      "gtin.label": "Barcode number (GTIN)",
      "gtin.placeholder": "e.g. 7891234567895",
      "gtin.hint": "The digits printed beneath the barcode.",
      "gtin.valid": "Valid code.",
      "gtin.typedLength": "{length} digits entered. A GTIN has 8, 12, 13 or 14.",
      "scope.legend": "These links apply to",
      "scope.product": "Every unit of this product",
      "scope.lot": "One batch/lot only",
      "lot.label": "Batch/lot number",
      "lot.placeholder": "e.g. L2026A",
      "lot.hint": "Unaccented letters, digits, full stop, hyphen or underscore. Up to 20 characters.",
      "lot.required": "Enter the batch/lot number.",
      "open.button": "Open record",
      "open.loading": "Querying the resolver…",
      "open.found": "Record found. Change whatever you need and save.",
      "open.new": "No record yet. Complete the steps below.",
      "open.others": "This GTIN also has: {entries}.",
      "open.changed": "You changed the code. Select Open record to see its targets.",
      "entry.product": "Product (all batches)",
      "entry.lot": "Batch/lot {value}",
      "entry.other": "Other record {value}",

      "step2.title": "Product name",
      "description.label": "What the product is called",
      "description.placeholder": "e.g. Disposable syringe 5 ml",

      "step3.title": "Targets",
      "links.hint": "Each target is a web page or document. The first one opens when someone scans the code (gs1:defaultLink). The others remain available to applications that ask for a specific type. If you have versions in other languages, add one row for each.",
      "links.add": "Add target",
      "links.minOne": "The product needs at least one target. To remove everything, use Delete this record.",
      "link.defaultBadge": "Default target",
      "link.type": "Type",
      "link.language": "Language",
      "link.url": "Address (URL)",
      "link.urlPlaceholder": "https://www.yourbrand.com/product",
      "link.title": "Title",
      "link.optional": "(optional)",
      "link.forward": "Pass the request's query parameters on to this target",
      "link.forwardHint": "e.g. a request with ?linkType=gs1:pip arrives at target?linkType=gs1:pip. Untick to send only the registered address.",
      "link.makeDefault": "Make default",
      "link.remove": "Remove",
      "link.removeAria": "Remove this target",
      "default.shared": "Default target type shared with the other records for this GTIN: {linkType}.",
      "default.sharedLocal": "This GTIN has other records (product or batches) whose default target is of type {linkType}. The first target must be of that type.",

      "save.button": "Save links",
      "save.saving": "Saving…",
      "delete.button": "Delete this record",
      "delete.confirm": "Delete the record for {target}?\n\nPeople scanning the code will no longer be taken to these targets.",
      "delete.targetLot": "batch/lot {lot} of GTIN {gtin}",
      "delete.targetGtin": "GTIN {gtin} (including its batch/lot records)",

      "preview.aria": "Code preview",
      "preview.qrPlaceholder": "The QR code appears once the GTIN is correct.",
      "preview.qrAlt": "QR code for {uri}",
      "preview.dlAria": "Open the GS1 Digital Link address",
      "legend.host": "Resolver address",
      "legend.hostHelp": "where the rules are kept",
      "legend.key": "01 + GTIN",
      "legend.keyHelp": "identifies the product",
      "legend.lot": "10 + batch/lot",
      "legend.lotHelp": "narrows it to one batch",
      "state.live": "Published",
      "state.draft": "Not yet registered",
      "preview.test": "Try now",
      "preview.copy": "Copy link address",
      "preview.copied": "Link address copied",
      "preview.png": "Download PNG",
      "preview.svg": "Download SVG",
      "label.options": "Label options",
      "label.hri": "Human readable text (HRI) below the code",
      "label.brand": "GS1® branding (pilot)",
      "label.brandHint": "“GS1®” above the top-left corner, as set out in the QR Codes powered by GS1 guidelines.",

      "error.network": "Cannot reach the server. Check your connection and try again.",
      "error.unexpected": "Unexpected error (code {status}).",
      "error.config": "The portal could not be loaded: {detail}",

      "gtin.required": "Enter the product's barcode number (GTIN).",
      "gtin.digitsOnly": "The GTIN must contain digits only.",
      "gtin.length": "The GTIN has {length} digits. Valid lengths are 8, 12, 13 or 14.",
      "gtin.checkDigit": "The last digit does not match: for this code it should be {expected}.",
      "gtin.restricted": "Codes starting with 2 are for in-store use only and cannot be published on the resolver.",
      "lot.invalid": "The batch/lot accepts up to 20 characters: unaccented letters, digits, full stop, hyphen and underscore.",
      "description.required": "Enter the product name.",
      "description.tooLong": "The product name must be at most {max} characters.",
      "links.required": "Add at least one target.",
      "links.tooMany": "The limit is {max} targets per record.",
      "link.typeRequired": "Choose the type of target {position}.",
      "link.urlRequired": "Enter the address (URL) of target {position}.",
      "link.urlInvalid": "The address “{url}” is not valid. Use a full address starting with https://",
      "link.languageRequired": "Choose the language of target {position}.",
      "link.duplicate": "Targets {first} and {second} have the same type and language. Change the language of one of them or remove one.",
      "default.required": "Choose which target opens first when someone scans the code.",
      "default.sharedMismatch": "This GTIN has other records ({entries}) that open {linkType} first. The default target applies to all of them: keep that type as the first target.",
      "record.notFound": "There is no record for this code.",
      "request.forbiddenOrigin": "Origin not authorised.",
      "request.jsonRequired": "Send the data as JSON.",
      "upstream.unavailable": "The resolver did not respond. Please try again in a few minutes.",
      "upstream.unauthorised": "The portal is not authorised on the resolver. Tell the administrator (incorrect access token).",
      "upstream.readFailed": "The current record could not be read from the resolver.",
      "upstream.createRejected": "The resolver rejected the record.",
      "upstream.updateRejected": "The resolver rejected the update.",
      "upstream.partialUpdate": "The new targets were saved, but {count} old target(s) could not be removed. Please save again.",
      "upstream.deleteFailed": "The resolver could not delete the record.",
      "upstream.deleteRestored": "The deletion failed and the original record was restored.",
      "save.created": "Record created. The code now leads to the targets you entered.",
      "save.updated": "Changes saved. The code now leads to the new targets.",
      "delete.done": "Record deleted. The code no longer leads to these targets.",

      "group.common": "Most used",
      "group.health": "Healthcare",
      "group.aftersales": "Use and after-sales",
      "group.consumer": "Consumer",
      "group.food": "Food",
      "group.b2b": "Business to business",
      "linkTypes": {
        "gs1:pip": ["Product information page", "A page with general information about the product on the brand's website."],
        "gs1:instructions": ["Instructions", "Manual, directions for use, assembly."],
        "gs1:support": ["Customer support", "Support channel: telephone, chat, e-mail."],
        "gs1:certificationInfo": ["Certification and compliance", "Certificates, registrations and regulatory compliance documents."],
        "gs1:safetyInfo": ["Safety information", "Warnings, hazards and precautions."],
        "gs1:epil": ["Electronic patient information leaflet", "Patient information in electronic form."],
        "gs1:smpc": ["Information for healthcare professionals", "Summary of product characteristics."],
        "gs1:recallStatus": ["Recall status", "States whether the product has been recalled."],
        "gs1:quickStartGuide": ["Quick start guide", "The essentials to start using it."],
        "gs1:tutorial": ["Tutorials", "Lessons and how-to videos."],
        "gs1:relatedVideo": ["Product video", "Any video about the product."],
        "gs1:serviceInfo": ["Servicing and maintenance", "Maintenance instructions and authorised service centres."],
        "gs1:whatsInTheBox": ["What's in the box", "Everything included in the pack."],
        "gs1:faqs": ["Frequently asked questions", "Common questions about the product."],
        "gs1:registerProduct": ["Register product or warranty", "Purchaser registration for the warranty."],
        "gs1:purchaseSuppliesOrAccessories": ["Buy accessories and refills", "Where to buy parts, refills and accessories."],
        "gs1:promotion": ["Promotion", "A current campaign or promotion."],
        "gs1:hasRetailers": ["Where to buy", "Shops that sell the product."],
        "gs1:review": ["Reviews", "Reviews from other buyers."],
        "gs1:leaveReview": ["Leave a review", "A page where customers can post a review."],
        "gs1:socialMedia": ["Social media", "The brand's social media profile."],
        "gs1:sustainabilityInfo": ["Sustainability and recycling", "Disposal, recycling and environmental impact."],
        "gs1:nutritionalInfo": ["Nutritional information", "Nutrition facts."],
        "gs1:ingredientsInfo": ["Ingredients", "List of ingredients."],
        "gs1:allergenInfo": ["Allergens", "Allergen information."],
        "gs1:recipeInfo": ["Recipes", "Recipes using the product."],
        "gs1:masterData": ["Master data (B2B)", "Structured product data for trading partners."],
        "gs1:traceability": ["Traceability", "Product tracking information."],
        "gs1:epcis": ["EPCIS repository", "EPCIS event endpoint."]
      }
    }
  };

  let locale = DEFAULT_LOCALE;

  function detect() {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (SUPPORTED.includes(saved)) return saved;
    } catch { /* storage unavailable: fall back to the cookie and browser languages */ }
    const cookie = document.cookie.split("; ").find(c => c.startsWith(COOKIE_NAME + "="));
    if (cookie && SUPPORTED.includes(decodeURIComponent(cookie.split("=")[1]))) return decodeURIComponent(cookie.split("=")[1]);
    for (const tag of navigator.languages || [navigator.language || ""]) {
      const lower = String(tag).toLowerCase();
      const match = LOCALE_MATCHERS.find(([prefix]) => lower === prefix || lower.startsWith(prefix + "-"));
      if (match) return match[1];
    }
    return DEFAULT_LOCALE;
  }

  function lookup(key, loc = locale) {
    return CATALOGUE[loc][key] ?? CATALOGUE[DEFAULT_LOCALE][key];
  }

  function t(key, params = {}) {
    const template = lookup(key);
    if (typeof template !== "string") return key;
    return template.replace(/\{(\w+)\}/g, (_, name) => (name in params ? String(params[name]) : `{${name}}`));
  }

  function linkType(code) {
    return lookup("linkTypes")[code] || CATALOGUE[DEFAULT_LOCALE].linkTypes[code] || [code, ""];
  }

  function linkTypeOption(code) {
    const [label] = linkType(code);
    return label === code ? code : `${code} — ${label}`;
  }

  function languageName(tag) {
    try {
      const name = new Intl.DisplayNames([locale], { type: "language" }).of(tag);
      return name ? name.charAt(0).toLocaleUpperCase(locale) + name.slice(1) : tag;
    } catch {
      return tag;
    }
  }

  /* Sets translatable text on an element and remembers the key so apply() can re-render it. */
  function set(el, key, params) {
    if (!el) return;
    if (key == null) {
      delete el.dataset.i18n;
      delete el.dataset.i18nParams;
      el.textContent = "";
      return;
    }
    el.dataset.i18n = key;
    if (params && Object.keys(params).length) el.dataset.i18nParams = JSON.stringify(params);
    else delete el.dataset.i18nParams;
    el.textContent = t(key, resolveParams(params || {}));
  }

  function apply(root = document) {
    document.documentElement.lang = locale;
    document.title = t(document.body.dataset.titleKey || "app.title");
    root.querySelectorAll("[data-i18n]").forEach(el => {
      const params = el.dataset.i18nParams ? JSON.parse(el.dataset.i18nParams) : {};
      el.textContent = t(el.dataset.i18n, resolveParams(params));
    });
    root.querySelectorAll("[data-i18n-attr]").forEach(el => {
      el.dataset.i18nAttr.split(";").forEach(pair => {
        const [attr, key] = pair.split(":");
        if (attr && key) el.setAttribute(attr.trim(), t(key.trim()));
      });
    });
    root.querySelectorAll("[data-i18n-type]").forEach(el => { el.textContent = linkTypeOption(el.dataset.i18nType); });
    root.querySelectorAll("[data-i18n-group]").forEach(el => { el.label = t("group." + el.dataset.i18nGroup); });
    root.querySelectorAll("[data-i18n-lang]").forEach(el => { el.textContent = languageName(el.dataset.i18nLang); });
  }

  /* Parameters that are themselves translatable (link types, record descriptions) are re-resolved
     on every render, so a message stays correct after the language changes. */
  function resolveParams(params) {
    const out = { ...params };
    if (typeof out.linkType === "string") out.linkType = linkTypeOption(out.linkType);
    if (Array.isArray(out.entries)) {
      out.entries = out.entries.map(e => t("entry." + e.kind, { value: e.value ?? "" })).join(", ");
    }
    return out;
  }

  function setLocale(next) {
    if (!SUPPORTED.includes(next)) return;
    locale = next;
    try { localStorage.setItem(STORAGE_KEY, next); } catch { /* not persisted */ }
    document.cookie = `${COOKIE_NAME}=${encodeURIComponent(next)}; path=/; max-age=31536000; SameSite=Lax` +
      (location.protocol === "https:" ? "; Secure" : "");
    apply();
    document.dispatchEvent(new CustomEvent("localechange", { detail: next }));
  }

  locale = detect();

  return {
    SUPPORTED,
    get locale() { return locale; },
    t: (key, params) => t(key, resolveParams(params || {})),
    set: (el, key, params) => set(el, key, params),
    apply, setLocale, linkType, linkTypeOption, languageName,
    nameOf: loc => CATALOGUE[loc]["locale.name"],
    // The same message in every locale (e.g. spreadsheet headers accepted in any language).
    every: key => SUPPORTED.map(loc => CATALOGUE[loc][key]).filter(v => typeof v === "string"),
    has: key => typeof CATALOGUE[locale][key] === "string",
  };
})();
