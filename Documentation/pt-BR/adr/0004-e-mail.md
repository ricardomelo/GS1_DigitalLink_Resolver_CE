# ADR 0004 — E-mail: um relay autenticado, convites, recuperação de senha e notificações

| | |
|---|---|
| Situação | **Aceita** (14 de outubro de 2026). A implementar em três etapas: 1 (este registro), 2 (envio, links de uso único, notificações e suas configurações no servidor), 3 (telas) |
| Item do backlog | 3.1 — e-mail |
| Decidido por | o dono do branch, que pediu a opção recomendada em todos os pontos da seção 4 enquanto estava ausente |
| Inglês | [ADR 0004 in English](../../adr/0004-e-mail.md) (versão de referência) |

## 1. Contexto

Hoje o portal não consegue enviar uma mensagem. Tudo o que normalmente passaria por e-mail passa à mão por um
administrador:

- um usuário novo recebe uma **senha temporária** que o administrador lê na tela e repassa (uma mensagem de chat,
  um telefonema), e que o usuário precisa trocar no primeiro acesso;
- um usuário que esqueceu a senha pede a um administrador, que gera outra senha temporária;
- ninguém fica sabendo quando sua senha ou seu endereço de e-mail mudou, nem quando sua conta foi bloqueada por
  tentativas de acesso erradas — os sinais usuais de que outra pessoa está tentando a conta;
- uma importação longa ou uma verificação de todos os links termina quando o usuário pode já ter saído da página.

O item 2.4 deu a cada usuário um endereço de e-mail opcional e único (ADR 0002, decisão 8), definido pelos
administradores e ainda não usado. Os itens 4.3 (monitoramento e alertas) e 4.4 (resumo semanal por organização)
também vão enviar mensagens e precisam de um meio para isso, de um lugar para as escolhas de cada usuário e de
textos nos dois idiomas.

Restrições das instalações:

- Os provedores de nuvem bloqueiam conexões de saída para a porta 25 (o Azure bloqueia; o servidor de homologação
  roda lá). O e-mail precisa passar por um **relay** que aceite envios autenticados na porta 587 (STARTTLS) ou 465
  (TLS): o da própria organização (Microsoft 365, Google Workspace, um servidor Exchange ou Postfix) ou um serviço
  de envio (Amazon SES, SendGrid, Mailgun e outros oferecem essa interface SMTP).
- O portal roda em várias réplicas e processos, e suas tarefas em segundo plano rodam no serviço `portal-worker`
  (ADR 0001). Um relay pode ficar lento ou indisponível por um tempo; a página de acesso não pode esperar por ele.
- Uma instalação sem relay precisa continuar funcionando exatamente como hoje.

## 2. Decisão

1. **Envio SMTP a um relay escolhido pelo operador**, com autenticação, na porta 587 com STARTTLS (o padrão) ou
   465 com TLS. O certificado do relay é sempre verificado. Um relay sem criptografia só é aceito sem credenciais
   (um servidor de teste na própria rede da instalação). Nenhuma API HTTP de fornecedor.
2. **Configurações no `.env`** (`PORTAL_MAIL_*`, seção 6), como todas as outras; a senha do relay é um segredo
   como os demais (nunca exibida, nunca no diário). **Sem `PORTAL_MAIL_HOST` o e-mail fica desligado** e o portal
   se comporta exatamente como antes: senhas temporárias, nenhum link de recuperação, nenhuma notificação. O
   instalador pergunta pelo relay numa etapa opcional.
3. **As mensagens são tarefas do worker** (um terceiro tipo de tarefa, `mail`, na coleção `jobs` da ADR 0001): a
   requisição que causa uma mensagem apenas a enfileira. O worker a envia, tenta de novo depois de uma falha
   temporária (após 1, 5, 15, 60 e 120 minutos) e desiste diante de uma recusa definitiva ou depois da última
   tentativa, gravando `mail-failed` no diário. O texto de uma mensagem é retirado da tarefa assim que ela é
   enviada ou falha.
4. **Links de uso único** para convites e recuperação de senha: 256 bits aleatórios, guardados só como hash
   SHA-256 numa nova coleção `tokens` que os expira (índice TTL); válidos por **72 horas** (convite) ou **60
   minutos** (recuperação); um link novo substitui o anterior do mesmo tipo; usados uma vez (retirados de forma
   atômica). **O token vai no fragmento do link** (`…/portal/login#reset=…`), que os navegadores nunca enviam a
   um servidor, de modo que não chega a logs de acesso, proxies nem ao `Referer` de uma página; a página de acesso
   o lê e o envia.
5. **Convites.** Com o e-mail ligado, um usuário criado **com endereço de e-mail** recebe um convite em vez de uma
   senha temporária (uma caixa no formulário, marcada por padrão, deixa o administrador ainda escolher a senha
   temporária). A conta convidada não tem senha até o usuário escolher uma pelo link. *Redefinir senha* envia um
   link a um usuário que tem endereço; sem endereço (ou com o e-mail desligado) gera uma senha temporária, como
   hoje.
6. **Recuperação de senha.** *Esqueceu a senha?* na página de acesso, exibido só quando o e-mail está ligado. O
   usuário digita seu nome de usuário ou endereço de e-mail; **a resposta é a mesma havendo ou não uma conta
   correspondente**, de modo que a página não revela quais nomes ou endereços existem. Os pedidos são limitados por
   nome e por endereço do navegador. Nada é enviado a uma conta sem endereço, desativada ou de uma organização
   desativada. Escolher uma senha por um link encerra todas as sessões abertas da conta e remove seus outros links.
7. **Uma estrutura de notificações** (`portal/notify.py`): cada mensagem pertence a uma **categoria**. As
   mensagens de *segurança* são sempre enviadas — a senha foi trocada, o endereço de e-mail foi trocado (para o
   endereço antigo e para o novo), a conta foi bloqueada depois de tentativas de acesso erradas repetidas (uma vez
   por bloqueio). *Minhas tarefas em segundo plano* (uma importação ou verificação de links que eu iniciei
   terminou) é opcional e fica **desligada por padrão**. Cada usuário guarda suas escolhas e **o idioma das suas
   mensagens** (pt-BR ou en-GB; tirado da página a cada acesso até ele escolher um em *Opções*). Os itens 4.3 e
   4.4 acrescentam suas próprias categorias.
8. **Textos nos dois idiomas, no código** (`portal/mailtexts.py`): um assunto e um texto simples por mensagem e
   idioma, com uma alternativa HTML feita do mesmo texto; assinados com o nome do operador (`RESOLVER_ORG_NAME`);
   sem marca GS1. Um teste confere que os dois idiomas têm as mesmas mensagens com os mesmos marcadores.
9. **Testes sem um relay real.** Os testes de desenvolvimento rodam um pequeno relay SMTP próprio (STARTTLS com um
   certificado descartável, autenticação, recusas sob demanda). Para experimentar o fluxo inteiro numa instalação
   de homologação antes de configurar um relay real, o `docker-compose.yml` ganha um **serviço `mailpit` no perfil
   `mail-test`** (não iniciado a menos que se peça), que aceita todas as mensagens e as mostra pela sua API em
   `127.0.0.1:8025`.
10. **Privacidade desde a concepção.** O diário identifica o usuário, nunca o seu endereço. Uma mensagem diz só o
    que o usuário precisa; mensagens de recuperação não dizem se outras contas existem. O relay vê endereços e
    textos, o que o operador aceita ao escolhê-lo.

## 3. Projeto

### 3.1 Envio (`portal/mail.py`)

`enabled()` é verdadeiro quando `PORTAL_MAIL_HOST` e `PORTAL_MAIL_FROM` estão definidos e as configurações são
coerentes (um usuário sem senha, ou credenciais com `PORTAL_MAIL_SECURITY=none`, desligam o e-mail com um erro no
log). `send(message)` abre uma conexão por mensagem:

| `PORTAL_MAIL_SECURITY` | Conexão |
|---|---|
| `starttls` (padrão, porta 587) | conexão simples, `STARTTLS` obrigatório (um relay que não o ofereça é recusado), depois `AUTH` |
| `tls` (porta 465) | TLS desde o primeiro byte, depois `AUTH` |
| `none` | sem criptografia, sem autenticação (um relay de teste como o Mailpit) |

O contexto TLS é o do sistema, mais `PORTAL_MAIL_CA_FILE` quando informado (o relay de uma empresa assinado por
uma autoridade privada). Os erros se dividem em **temporários** (sem conexão, tempo esgotado, resposta 4xx) e
**definitivos** (5xx: remetente recusado, destinatário desconhecido, autenticação falhou).

`python mail.py test <endereço>` (executado no contêiner `portal-service`) envia uma mensagem de teste na hora, sem
o worker, e mostra a resposta do relay: a conferência do operador depois de configurar o relay.

### 3.2 A tarefa `mail`

```
{"_id": "<token>", "type": "mail", "user": "<nome do destinatário>", "state": "queued",
 "to": "maria@example.org", "subject": "…", "text": "…", "html": "…", "template": "password-reset",
 "tries": 0, "notBefore": <data>, "lastError": "…", "created": …, "expiresAt": …}
```

A mensagem é composta quando é enfileirada (o idioma e o link são conhecidos nesse momento). `jobs.claim()` pega
uma tarefa da fila só quando o seu `notBefore` já passou; `jobs.defer()` devolve uma tarefa à fila com um
`notBefore` mais adiante (uma falha temporária). Depois de enviada, a tarefa termina e perde `text` e `html`; uma
tarefa que falhou também os perde e o diário recebe `mail-failed` (o modelo e a resposta do relay, nunca o
endereço). As tarefas de e-mail não aparecem no navegador: ninguém espera por elas.

### 3.3 Links de uso único (`portal/tokens.py`)

```
{"_id": "<sha256 do token>", "purpose": "invite" | "reset", "user": "maria",
 "created": <data>, "expiresAt": <data>}
```

- `issue(user, purpose)` remove os links anteriores do usuário com aquele propósito e devolve um novo token
  aleatório (`secrets.token_urlsafe(32)`); só o seu hash é guardado.
- `peek(token)` (é válido, de quem, para quê) permite à página mostrar o nome do usuário antes de ele digitar uma
  senha.
- `consume(token)` retira o documento de forma atômica (`find_one_and_delete` por hash e data): um link funciona
  uma vez.
- `purge(user)` remove todos os links de um usuário (senha definida, usuário removido).
- O link é `<PORTAL_ORIGIN>/portal/login#invite=<token>` ou `#reset=<token>`.

### 3.4 Contas

Os documentos de `users` ganham:

- `invited`: a data do convite, enquanto a conta não tem senha própria (o `hash` fica vazio, então nenhuma senha
  entra); removido quando o usuário escolhe uma.
- `language`: `pt-BR` ou `en-GB`; `languageChosen`: verdadeiro depois que o usuário o escolheu em *Opções* (até lá
  cada acesso usa o idioma da página).
- `notify`: as categorias opcionais que o usuário ligou (`{"jobs": true}`).

### 3.5 Fluxos

| Fluxo | O que acontece |
|---|---|
| Convite | o administrador cria o usuário com endereço e *Enviar convite* marcado → conta com `invited`, sem senha → link `invite` por e-mail → o usuário o abre, vê o seu nome de usuário, escolhe uma senha → vai para a página de acesso com uma mensagem → diário `invite-accepted` |
| Redefinição por um administrador | *Redefinir senha* num usuário com endereço → todas as sessões do usuário terminam (a senha antiga para de funcionar na hora) → link `reset` por e-mail → como acima, diário `user-reset` (com `detail` "link") e depois `password-reset` |
| Recuperação pelo usuário | *Esqueceu a senha?* → nome de usuário ou endereço → a mesma resposta para qualquer entrada → quando uma conta corresponde e pode entrar, link `reset` por e-mail e diário `password-recovery` → como acima |
| Senha escolhida por um link | `POST /portal/api/password/link` com o token e a nova senha (tamanho mínimo como hoje) → senha definida, `mustChange` e `invited` apagados, todas as sessões e os outros links do usuário encerrados → mensagem de segurança "sua senha foi trocada" |
| Endereço trocado por um administrador | mensagem de segurança para o endereço antigo (que pode não ser mais do usuário) e para o novo |
| Conta bloqueada | a quinta tentativa de acesso errada para um nome de usuário que existe envia uma mensagem de segurança (uma por bloqueio) |
| Tarefa terminada | quando o usuário ligou *Minhas tarefas em segundo plano*: uma importação (contagens) ou uma verificação de links (problemas encontrados) terminou |

O tempo de uma requisição não depende de haver uma conta correspondente (a mesma espera de um acesso errado). Os
pedidos de recuperação contam na coleção do limitador de acessos com chaves próprias: 3 por nome de usuário e 10
por endereço do navegador em 15 minutos.

### 3.6 Telas

- **Página de acesso**: *Esqueceu a senha?* (com o e-mail ligado) abre um pequeno formulário; um link de uma
  mensagem abre *Escolha a sua senha* (nome de usuário exibido, nova senha duas vezes).
- **Usuários**: *Enviar convite por e-mail* no formulário de novo usuário (com o e-mail ligado e um endereço
  digitado); a coluna de situação diz *Convidado*; *Redefinir senha* diz antes de agir se virá um link ou uma
  senha temporária.
- **Opções**: uma seção *E-mail* com o endereço do usuário (definido pelos administradores), o idioma das
  mensagens e as categorias opcionais; as mensagens de segurança aparecem como sempre enviadas.

### 3.7 API acrescentada ou alterada

| Chamada | Quem | |
|---|---|---|
| `GET /portal/api/login/options` | qualquer um | `{"passwordRecovery": bool}` para a página de acesso |
| `POST /portal/api/password/forgot` | qualquer um | `{"login"}` → sempre `password.recoverySent` |
| `POST /portal/api/password/link/check` | qualquer um | `{"token"}` → `{"user", "purpose"}` ou `password.linkInvalid` |
| `POST /portal/api/password/link` | qualquer um | `{"token", "newPassword"}` → `password.set` |
| `GET` / `PUT /portal/api/preferences` | com acesso | idioma e categorias opcionais |
| `POST /portal/api/users` | administradores | ganha `invite` (booleano); responde sem senha quando um convite foi enviado |
| `POST /portal/api/users/<nome>/reset` | administradores | envia um link quando possível (`users.resetSent`), senão uma senha temporária como hoje |
| `GET /portal/api/config` | com acesso | ganha `mail` (`{"enabled": bool}`) e o `email`, `language` e `notify` do usuário |
| `GET /portal/healthz` | qualquer um | ganha `"mail": "off"` ou `"on"` |

## 4. Opções consideradas

| Ponto | Escolhida (recomendada) | Não escolhida |
|---|---|---|
| Transporte | envio SMTP a um relay, 587 STARTTLS ou 465 TLS | a API HTTP de um provedor (um fornecedor, mais um formato de segredo); um servidor de e-mail num contêiner (porta 25 bloqueada, mensagens marcadas como spam) |
| Quando as mensagens são enviadas | tarefas do worker, com novas tentativas | na requisição (um relay lento trava a página, uma falha perde a mensagem); uma coleção de saída separada (um segundo mecanismo de reserva ao lado do das tarefas) |
| Links | token aleatório, só o hash guardado, no fragmento do link | um token assinado sem armazenamento (não pode ser de uso único nem revogado); o token na query string (gravado em logs de acesso, enviado como `Referer`) |
| Validade | 72 horas para convites, 60 minutos para recuperação, configuráveis | um valor para os dois; um dia para recuperação (uma janela maior para uma caixa postal roubada) |
| Usuários novos | convite por padrão quando há endereço, senha temporária ainda possível | só convite (sem como ajudar um usuário cuja caixa postal falha); só senha temporária (o item 3.1 não mudaria nada para usuários novos) |
| Recuperação | nome de usuário ou e-mail, a mesma resposta para todos | só nome de usuário (os usuários esquecem mais o nome que o endereço); uma resposta que diz "conta inexistente" (revela quem tem conta) |
| Notificações | segurança sempre, tarefas em segundo plano opcionais (desligadas) | todas as categorias opcionais (um usuário poderia silenciar o aviso de que alguém trocou sua senha); tudo ligado (ruído) |
| Idioma das mensagens | o do usuário, tirado da página até ele escolher | o da instalação (um usuário português numa instalação em inglês); os dois idiomas em cada mensagem (longas) |
| Textos | no código, nos dois idiomas, conferidos por um teste | arquivos que o operador edita (os textos se afastam do código, dois idiomas fora de sincronia) |
| Experimentar em homologação | Mailpit num perfil do compose | só um relay real (não dá para testar antes de a organização fornecer um); um relay falso no portal (código que a produção carrega à toa) |
| Entrega | três etapas: registro, servidor, telas | uma etapa; quatro (envio, links, notificações, telas) |

## 5. Consequências

- Sem relay nada muda. Com um, os usuários novos e as senhas esquecidas deixam de passar pelas mãos dos
  administradores, e os usuários ficam sabendo das mudanças na sua conta.
- As mensagens do portal são tão confiáveis quanto o relay: a organização precisa dar à instalação um endereço de
  remetente que o seu domínio autorize (SPF, DKIM), ou as mensagens podem cair no spam. O guia do operador lista o
  que pedir aos administradores de e-mail da organização.
- Um link de convite ou de recuperação é uma credencial enquanto vale: quem lê a caixa postal pode escolher a
  senha. A validade é curta, o link funciona uma vez, e o usuário é avisado depois que sua senha mudou.
- O worker agora também envia e-mail: uma instalação que pare o serviço `portal-worker` (com
  `PORTAL_WORKER=external`) enfileira as mensagens até ele voltar (a verificação de saúde já mostra a falta do
  worker).
- Uma conta ou organização desativada não recebe mensagem; remover um usuário remove os seus links, e as suas
  mensagens na fila deixam de ser enviadas (a tarefa confere a conta antes).

## 6. Configuração acrescentada

| Variável | Padrão | |
|---|---|---|
| `PORTAL_MAIL_HOST` | vazio (e-mail desligado) | o nome do servidor relay |
| `PORTAL_MAIL_PORT` | 587 (465 com `tls`, 25 com `none`) | |
| `PORTAL_MAIL_SECURITY` | `starttls` | `starttls`, `tls` ou `none` |
| `PORTAL_MAIL_USERNAME`, `PORTAL_MAIL_PASSWORD` | vazio | as credenciais do relay (obrigatórias com `starttls` ou `tls`, a menos que o relay aceite o servidor pelo endereço) |
| `PORTAL_MAIL_FROM` | vazio | o remetente, `Nome <endereço>` ou um endereço; obrigatório |
| `PORTAL_MAIL_REPLY_TO` | vazio | endereço opcional para respostas (uma central de ajuda) |
| `PORTAL_MAIL_CA_FILE` | vazio | uma autoridade certificadora adicional para o relay (PEM) |
| `PORTAL_MAIL_TIMEOUT` | 20 | segundos para cada passo da conversa com o relay |
| `PORTAL_INVITE_HOURS` | 72 | validade de um link de convite |
| `PORTAL_RESET_MINUTES` | 60 | validade de um link de recuperação |

## 7. Entrega

1. Este registro (nos dois idiomas).
2. No servidor: `portal/mail.py`, `portal/mailtexts.py`, `portal/tokens.py`, `portal/notify.py`; a tarefa `mail`
   e `notBefore` em `jobs.py`; os novos campos das contas em `users.py`; as chamadas da seção 3.7 em `app.py`; a
   coleção `tokens`; a etapa opcional do relay no instalador; o serviço `mailpit` no perfil `mail-test`; um novo
   programa de testes de desenvolvimento `test_mail.py` com o seu próprio relay SMTP.
3. Telas (imagens das telas prontas para revisão, como no item 2.4, já que o dono está ausente): a página de
   acesso, a tela de usuários e *Opções*; os testes de ponta a ponta; os guias do usuário e do desenvolvedor.
