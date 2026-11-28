"""
Texts of the portal's e-mail messages (Documentation/adr/0004-e-mail.md, decision 8): British English and Brazilian
Portuguese here, the other languages of the interface (Documentation/adr/0014-interface-languages.md) in
mail_languages.json, in the same form ({language: {"signature": …, "texts": {message: [subject, body]}}}).

Each message has a subject and a plain text per language, with {placeholders} filled in by compose(). Every
message ends with the same signature: the operator's name (RESOLVER_ORG_NAME) and the portal's address. The HTML
alternative is made from the plain text (escaped, paragraphs, links made clickable), so the two never differ.

The development tests check that every language has the same messages with the same placeholders
(dev-tests/portal/test_mail.py, test_i18n.py). A new message needs every language and a category in notify.TEMPLATES.
"""
import html
import json
import os
import re
import string

LANGUAGES = ("en-GB", "pt-BR")
DEFAULT_LANGUAGE = "en-GB"

SIGNATURE = {
    "en-GB": "—\n{operator}\nLink management portal: {portal}\n\n"
             "This message was sent automatically by the GS1 Digital Link resolver of {operator}. "
             "Please do not reply to it.",
    "pt-BR": "—\n{operator}\nPortal de gestão de links: {portal}\n\n"
             "Esta mensagem foi enviada automaticamente pelo resolver GS1 Digital Link de {operator}. "
             "Por favor, não responda.",
}

TEXTS = {
    "invite": {
        "en-GB": ("Your account in the link management portal",
                  "Hello,\n\n"
                  "An account was created for you in the link management portal of {operator}, where the links "
                  "of GS1 Digital Link QR codes are managed.\n\n"
                  "User name: {user}\n\n"
                  "To choose your password and start, open this link within {hours} hours:\n\n"
                  "{link}\n\n"
                  "The link works once. If it has expired, ask your administrator to send a new invitation. If "
                  "you did not expect this message, you can ignore it."),
        "pt-BR": ("Sua conta no portal de gestão de links",
                  "Olá,\n\n"
                  "Uma conta foi criada para você no portal de gestão de links de {operator}, onde são geridos os "
                  "links dos QR codes GS1 Digital Link.\n\n"
                  "Nome de usuário: {user}\n\n"
                  "Para escolher a sua senha e começar, abra este link em até {hours} horas:\n\n"
                  "{link}\n\n"
                  "O link funciona uma vez. Se ele tiver expirado, peça ao seu administrador um novo convite. Se "
                  "você não esperava esta mensagem, pode ignorá-la."),
    },
    "password-recovery": {
        "en-GB": ("Choose a new password",
                  "Hello,\n\n"
                  "Someone asked to choose a new password for the user {user} in the link management portal. "
                  "If it was you, open this link within {minutes} minutes:\n\n"
                  "{link}\n\n"
                  "The link works once. If you did not ask for it, ignore this message: your password has not "
                  "changed and nobody can change it without this link."),
        "pt-BR": ("Escolha uma nova senha",
                  "Olá,\n\n"
                  "Alguém pediu para escolher uma nova senha para o usuário {user} no portal de gestão de links. "
                  "Se foi você, abra este link em até {minutes} minutos:\n\n"
                  "{link}\n\n"
                  "O link funciona uma vez. Se você não pediu, ignore esta mensagem: a sua senha não mudou e "
                  "ninguém pode mudá-la sem este link."),
    },
    "password-reset-admin": {
        "en-GB": ("Your password was reset",
                  "Hello,\n\n"
                  "An administrator reset the password of the user {user} in the link management portal. Your "
                  "previous password no longer works.\n\n"
                  "To choose a new one, open this link within {minutes} minutes:\n\n"
                  "{link}\n\n"
                  "The link works once. If it has expired, use \"Forgot your password?\" on the sign-in page."),
        "pt-BR": ("A sua senha foi redefinida",
                  "Olá,\n\n"
                  "Um administrador redefiniu a senha do usuário {user} no portal de gestão de links. A sua senha "
                  "anterior não funciona mais.\n\n"
                  "Para escolher uma nova, abra este link em até {minutes} minutos:\n\n"
                  "{link}\n\n"
                  "O link funciona uma vez. Se ele tiver expirado, use \"Esqueceu a senha?\" na página de acesso."),
    },
    "password-changed": {
        "en-GB": ("Your password was changed",
                  "Hello,\n\n"
                  "The password of the user {user} in the link management portal was changed on {when} (UTC). "
                  "Every other open session of the account was ended.\n\n"
                  "If it was you, there is nothing to do. If it was not, use \"Forgot your password?\" on the "
                  "sign-in page at once and tell your administrator."),
        "pt-BR": ("A sua senha foi trocada",
                  "Olá,\n\n"
                  "A senha do usuário {user} no portal de gestão de links foi trocada em {when} (UTC). Todas as "
                  "outras sessões abertas da conta foram encerradas.\n\n"
                  "Se foi você, não há nada a fazer. Se não foi, use \"Esqueceu a senha?\" na página de acesso "
                  "imediatamente e avise o seu administrador."),
    },
    "email-changed-old": {
        "en-GB": ("Your e-mail address was changed",
                  "Hello,\n\n"
                  "An administrator changed the e-mail address of the user {user} in the link management portal "
                  "on {when} (UTC). Messages about the account will no longer come to this address.\n\n"
                  "If you did not ask for the change, tell your administrator."),
        "pt-BR": ("O seu endereço de e-mail foi trocado",
                  "Olá,\n\n"
                  "Um administrador trocou o endereço de e-mail do usuário {user} no portal de gestão de links em "
                  "{when} (UTC). As mensagens sobre a conta não virão mais para este endereço.\n\n"
                  "Se você não pediu a troca, avise o seu administrador."),
    },
    "email-changed-new": {
        "en-GB": ("Your e-mail address in the link management portal",
                  "Hello,\n\n"
                  "This address is now the e-mail address of the user {user} in the link management portal. "
                  "Messages about the account (password changes, recovery links) will come here.\n\n"
                  "If you do not know this account, tell the portal's administrators."),
        "pt-BR": ("O seu endereço de e-mail no portal de gestão de links",
                  "Olá,\n\n"
                  "Este é agora o endereço de e-mail do usuário {user} no portal de gestão de links. As mensagens "
                  "sobre a conta (trocas de senha, links de recuperação) virão para cá.\n\n"
                  "Se você não conhece esta conta, avise os administradores do portal."),
    },
    "sign-in-failures": {
        "en-GB": ("Sign-in attempts to your account",
                  "Hello,\n\n"
                  "The user {user} could not sign in to the link management portal after several wrong "
                  "passwords in {minutes} minutes, the last on {when} (UTC).\n\n"
                  "The account is not locked: each address that keeps trying waits longer between attempts, so "
                  "you can still sign in from your own computer. If it was you, use \"Forgot your password?\" on "
                  "the sign-in page if you need to. If it was not, someone may be trying to guess your password: "
                  "tell your administrator."),
        "pt-BR": ("Tentativas de acesso à sua conta",
                  "Olá,\n\n"
                  "O usuário {user} não conseguiu entrar no portal de gestão de links depois de várias senhas "
                  "erradas em {minutes} minutos, a última em {when} (UTC).\n\n"
                  "A conta não está bloqueada: cada endereço que continua tentando espera cada vez mais entre as "
                  "tentativas, e você ainda pode entrar a partir do seu computador. Se foi você, use \"Esqueceu a "
                  "senha?\" na página de acesso, se precisar. Se não foi, alguém pode estar tentando adivinhar a "
                  "sua senha: avise o seu administrador."),
    },
    "api-key-created": {
        "en-GB": ("A new API key was created",
                  "Hello,\n\n"
                  "The user {user} created the API key \"{name}\" ({id}) for {scope} on {when} (UTC), with the "
                  "scopes {scopes}. It expires on {expires} (UTC).\n\n"
                  "Whoever holds the key can use the portal's API within those scopes until it expires or is revoked. "
                  "If you did not create it, revoke it at once in the portal (API keys) and tell your administrator."),
        "pt-BR": ("Uma nova chave de API foi criada",
                  "Olá,\n\n"
                  "O usuário {user} criou a chave de API \"{name}\" ({id}) para {scope} em {when} (UTC), com os "
                  "escopos {scopes}. Ela expira em {expires} (UTC).\n\n"
                  "Quem tem a chave pode usar a API do portal dentro desses escopos até ela expirar ou ser revogada. "
                  "Se não foi você que a criou, revogue-a imediatamente no portal (Chaves de API) e avise o seu "
                  "administrador."),
    },
    "api-key-expiring": {
        "en-GB": ("An API key expires soon",
                  "Hello,\n\n"
                  "The API key \"{name}\" ({id}) you created for {scope} expires on {expires} (UTC). The systems that "
                  "use it will then be refused.\n\n"
                  "To keep them working, create a new key in the portal (API keys), put it in those systems and "
                  "revoke the old one."),
        "pt-BR": ("Uma chave de API expira em breve",
                  "Olá,\n\n"
                  "A chave de API \"{name}\" ({id}) que você criou para {scope} expira em {expires} (UTC). Os "
                  "sistemas que a usam passarão a ser recusados.\n\n"
                  "Para mantê-los funcionando, crie uma chave nova no portal (Chaves de API), coloque-a nesses "
                  "sistemas e revogue a antiga."),
    },
    "import-finished": {
        "en-GB": ("Your import has finished",
                  "Hello,\n\n"
                  "The spreadsheet import you started in the link management portal has finished:\n\n"
                  "Records created: {created}\nRecords updated: {updated}\nRecords that failed: {failed}\n\n"
                  "The details are in the portal while the page stays open, and in the audit trail.\n\n"
                  "You receive this message because you chose it in Options → E-mail."),
        "pt-BR": ("A sua importação terminou",
                  "Olá,\n\n"
                  "A importação de planilha que você iniciou no portal de gestão de links terminou:\n\n"
                  "Cadastros criados: {created}\nCadastros atualizados: {updated}\nCadastros com falha: {failed}\n\n"
                  "Os detalhes estão no portal enquanto a página continuar aberta, e na trilha de auditoria.\n\n"
                  "Você recebe esta mensagem porque a escolheu em Opções → E-mail."),
    },
    "linkcheck-finished": {
        "en-GB": ("Your link check has finished",
                  "Hello,\n\n"
                  "The check of every record's links you started in the link management portal has finished: "
                  "{urls} addresses checked, {problems} with a problem.\n\n"
                  "The record list shows which records have problems.\n\n"
                  "You receive this message because you chose it in Options → E-mail."),
        "pt-BR": ("A sua verificação de links terminou",
                  "Olá,\n\n"
                  "A verificação dos links de todos os cadastros que você iniciou no portal de gestão de links "
                  "terminou: {urls} endereços verificados, {problems} com problema.\n\n"
                  "A lista de cadastros mostra quais cadastros têm problemas.\n\n"
                  "Você recebe esta mensagem porque a escolheu em Opções → E-mail."),
    },
    "alert-resolver-down": {
        "en-GB": ("Alert: the resolver is not answering",
                  "Hello,\n\n"
                  "The resolver of {operator} has not answered the portal's checks through the proxy since {since}. "
                  "Scans of GS1 Digital Link QR codes may be failing.\n\n"
                  "Address checked: {url}\nProblem: {problem}\n\n"
                  "On the server, \"docker compose ps\" shows which service is down and \"docker compose logs "
                  "--tail=50 web-service frontend-proxy-service\" why. You will receive a message when it answers "
                  "again, and a reminder every 24 hours meanwhile.\n\n"
                  "You receive this message as a server administrator; you can switch alerts off in Options → "
                  "E-mail."),
        "pt-BR": ("Alerta: o Resolver não está respondendo",
                  "Olá,\n\n"
                  "O Resolver de {operator} não responde às verificações do portal pelo proxy desde {since}. As "
                  "leituras de QR codes GS1 Digital Link podem estar falhando.\n\n"
                  "Endereço verificado: {url}\nProblema: {problem}\n\n"
                  "No servidor, \"docker compose ps\" mostra qual serviço parou e \"docker compose logs --tail=50 "
                  "web-service frontend-proxy-service\" o motivo. Você receberá uma mensagem quando ele voltar a "
                  "responder, e um lembrete a cada 24 horas enquanto isso.\n\n"
                  "Você recebe esta mensagem como administrador do servidor; pode desligar os alertas em Opções → "
                  "E-mail."),
    },
    "alert-resolver-up": {
        "en-GB": ("Resolved: the resolver is answering again",
                  "Hello,\n\n"
                  "The resolver of {operator} answers the portal's checks again ({url}). It had stopped answering "
                  "on {since}.\n\n"
                  "You receive this message as a server administrator; you can switch alerts off in Options → "
                  "E-mail."),
        "pt-BR": ("Resolvido: o Resolver voltou a responder",
                  "Olá,\n\n"
                  "O Resolver de {operator} voltou a responder às verificações do portal ({url}). Ele tinha parado "
                  "de responder em {since}.\n\n"
                  "Você recebe esta mensagem como administrador do servidor; pode desligar os alertas em Opções → "
                  "E-mail."),
    },
    "alert-backup-failed": {
        "en-GB": ("Alert: the daily backup did not succeed",
                  "Hello,\n\n"
                  "The daily backup of the resolver of {operator} needs attention.\n\n"
                  "Last run: {at}\nProblem: {error}\nLast good backup: {lastOk}\n\n"
                  "On the server, /var/log/resolver-backup.log has the message of each run, and \"sudo "
                  "scripts/resolver-backup.sh\" runs one now. You will receive a message when a backup succeeds "
                  "again, and a reminder every 24 hours meanwhile.\n\n"
                  "You receive this message as a server administrator; you can switch alerts off in Options → "
                  "E-mail."),
        "pt-BR": ("Alerta: o backup diário não deu certo",
                  "Olá,\n\n"
                  "O backup diário do Resolver de {operator} precisa de atenção.\n\n"
                  "Última execução: {at}\nProblema: {error}\nÚltimo backup bom: {lastOk}\n\n"
                  "No servidor, /var/log/resolver-backup.log tem a mensagem de cada execução, e \"sudo "
                  "scripts/resolver-backup.sh\" executa um agora. Você receberá uma mensagem quando um backup "
                  "voltar a dar certo, e um lembrete a cada 24 horas enquanto isso.\n\n"
                  "Você recebe esta mensagem como administrador do servidor; pode desligar os alertas em Opções → "
                  "E-mail."),
    },
    "alert-backup-ok": {
        "en-GB": ("Resolved: the daily backup succeeded",
                  "Hello,\n\n"
                  "The backup of the resolver of {operator} succeeded on {at}. The problem had been reported on "
                  "{since}.\n\n"
                  "You receive this message as a server administrator; you can switch alerts off in Options → "
                  "E-mail."),
        "pt-BR": ("Resolvido: o backup diário deu certo",
                  "Olá,\n\n"
                  "O backup do Resolver de {operator} deu certo em {at}. O problema tinha sido avisado em "
                  "{since}.\n\n"
                  "Você recebe esta mensagem como administrador do servidor; pode desligar os alertas em Opções → "
                  "E-mail."),
    },
    "alert-certificate": {
        "en-GB": ("Alert: the certificate of {host} needs renewing",
                  "Hello,\n\n"
                  "The HTTPS certificate of {host}, the address printed in the QR codes of {operator}, expires on "
                  "{expires} ({days} days left), or could not be verified: {error}\n\n"
                  "When it expires, phones refuse to open the scanned links. With Certbot, \"sudo certbot renew\" "
                  "renews it and \"sudo systemctl list-timers | grep certbot\" shows whether automatic renewal "
                  "is scheduled.\n\n"
                  "You receive this message as a server administrator; you can switch alerts off in Options → "
                  "E-mail."),
        "pt-BR": ("Alerta: o certificado de {host} precisa ser renovado",
                  "Olá,\n\n"
                  "O certificado HTTPS de {host}, o endereço impresso nos QR codes de {operator}, vence em "
                  "{expires} (faltam {days} dias), ou não pôde ser verificado: {error}\n\n"
                  "Quando ele vencer, os celulares recusarão abrir os links lidos. Com o Certbot, \"sudo certbot "
                  "renew\" o renova e \"sudo systemctl list-timers | grep certbot\" mostra se a renovação "
                  "automática está agendada.\n\n"
                  "Você recebe esta mensagem como administrador do servidor; pode desligar os alertas em Opções → "
                  "E-mail."),
    },
    "alert-certificate-ok": {
        "en-GB": ("Resolved: the certificate of {host} is valid",
                  "Hello,\n\n"
                  "The HTTPS certificate of {host} is valid until {expires} ({days} days). The problem had been "
                  "reported on {since}.\n\n"
                  "You receive this message as a server administrator; you can switch alerts off in Options → "
                  "E-mail."),
        "pt-BR": ("Resolvido: o certificado de {host} está válido",
                  "Olá,\n\n"
                  "O certificado HTTPS de {host} vale até {expires} ({days} dias). O problema tinha sido avisado "
                  "em {since}.\n\n"
                  "Você recebe esta mensagem como administrador do servidor; pode desligar os alertas em Opções → "
                  "E-mail."),
    },
    "alert-404-spike": {
        "en-GB": ("Alert: many scans of codes nobody registered",
                  "Hello,\n\n"
                  "In the last hour the resolver answered \"code not registered\" (404) {count} times for the "
                  "codes in your reach, against about {usual} in a usual hour. A label may have been printed "
                  "with a code that has no record yet. The codes scanned most:\n\n"
                  "{codes}\n\n"
                  "The portal's Overview lists them with a button to register each one.\n\n"
                  "You receive this message as an administrator; you can switch alerts off in Options → E-mail."),
        "pt-BR": ("Alerta: muitas leituras de códigos sem cadastro",
                  "Olá,\n\n"
                  "Na última hora o Resolver respondeu \"código não cadastrado\" (404) {count} vezes para os "
                  "códigos ao seu alcance, contra cerca de {usual} numa hora comum. Pode ter sido impressa "
                  "uma etiqueta com um código que ainda não tem cadastro. Os códigos mais lidos:\n\n"
                  "{codes}\n\n"
                  "A Visão geral do portal os lista com um botão para cadastrar cada um.\n\n"
                  "Você recebe esta mensagem como administrador; pode desligar os alertas em Opções → E-mail."),
    },
    "alert-log-space": {
        "en-GB": ("Alert: the request log uses {percent} % of its space",
                  "Hello,\n\n"
                  "The log of resolver requests of {operator} uses {used} on disk, {percent} % of the {max} it may "
                  "use (since {since}). When it reaches its limit, the worker deletes the oldest requests, every "
                  "hour, to keep within it.\n\n"
                  "To keep more, raise the limit or free space on the server; to keep less, lower the days in "
                  "Requests → Retention. You will receive another message at each further 5 %.\n\n"
                  "You receive this message as a server administrator; you can switch alerts off in Options → "
                  "E-mail."),
        "pt-BR": ("Alerta: o registro de acessos usa {percent} % do seu espaço",
                  "Olá,\n\n"
                  "O registro de acessos ao Resolver de {operator} ocupa {used} em disco, {percent} % dos {max} "
                  "que pode usar (desde {since}). Ao atingir o limite, o worker apaga os acessos mais antigos, a "
                  "cada hora, para mantê-lo dentro dele.\n\n"
                  "Para guardar mais, aumente o limite ou libere espaço no servidor; para guardar menos, diminua os "
                  "dias em Acessos → Retenção. Você receberá outra mensagem a cada 5 % a mais.\n\n"
                  "Você recebe esta mensagem como administrador do servidor; pode desligar os alertas em Opções → "
                  "E-mail."),
    },
    "alert-log-space-ok": {
        "en-GB": ("Resolved: the request log uses {percent} % of its space",
                  "Hello,\n\n"
                  "The log of resolver requests of {operator} uses {used} on disk, {percent} % of the {max} it may "
                  "use: below the 80 % that had been reported on {since}.\n\n"
                  "You receive this message as a server administrator; you can switch alerts off in Options → "
                  "E-mail."),
        "pt-BR": ("Resolvido: o registro de acessos usa {percent} % do seu espaço",
                  "Olá,\n\n"
                  "O registro de acessos ao Resolver de {operator} ocupa {used} em disco, {percent} % dos {max} "
                  "que pode usar: abaixo dos 80 % avisados em {since}.\n\n"
                  "Você recebe esta mensagem como administrador do servidor; pode desligar os alertas em Opções → "
                  "E-mail."),
    },
    "alert-gcp-table": {
        "en-GB": ("Alert: GS1's GCP length table in use is {days} days old",
                  "Hello,\n\nThe portal of {operator} uses GS1's GCP length table of {date}: {days} days old (reported "
                  "from {max} days; since {since}). GS1 adds company prefixes all the time, so with an old list the EPC "
                  "of a newer prefix and the warnings on the organisations' prefixes may be wrong.\n\nDownload GS1's "
                  "latest list (GCPPrefixFormatList.xml) and upload it in Organisations → GS1 Company Prefix length "
                  "table. You will be reminded every week while the list is this old.\n\nYou receive this message as a "
                  "server administrator; you can switch alerts off in Options → E-mail."),
        "pt-BR": ("Alerta: a tabela de tamanhos de GCP da GS1 em uso tem {days} dias",
                  "Olá,\n\nO portal de {operator} usa a tabela de tamanhos de GCP da GS1 de {date}: {days} dias (o aviso "
                  "começa em {max} dias; desde {since}). A GS1 acrescenta prefixos de empresa o tempo todo; com uma "
                  "lista antiga, o EPC de um prefixo mais novo e os avisos sobre os prefixos das organizações podem "
                  "estar errados.\n\nBaixe a lista mais recente da GS1 (GCPPrefixFormatList.xml) e envie-a em "
                  "Organizações → Tabela de tamanhos do prefixo de empresa GS1. Você será lembrado toda semana enquanto "
                  "a lista estiver assim antiga.\n\nVocê recebe esta mensagem como administrador do servidor; pode "
                  "desligar os alertas em Opções → E-mail."),
    },
    "alert-gcp-table-ok": {
        "en-GB": ("Resolved: GS1's GCP length table is up to date",
                  "Hello,\n\nThe portal of {operator} now uses GS1's GCP length table of {date}, {days} days old. The old "
                  "list had been reported on {since}.\n\nYou receive this message as a server administrator; you can "
                  "switch alerts off in Options → E-mail."),
        "pt-BR": ("Resolvido: a tabela de tamanhos de GCP da GS1 está em dia",
                  "Olá,\n\nO portal de {operator} agora usa a tabela de tamanhos de GCP da GS1 de {date}, com {days} "
                  "dias. A lista antiga tinha sido avisada em {since}.\n\nVocê recebe esta mensagem como administrador do "
                  "servidor; pode desligar os alertas em Opções → E-mail."),
    },
    "alert-journal": {
        "en-GB": ("Alert: {count} broken chain(s) in the audit trail",
                  "Hello,\n\nThe verification of {at} found {count} chain(s) of the audit trail of the portal of {operator} broken (since {since}):\n\n{chains}\n\nAn event was changed, removed or added outside the portal. Open Audit trail → Verify integrity to see each chain, keep the database backups made before that date, and check who can reach the database server and the journal key. You will be reminded every day while a chain is broken.\n\nYou receive this message as a server administrator; you can switch alerts off in Options → E-mail."),
        "pt-BR": ("Alerta: {count} cadeia(s) quebrada(s) na trilha de auditoria",
                  "Olá,\n\nA verificação de {at} encontrou {count} cadeia(s) da trilha de auditoria do portal de {operator} quebrada(s) (desde {since}):\n\n{chains}\n\nUm evento foi alterado, apagado ou acrescentado fora do portal. Abra Auditoria → Verificar integridade para ver cada cadeia, guarde as cópias de segurança do banco de dados feitas antes dessa data e verifique quem tem acesso ao servidor do banco de dados e à chave do diário. Você será lembrado todos os dias enquanto houver uma cadeia quebrada.\n\nVocê recebe esta mensagem como administrador do servidor; pode desligar os alertas em Opções → E-mail."),
    },
    "alert-journal-ok": {
        "en-GB": ("Resolved: every chain of the audit trail is whole",
                  "Hello,\n\nThe verification of {at} found every chain of the audit trail of the portal of {operator} whole. A broken chain had been reported on {since}.\n\nYou receive this message as a server administrator; you can switch alerts off in Options → E-mail."),
        "pt-BR": ("Resolvido: todas as cadeias da trilha de auditoria estão íntegras",
                  "Olá,\n\nA verificação de {at} encontrou íntegras todas as cadeias da trilha de auditoria do portal de {operator}. Uma cadeia quebrada tinha sido avisada em {since}.\n\nVocê recebe esta mensagem como administrador do servidor; pode desligar os alertas em Opções → E-mail."),
    },
    "alert-secrets": {
        "en-GB": ("Alert: an example password of .env.example is in use",
                  "Hello,\n\nThe installation of {operator} still uses a password of .env.example, which is public (since {since}):\n\n{names}\n\nAnyone who can reach the service may use it. MONGO_URI: on the server, \"sudo scripts/rotate-secrets.sh mongo\" changes MongoDB's root password. PORTAL_ADMIN_PASSWORD: sign in as that user and change the password in Options. You will be reminded every week while one is in use.\n\nYou receive this message as a server administrator; you can switch alerts off in Options → E-mail."),
        "pt-BR": ("Alerta: uma senha de exemplo do .env.example está em uso",
                  "Olá,\n\nA instalação de {operator} ainda usa uma senha do .env.example, que é público (desde {since}):\n\n{names}\n\nQualquer pessoa que alcance o serviço pode usá-la. MONGO_URI: no servidor, \"sudo scripts/rotate-secrets.sh mongo\" troca a senha do root do MongoDB. PORTAL_ADMIN_PASSWORD: entre como esse usuário e troque a senha em Opções. Você será lembrado toda semana enquanto uma estiver em uso.\n\nVocê recebe esta mensagem como administrador do servidor; pode desligar os alertas em Opções → E-mail."),
    },
    "alert-secrets-ok": {
        "en-GB": ("Resolved: no example password of .env.example is in use",
                  "Hello,\n\nThe installation of {operator} no longer uses a password of .env.example. One had been reported on {since}.\n\nYou receive this message as a server administrator; you can switch alerts off in Options → E-mail."),
        "pt-BR": ("Resolvido: nenhuma senha de exemplo do .env.example está em uso",
                  "Olá,\n\nA instalação de {operator} não usa mais senhas do .env.example. Uma tinha sido avisada em {since}.\n\nVocê recebe esta mensagem como administrador do servidor; pode desligar os alertas em Opções → E-mail."),
    },
    "alert-settings-stale": {
        "en-GB": ("Alert: the resolver cannot read the portal's settings",
                  "Hello,\n\nSince {since} the resolver of {operator} has not been able to read the portal's settings from the database for longer than its limit (RESOLVER_SETTINGS_MAX_AGE_S; 15 minutes unless set). Until it reads them again it sends no code to another resolver (prefix rules and the resolver of last resort) and shows the item's pages without the organisations' brands; it keeps the domains, the strict mode and the request log's retention it read last.\n\nAddress checked: {url}\n\nOn the server, \"docker compose logs --tail=100 web-service\" shows which settings and why (lines \"not read\"). You will receive a message when it reads them again, and a reminder every 24 hours meanwhile.\n\nYou receive this message as a server administrator; you can switch alerts off in Options → E-mail."),
        "pt-BR": ("Alerta: o Resolver não consegue ler as configurações do portal",
                  "Olá,\n\nDesde {since} o Resolver de {operator} não consegue ler as configurações do portal no banco de dados por mais tempo que o seu limite (RESOLVER_SETTINGS_MAX_AGE_S; 15 minutos se não for definido). Até lê-las de novo, ele não envia nenhum código a outro resolver (regras por prefixo e resolver de último recurso) e mostra as páginas dos itens sem as marcas das organizações; mantém os domínios, o modo estrito e a retenção dos acessos que leu por último.\n\nEndereço verificado: {url}\n\nNo servidor, \"docker compose logs --tail=100 web-service\" mostra quais configurações e por quê (linhas \"not read\"). Você receberá uma mensagem quando ele voltar a lê-las, e um lembrete a cada 24 horas enquanto isso.\n\nVocê recebe esta mensagem como administrador do servidor; pode desligar os alertas em Opções → E-mail."),
    },
    "alert-settings-current": {
        "en-GB": ("Resolved: the resolver reads the portal's settings again",
                  "Hello,\n\nThe resolver of {operator} reads the portal's settings again and applies them ({url}). It had reported them unreadable on {since}.\n\nYou receive this message as a server administrator; you can switch alerts off in Options → E-mail."),
        "pt-BR": ("Resolvido: o Resolver voltou a ler as configurações do portal",
                  "Olá,\n\nO Resolver de {operator} voltou a ler as configurações do portal e a aplicá-las ({url}). Ele tinha avisado em {since} que não conseguia lê-las.\n\nVocê recebe esta mensagem como administrador do servidor; pode desligar os alertas em Opções → E-mail."),
    },
    "alert-domain-lapsed": {
        "en-GB": ("Alert: the DNS record that proves {domain} is missing",
                  "Hello,\n\n"
                  "The portal of {operator} has not found the TXT record {record} for {days} days: it was last seen on {seen}. The record proves that you control {domain}.\n\n"
                  "If {domain} is a domain of your QR codes, it is still served but no longer offered for new labels. If it signs people in with single sign-on, it still does. In both cases another organisation of this installation that proves the domain takes it over.\n\n"
                  "If you still use the domain, publish the record again (Domains or Single sign-on shows its value) and click Verify. If you no longer use it, remove it.\n\n"
                  "You receive this message as an administrator; you can switch alerts off in Options → E-mail."),
        "pt-BR": ("Alerta: o registro DNS que comprova {domain} sumiu",
                  "Olá,\n\n"
                  "O portal de {operator} não encontra o registro TXT {record} há {days} dias: ele foi visto pela última vez em {seen}. O registro comprova que vocês controlam {domain}.\n\n"
                  "Se {domain} é um domínio dos seus QR codes, ele continua atendido, mas não é mais oferecido para novas etiquetas. Se ele dá acesso pelo login único, continua dando. Nos dois casos, outra organização desta instalação que comprovar o domínio passa a tê-lo.\n\n"
                  "Se ainda usam o domínio, publique o registro de novo (o valor está em Domínios ou em Login único) e clique em Verificar. Se não o usam mais, remova-o.\n\n"
                  "Você recebe esta mensagem como administrador; pode desligar os alertas em Opções → E-mail."),
    },
    "forwarding-on": {
        "en-GB": ("Codes of prefix {prefix} are now sent to another resolver",
                  "Hello,\n\n"
                  "Since {at}, the resolver of {operator} sends every code whose GS1 Company Prefix starts with {prefix} to {target}: a server administrator set this forwarding rule. It covers these prefixes of {organisation}: {prefixes}.\n\n"
                  "Requests for those codes no longer reach the records you keep in this portal; the records themselves have not changed. If you did not expect this, contact the operator of the portal. The change is in your audit trail.\n\n"
                  "You receive this message as an administrator; you can switch alerts off in Options → E-mail."),
        "pt-BR": ("Os códigos do prefixo {prefix} agora vão para outro resolver",
                  "Olá,\n\n"
                  "Desde {at}, o resolver de {operator} envia a {target} todo código cujo prefixo de empresa GS1 começa com {prefix}: um administrador do servidor definiu essa regra de encaminhamento. Ela abrange estes prefixos de {organisation}: {prefixes}.\n\n"
                  "As requisições desses códigos não chegam mais aos registros que vocês mantêm neste portal; os registros em si não mudaram. Se vocês não esperavam por isso, procurem o operador do portal. A mudança está na sua trilha de auditoria.\n\n"
                  "Você recebe esta mensagem como administrador; pode desligar os alertas em Opções → E-mail."),
    },
    "forwarding-off": {
        "en-GB": ("Codes of prefix {prefix} are no longer sent to another resolver",
                  "Hello,\n\n"
                  "Since {at}, the resolver of {operator} no longer sends codes whose GS1 Company Prefix starts with {prefix} to {target}: a server administrator switched off or removed the forwarding rule. It covered these prefixes of {organisation}: {prefixes}.\n\n"
                  "Unless another rule covers them, requests for those codes are answered again from the records you keep in this portal: check that they are up to date. The change is in your audit trail.\n\n"
                  "You receive this message as an administrator; you can switch alerts off in Options → E-mail."),
        "pt-BR": ("Os códigos do prefixo {prefix} não vão mais para outro resolver",
                  "Olá,\n\n"
                  "Desde {at}, o resolver de {operator} não envia mais a {target} os códigos cujo prefixo de empresa GS1 começa com {prefix}: um administrador do servidor desligou ou removeu a regra de encaminhamento. Ela abrangia estes prefixos de {organisation}: {prefixes}.\n\n"
                  "Salvo se outra regra os abranger, as requisições desses códigos voltam a ser respondidas pelos registros que vocês mantêm neste portal: confira se estão atualizados. A mudança está na sua trilha de auditoria.\n\n"
                  "Você recebe esta mensagem como administrador; pode desligar os alertas em Opções → E-mail."),
    },
    "forwarding-covered": {
        "en-GB": ("A forwarding rule sends codes of prefix {prefix} to another resolver",
                  "Hello,\n\n"
                  "On {at}, a server administrator of {operator} gave {organisation} these GS1 Company Prefixes: {prefixes}. A forwarding rule already sends every code whose GS1 Company Prefix starts with {prefix} to {target}.\n\n"
                  "Requests for those codes do not reach the records you keep in this portal: while the rule is on, what you save for them is not what a scan finds. If you did not expect this, contact the operator of the portal. The change is in your audit trail.\n\n"
                  "You receive this message as an administrator; you can switch alerts off in Options → E-mail."),
        "pt-BR": ("Uma regra de encaminhamento envia os códigos do prefixo {prefix} a outro resolver",
                  "Olá,\n\n"
                  "Em {at}, um administrador do servidor de {operator} deu a {organisation} estes prefixos de empresa GS1: {prefixes}. Uma regra de encaminhamento já envia a {target} todo código cujo prefixo de empresa GS1 começa com {prefix}.\n\n"
                  "As requisições desses códigos não chegam aos registros que vocês mantêm neste portal: enquanto a regra estiver ligada, o que vocês salvarem para eles não é o que a leitura encontra. Se vocês não esperavam por isso, procurem o operador do portal. A mudança está na sua trilha de auditoria.\n\n"
                  "Você recebe esta mensagem como administrador; pode desligar os alertas em Opções → E-mail."),
    },
    "test": {
        "en-GB": ("Test message from the link management portal",
                  "Hello,\n\n"
                  "This is a test message sent on {when} (UTC) to check the portal's e-mail settings. If you can "
                  "read it, the relay accepted the message and delivered it."),
        "pt-BR": ("Mensagem de teste do portal de gestão de links",
                  "Olá,\n\n"
                  "Esta é uma mensagem de teste enviada em {when} (UTC) para conferir as configurações de e-mail do "
                  "portal. Se você consegue lê-la, o relay aceitou a mensagem e a entregou."),
    },
}


# The other languages, kept apart so this file stays readable
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "mail_languages.json"), encoding="utf-8") as _fh:
    for _lang, _texts in json.load(_fh).items():
        SIGNATURE[_lang] = _texts["signature"]
        for _name, (_subject, _body) in _texts["texts"].items():
            TEXTS[_name][_lang] = (_subject, _body)
        LANGUAGES += (_lang,)


class _Defaults(dict):
    """format_map dictionary that leaves an unknown placeholder visible instead of failing."""

    def __missing__(self, key):
        return "{" + key + "}"


def placeholders(text: str) -> set[str]:
    """The {names} a text uses."""
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def language(value) -> str:
    """One of LANGUAGES: the value when supported, the same language of another region ("pt" → pt-BR), else the
    default."""
    text = str(value or "").strip()
    if text in LANGUAGES:
        return text
    base = text.split("-")[0].lower()
    return next((lang for lang in LANGUAGES if lang.split("-")[0].lower() == base), DEFAULT_LANGUAGE) if base \
        else DEFAULT_LANGUAGE


_URL = re.compile(r"https?://[^\s<>\"]+")


def _html(text: str) -> str:
    """The HTML alternative of a plain text: escaped, one paragraph per block, addresses made clickable."""
    blocks = []
    for block in text.split("\n\n"):
        escaped = html.escape(block)
        linked = _URL.sub(lambda m: f'<a href="{m.group(0)}">{m.group(0)}</a>', escaped)
        blocks.append("<p>" + linked.replace("\n", "<br>\n") + "</p>")
    return ("<!doctype html>\n<html><body style=\"font-family: Arial, Helvetica, sans-serif; font-size: 15px; "
            "line-height: 1.5; color: #1a1a1a\">\n" + "\n".join(blocks) + "\n</body></html>\n")


def compose(template: str, lang: str, **params) -> tuple[str, str, str]:
    """(subject, plain text, HTML) of a message in a language, with its placeholders and the signature filled."""
    lang = language(lang)
    subject, body = TEXTS[template][lang]
    values = _Defaults({k: "" if v is None else str(v) for k, v in params.items()})
    text = body.format_map(values) + "\n\n" + SIGNATURE[lang].format_map(values)
    return subject.format_map(values), text, _html(text)
