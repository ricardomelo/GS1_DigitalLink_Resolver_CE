# ADR 0044 — Encrypted backups; the single sign-on secrets sealed in the database

| | |
|---|---|
| Status | **Accepted** (22 November 2026) |
| Backlog item | 10.1, the security assessment ([ADR 0020](0020-security-assessment.md)); threats T-I4 and T-I2 of the [threat model](../threat-model.md) |
| Decided by | the owner's standing instruction for the assessment's findings, the owner away: the recommended option taken. Not taken: `openssl enc` with a passphrase (no integrity: an archive changed by whoever holds the copy restores without a word); `gpg --symmetric` (the passphrase must sit on the server to encrypt, so the server's copy and the off-server copy fall together); leaving encryption to the off-server destination (the local archives and any copy made by hand stay readable); a key for the client secrets derived from the session key (`scripts/rotate-secrets.sh session` would then make every stored secret unreadable) |

## 1. Context

`scripts/resolver-backup.sh` writes, every night, a dump of every database — the portal's users with their password
hashes and e-mail addresses, the organisations, the records, the journal, the single sign-on configurations — and a
copy of the portal's configuration volume (the fallback session key). The files were gzip archives, readable by
whoever got them: the off-server copy (`BACKUP_COPY_TO`, an SSH account or a mounted share run by someone else), a
copy made by hand to a laptop, a disk sold with the server.

The single sign-on configurations ([ADR 0012](0012-single-sign-on.md)) keep each organisation's OpenID Connect
client secret, which the portal must send back to the provider at every sign-in, so it cannot be hashed. It was stored
as text in the collection `sso`: anyone who could read the database or a dump of it — a backup, a database user given
read access for a report, the database port exposed by mistake — held every organisation's client secret and could
ask its provider for tokens as the portal.

## 2. Decision

### 2.1 Backups encrypted with age

1. **Every archive is encrypted with [age](https://age-encryption.org)** (X25519 recipients, ChaCha20-Poly1305:
   confidentiality and integrity) as it is written: `mongodump … | age -r <recipient> … > resolver-<time>.archive.gz.age`
   and likewise `portal-config-<time>.tar.gz.age`. Nothing unencrypted reaches the disk; a failure of either side of
   the pipe fails the run (`ERROR`, status 1, recorded for the monitoring) and leaves no file.
2. **Recipients, not a passphrase.** Encrypting needs only the public key. The recipients are the public key of the
   identity in `BACKUP_KEY_FILE` (default `/etc/resolver-backup.key`, root, mode 600) when that file is there, and the
   public keys in `BACKUP_RECIPIENTS` (`.env`, separated by spaces or commas). An operator who wants the server unable
   to read its own backups puts the public key in `BACKUP_RECIPIENTS` and keeps the identity elsewhere.
3. **The key is made for the operator.** The installer installs age and, when there is neither a key file nor
   `BACKUP_RECIPIENTS`, creates the key file with `age-keygen` and says, in its summary, that a copy must be kept off
   the server (a password manager): **without it no backup can be restored**. `resolver-backup.sh` does the same at
   its first run on an installation upgraded without the installer, with a `NOTICE` line in its log.
4. **age missing is a failure, never a fallback.** Without age the run says `ERROR: age is not installed (sudo apt-get
   install age)`, writes nothing and exits with status 1 (the portal's monitoring then alerts). `BACKUP_ENCRYPTION=off`
   keeps the former unencrypted archives, for a destination that encrypts by itself; each such run prints a `WARNING`.
5. **Restoring decrypts.** `scripts/restore-rehearsal.sh` takes the newest archive, encrypted (`*.archive.gz.age`) or
   from before (`*.archive.gz`), decrypts the first with the identity in `BACKUP_KEY_FILE` (an error naming the
   setting when the file is not on the server, and when the key does not open the archive) and restores it as before.
   The operator README gives the manual restore: `age -d -i <key> <archive> | docker compose exec -T database-service
   … mongorestore --archive --gzip --drop`. Retention removes the encrypted names too.

### 2.2 The client secrets sealed

1. **`portal/sealed.py`** seals a value with AES-256-GCM (`cryptography`, already in the image through `pyjwt[crypto]`)
   under a key of its own: `{"sealed": 1, "kid": <key id>, "nonce": <base64>, "data": <base64>}`. The associated data
   names the place of the value (`sso:<scope>:clientSecret`), so a sealed value moved to another configuration does
   not open.
2. **The key.** `PORTAL_DATA_KEY` (`.env`; the installer generates one like `PORTAL_JOURNAL_KEY` and never replaces
   it), stretched with HKDF-SHA256; without it, a random key created once in the portal's configuration volume
   (`data.key`, created like the fallback session key), so that an installation upgraded without the installer seals
   too. It is independent of the session key: rotating `PORTAL_SECRET_KEY` signs people out and touches no secret.
3. **Earlier keys.** A value sealed with another known key — `PORTAL_DATA_KEY_PREVIOUS`, or `data.key` once
   `PORTAL_DATA_KEY` is set — still opens, and the portal seals it again with the current key when it starts.
   `scripts/rotate-secrets.sh data` (only when named) moves the current key to `PORTAL_DATA_KEY_PREVIOUS` and writes
   a new one; the services are recreated and the secrets sealed again.
4. **At the start** the portal seals every secret stored in clear by an earlier version (and re-seals those of an
   earlier key), in place, only where the stored value is still the one read.
5. **A secret that does not open** (the key lost or changed without `PORTAL_DATA_KEY_PREVIOUS`) is never sent: the
   sign-in stops with `sso.secretUnreadable` (recorded as the configuration's last error) and the Single sign-on screen
   shows *secret unreadable* in place of *secret stored*; the organisation's administrator enters it again.

## 3. Consequences

- A backup, or its off-server copy, read without the backup key shows nothing; changed, it does not decrypt. The key
  is now the one thing that makes a backup useful: losing it loses every backup encrypted to it (the installer, the
  first run, the operator README and the CHANGELOG say so).
- The database alone — a dump, a read-only user, an exposed port — no longer gives the providers' client secrets.
  Whoever reads both the database and `.env` (or the configuration volume, when `PORTAL_DATA_KEY` is not set) still
  has them: root on the server has everything, as before.
- The configuration volume's archive holds `data.key` when `PORTAL_DATA_KEY` is not set; it is encrypted like the
  dump. With `PORTAL_DATA_KEY` set, a restore needs the `.env` of the installation (or the key) to bring the client
  secrets back; otherwise they are entered again.
- Upgrading: `sudo apt-get install age`, a backup run (it creates the key), a copy of `/etc/resolver-backup.key` kept
  off the server, and optionally `PORTAL_DATA_KEY` in `.env`. Archives written before stay unencrypted until the
  retention removes them; the off-server destination keeps its own.

## 4. Residuals

1. The backup's result recorded for the monitoring does not say whether it was encrypted (`BACKUP_ENCRYPTION=off`
   shows only in the log).
2. Rotating the backup key is manual (a new key file; the former one kept for the archives encrypted to it).
3. Other values stored for later use are not sealed: the portal stores no other third-party secret (API keys and
   passwords are hashed; the mail relay's password is in `.env`).
4. The data key sits in `.env` or the configuration volume of the same server: sealing protects copies of the
   database, not a compromised server.
5. `scripts/upgrade-from-official.sh` still writes its one pre-upgrade archive unencrypted (an official installation
   has no backup key yet); it names the file, to be deleted once the upgrade works.
