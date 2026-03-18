---
name: devflow-learned-vercel-deploy-workaround
description: Diagnose and work around Vercel "Unexpected error" deploy failures caused by broken GitHub integration
trigger: Vercel deploy fails with "Unexpected error. Please try again later." — especially when builds show READY with empty output in <1s
type: learned
---

# Vercel Deploy "Unexpected Error" — Broken GitHub Integration

## Symptom

- `vercel --prod` or git push both fail with: `Error: Unexpected error. Please try again later.`
- `vercel inspect` shows build `readyState: "READY"` but output `[]` and deployment `readyState: "ERROR"`
- Build completes in ~260ms (never actually executes)
- Account is NOT soft-blocked, billing is active

## Diagnosis

1. List recent deployments: `npx vercel ls | head -15`
2. Check which ones succeeded vs failed, noting the `source` column
3. Use Vercel API to inspect deploy metadata:
   ```bash
   TOKEN=$(python3 -c "import json; print(json.load(open('$HOME/Library/Application Support/com.vercel.cli/auth.json'))['token'])")
   curl -s -H "Authorization: Bearer $TOKEN" \
     "https://api.vercel.com/v6/deployments?projectId=<PROJECT_ID>&teamId=<TEAM_ID>&limit=15" \
     | python3 -c "
   import sys,json
   for dep in json.load(sys.stdin).get('deployments',[]):
       state = dep.get('readyState','?')
       src = dep.get('source','?')
       sha = dep.get('meta',{}).get('githubCommitSha','N/A')[:8]
       msg = dep.get('meta',{}).get('githubCommitMessage','N/A')[:60]
       print(f'{state:8s} | {src:8s} | {sha} | {msg}')
   "
   ```
4. **Key pattern:** If all deploys with git metadata (githubCommitSha present) fail, but CLI deploys without git metadata (N/A) succeed — the GitHub integration is broken.

## Workaround — Deploy Without Git

```bash
# 1. Copy project without .git to a temp directory
rsync -a --exclude='.git' --exclude='node_modules' --exclude='.next' --exclude='.vercel' \
  /path/to/project/ /tmp/project-deploy/

# 2. Link to Vercel project
mkdir -p /tmp/project-deploy/.vercel
cp /path/to/project/.vercel/project.json /tmp/project-deploy/.vercel/project.json

# 3. Deploy from the git-free directory
cd /tmp/project-deploy && npx vercel --prod --yes
```

## Permanent Fix

Reconnect the GitHub integration in the Vercel dashboard:
1. Go to Project > Settings > Git
2. Disconnect the GitHub repository
3. Reconnect with the same repository
4. Test with a git push

## Related

- Vercel Hobby plan also blocks deploys with `Co-Authored-By` trailers from non-owner accounts (see `feedback_no_coauthor_vercel.md`)
- Project settings (like `nodeVersion`) can be checked/updated via API: `PATCH https://api.vercel.com/v9/projects/<ID>`
