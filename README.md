# FindIt AI — Frontend

React (Vite) app for FindIt AI. It talks to the FastAPI backend in `../findit-backend`; every API call lives in `src/api/client.js`.

## Run

```bash
# 1. backend (in ../findit-backend)
docker compose up -d db && python -m app.seed && uvicorn app.main:app --reload

# 2. frontend
cp .env.example .env      # VITE_API_URL=http://localhost:8000/api/v1
npm install
npm run dev               # http://localhost:5173
```

Sign in with the seeded demo account: `demo@findit.demo` / `demo12345` (the login page has a "Fill demo account" button).

## Pages

| Route | Page |
|---|---|
| `#/` | Home: hero search, live counts, recent reports, how it works |
| `#/items` | Find items: search, lost/found, category, location, date filters, load more |
| `#/items/:id` | Item details, top matches, claim request (owners can mark returned, close or delete) |
| `#/report/lost`, `#/report/found` | Report form with validation, photo preview, optional "add my location" |
| `#/matches/:id` | AI matching: pick one of your reports, see ranked matches with score breakdown and explanation |
| `#/dashboard` | Totals, your numbers, activity, claim requests (approve, decline, withdraw), your reports |
| `#/auth` | Sign in / create account |

## Demo walkthrough

1. Sign in as the demo account, then **Report lost item**: black backpack, description, photo, location, date.
2. You land on **AI matching** for that report. The backend indexes it in the background; the page shows a short loading state, then ranked found items.
3. **Find items**: search "backpack".
4. Open a match, **Claim this item**, add a message and a detail only the owner would know.
5. **Dashboard** shows the pending claim. Sign in as `asha@findit.demo` (owner of the seeded found backpack) to approve it.

## Honest labelling

- When the backend runs with `EMBEDDING_BACKEND=demo`, the matching page shows a "Demo scoring" banner: scores are simulated (colour patterns and keywords), not CLIP or SentenceTransformer. With `real`, the banner describes the real models instead.
- Counts on Home and Dashboard are live database numbers; the seeded sample reports are demo data.
- Claim requests are reviewed by the report owner and are not proof of identity. Contact details are never displayed.

## Structure

```
src/
  api/client.js        service layer (fetch, auth token, error messages)
  context.jsx          auth, toast and meta (categories, scoring) providers
  router.js            tiny hash router
  hooks.js, useMatches.js   data loading, match polling while the server indexes
  components/          Chrome (nav/footer), ui (cards, badges, rings, modal, fields), MatchCard, ClaimModal
  pages/               Home, FindItems, ItemDetail, Report, Matching, Dashboard, Auth
```
