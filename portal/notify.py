"""
Notifications of the portal by e-mail (Documentation/adr/0004-e-mail.md, decisions 3 and 7).

send() composes a message in the recipient's language (mailtexts.py) and queues it as a "mail" job; the worker
sends it (run_mail_job) and tries again after a temporary failure. Nothing is queued when mail is off
(mail.enabled()), when the account has no address, is disabled or belongs to a disabled organisation, or when the
message is of an optional category the user did not switch on.

Categories (TEMPLATES maps each message to one):
  account     messages the user or an administrator asked for (invitation, recovery and reset links): always
  security    the password or the e-mail address was changed, the account was locked: always
  jobs        an import or a link check the user started has finished: optional, off by default
  alerts      monitoring (Documentation/adr/0008-monitoring-and-alerts.md): the resolver down, the backup, the
              certificate, spikes of 404 — to administrators: optional, on by default
"""
import logging
import os
from datetime import datetime, timezone

from pymongo.errors import PyMongoError

import jobs
import journal
import mail
import mailtexts
import tenants
import users
import worker

log = logging.getLogger("portal.notify")

# category → (optional, default for a user who has not chosen)
CATEGORIES = {"account": (False, True), "security": (False, True), "jobs": (True, False), "alerts": (True, True)}
OPTIONAL = tuple(name for name, (optional, _) in CATEGORIES.items() if optional)
TEMPLATES = {
    "invite": "account", "password-recovery": "account", "password-reset-admin": "account",
    "password-changed": "security", "email-changed-old": "security", "email-changed-new": "security",
    "account-locked": "security", "api-key-created": "security", "api-key-expiring": "security",
    "import-finished": "jobs", "linkcheck-finished": "jobs",
    "alert-resolver-down": "alerts", "alert-resolver-up": "alerts", "alert-backup-failed": "alerts",
    "alert-backup-ok": "alerts", "alert-certificate": "alerts", "alert-certificate-ok": "alerts",
    "alert-404-spike": "alerts",
}
# Waits before each new try after a temporary failure, in minutes; after the last, the message has failed.
RETRY_MINUTES = (1, 5, 15, 60, 120)


def operator_name() -> str:
    return (os.environ.get("RESOLVER_ORG_NAME", "") or "").strip()


def portal_address() -> str:
    """The portal's public address, with a trailing slash (the signature of every message)."""
    return mail._portal_address()


def link_base() -> str:
    """Where the links of the messages point: the portal's public origin."""
    return portal_address()[: -len("/portal/")]


def now_text() -> str:
    """The current time as messages show it (UTC, to the minute)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")


def wants(account: dict, template: str) -> bool:
    """Whether the account receives a message of that template (its category always, or chosen by the user)."""
    optional, default = CATEGORIES[TEMPLATES[template]]
    if not optional:
        return True
    return bool((account.get("notify") or {}).get(TEMPLATES[template], default))


def reachable(account: dict | None) -> bool:
    """An enabled account of an enabled organisation (or of the operator)."""
    if not account or account.get("disabled"):
        return False
    if account.get("tenant"):
        tenant = tenants.get(account["tenant"])
        return bool(tenant) and not tenant["disabled"]
    return True


def send(username: str, template: str, to: str | None = None, language: str | None = None, **params) -> bool:
    """Queues a message for a user (to his address, or to `to`); returns whether one was queued. Never raises
    for a problem of mail: the action that caused the message has already happened."""
    try:
        if not mail.enabled():
            return False
        account = users.get(username)
        address = to or (account or {}).get("email")
        if not address or not reachable(account) or not wants(account, template):
            return False
        lang = mailtexts.language(language or account.get("language"))
        subject, text, html = mailtexts.compose(template, lang, user=username, operator=operator_name(),
                                                portal=portal_address(), **params)
        jobs.create("mail", username, "queued", 1, to=address, subject=subject, text=text, html=html,
                    template=template, tries=0)
        worker.wake()                                 # the embedded worker, when there is one, looks at once
        return True
    except PyMongoError as exc:
        log.warning("Message %s for %s not queued: %s", template, username, exc)
        return False


def _journal_failure(job: dict, error: str) -> None:
    account = users.get(job["user"]) or {}
    try:
        journal.append("mail-failed", job["user"], detail=f'{job.get("template")}: {error}'[:300],
                       **({"tenant": account["tenant"]} if account.get("tenant") else {}))
    except PyMongoError as exc:
        log.warning("Journal not written (mail-failed): %s", exc)


def run_mail_job(job: dict, reporter: "jobs.Reporter") -> None:
    """Worker: sends one queued message. A temporary failure puts it back in the queue for RETRY_MINUTES; a
    permanent one, or the last try, fails it and writes mail-failed in the journal. The message's text leaves the
    job once it is sent or has failed (the links it carries are credentials while they are valid)."""
    account = users.get(job["user"])
    if not reachable(account):                     # removed or disabled since the message was queued
        reporter.finish(remove=("text", "html"), skipped=True)
        log.info("Message %s for %s not sent: the account can no longer receive it.", job.get("template"), job["user"])
        return
    tries = int(job.get("tries") or 0) + 1
    try:
        answer = mail.send(mail.message(mail.addressee(job["to"]), job["subject"], job["text"], job.get("html")))
    except mail.MailError as exc:
        error = str(exc)[:300]
        if exc.temporary and tries <= len(RETRY_MINUTES):
            log.warning("Message %s for %s not taken by the relay (try %d): %s; trying again in %d min.",
                        job.get("template"), job["user"], tries, error, RETRY_MINUTES[tries - 1])
            reporter.defer(RETRY_MINUTES[tries - 1] * 60, tries=tries, lastError=error)
        log.error("Message %s for %s failed after %d tries: %s", job.get("template"), job["user"], tries, error)
        reporter.give_up("mail.failed", remove=("text", "html"), tries=tries, lastError=error)
        _journal_failure(job, error)
        return
    log.info("Message %s for %s sent (%s).", job.get("template"), job["user"], answer)
    reporter.finish(remove=("text", "html"), tries=tries, sent=True)
