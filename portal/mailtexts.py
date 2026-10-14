"""
Texts of the portal's e-mail messages, in British English and Brazilian Portuguese
(Documentation/adr/0004-e-mail.md, decision 8).

Each message has a subject and a plain text per language, with {placeholders} filled in by compose(). Every
message ends with the same signature: the operator's name (RESOLVER_ORG_NAME) and the portal's address. The HTML
alternative is made from the plain text (escaped, paragraphs, links made clickable), so the two never differ.

The development tests check that both languages have the same messages with the same placeholders
(dev-tests/portal/test_mail.py). A new message needs both languages and a category in notify.TEMPLATES.
"""
import html
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
    "account-locked": {
        "en-GB": ("Sign-in attempts to your account",
                  "Hello,\n\n"
                  "The user {user} could not sign in to the link management portal after several wrong "
                  "passwords, the last on {when} (UTC). Sign-in for this user is blocked for {minutes} "
                  "minutes.\n\n"
                  "If it was you, wait and try again, or use \"Forgot your password?\" on the sign-in page. If it "
                  "was not, someone may be trying to use your account: tell your administrator."),
        "pt-BR": ("Tentativas de acesso à sua conta",
                  "Olá,\n\n"
                  "O usuário {user} não conseguiu entrar no portal de gestão de links depois de várias senhas "
                  "erradas, a última em {when} (UTC). O acesso deste usuário está bloqueado por {minutes} "
                  "minutos.\n\n"
                  "Se foi você, espere e tente de novo, ou use \"Esqueceu a senha?\" na página de acesso. Se não "
                  "foi, alguém pode estar tentando usar a sua conta: avise o seu administrador."),
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
