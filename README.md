# FastAPI + Firebase (Firestore/Auth/Storage) — OSINT Backend

## Como subir rápido (Render gratuito)
1. **Baixe** este ZIP e **suba os arquivos** para um repositório no **GitHub** (novo repo).
2. No **Firebase Console** (mesma conta do seu projeto):
   - Vá em **Configurações do projeto ▸ Contas de serviço** → *Gerar nova chave privada* → baixa `service-account.json`.
   - No **Storage**, copie o nome do bucket (geralmente `seu-projeto.appspot.com`).
3. No **Render.com** (plano gratuito):
   - *New ▸ Web Service* → conecte ao repo do GitHub.
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - Em **Environment**:
     - **Add Secret File**: nome `serviceAccount.json` → cole o conteúdo do seu JSON do Firebase.
     - **Env Var** `GOOGLE_APPLICATION_CREDENTIALS=/etc/secrets/serviceAccount.json`
     - **Env Var** `FIREBASE_STORAGE_BUCKET=<seu-bucket>.appspot.com`
   - Deploy.
4. Ao finalizar, o Render mostra sua **URL pública HTTPS**, algo como:
   `https://osint-backend-lite.onrender.com`
   - Teste: `GET /health`.

## Endpoints (todos exigem Auth Firebase, exceto /canary)
- `POST /cases` → cria caso (body opcional: `title`, `description`).
- `GET /cases` → lista casos do usuário.
- `GET /cases/{case_id}` → detalhe do caso.
- `POST /cases/{case_id}/evidences` (form-data: `url`, `headers`, `file`) → adiciona evidência (upload vai pro Storage).
- `GET /cases/{case_id}/evidences` → lista evidências.
- `GET /canary/{case_id}` (público) → registra IP/UA e retorna GIF 1x1.
- `GET /osint/{username}` → checa presença em GitHub/Reddit (exemplo WhatsMyName).

## Como obter o **ID Token** (Firebase Auth) para testar
- Faça login no seu app cliente (web/mobile) com Firebase Auth e pegue `ID Token`.
- Em ferramentas como Postman/curl use header: `Authorization: Bearer <ID_TOKEN>`.

### Exemplo rápido com `curl` (substitua `<TOKEN>` e `<CASE_ID>`)
```bash
curl -H "Authorization: Bearer <TOKEN>" https://SEU_SERVICO.onrender.com/cases
curl -X POST -H "Content-Type: application/json" -H "Authorization: Bearer <TOKEN>" \
  -d '{"title":"Caso A","description":"Teste"}' \
  https://SEU_SERVICO.onrender.com/cases

curl -H "Authorization: Bearer <TOKEN>" https://SEU_SERVICO.onrender.com/osint/usuario_teste

# após criar um caso:
curl https://SEU_SERVICO.onrender.com/canary/<CASE_ID>  -v
```

## Observações
- **Não** faça commit do `service-account.json` no GitHub. Use sempre **Secret File** no Render.
- O endpoint `/canary/{case_id}` é público por design (isca). Use com responsabilidade e amparo jurídico.
- Este backend faz controle de acesso por **UID** (cada usuário só enxerga seus próprios casos/evidências).
