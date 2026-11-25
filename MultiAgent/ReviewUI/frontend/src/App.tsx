// Draft review UI: run bar (left) + tabs Review / LLM feedback / Supervisor.
import { useCallback, useEffect, useState } from 'react'
import {
  Alert, AppBar, Backdrop, Box, Button, CircularProgress, Divider, Drawer, MenuItem, Snackbar, Stack, Tab, Tabs,
  TextField, Toolbar, Typography,
} from '@mui/material'
import { api, type Config, type Run, type RunSummary } from './api'
import ReviewTab from './ReviewTab'
import FeedbackTab from './FeedbackTab'
import SupervisorTab from './SupervisorTab'

const SIDE = 300

export default function App() {
  const [cfg, setCfg] = useState<Config | null>(null)
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [runId, setRunId] = useState('')
  const [run, setRun] = useState<Run | null>(null)
  const [tab, setTab] = useState('review')
  const [busyMsg, setBusyMsg] = useState('')
  const [msg, setMsg] = useState<{ text: string; error: boolean } | null>(null)
  const [units, setUnits] = useState('')
  const [seed, setSeed] = useState('0')
  const [perKey, setPerKey] = useState<Record<string, { min: string; max: string }>>({})

  const notify = useCallback((text: string, error = false) => setMsg({ text, error }), [])
  const busy = useCallback(<T,>(m: string, p: Promise<T>): Promise<T> => {
    setBusyMsg(m)
    return p.finally(() => setBusyMsg(''))
  }, [])

  const loadRuns = useCallback(
    (select?: string) =>
      api<RunSummary[]>('/runs')
        .then((r) => { setRuns(r); setRunId((cur) => select ?? (cur && r.some((x) => x.run_id === cur) ? cur : r[0]?.run_id ?? '')) })
        .catch((e) => notify(String(e), true)),
    [notify],
  )
  const loadRun = useCallback(() => {
    if (!runId) { setRun(null); return }
    api<Run>(`/runs/${runId}`).then(setRun).catch((e) => notify(String(e), true))
  }, [runId, notify])
  const reload = useCallback(() => { loadRun(); loadRuns() }, [loadRun, loadRuns])

  useEffect(() => {
    api<Config>('/config')
      .then((c) => { setCfg(c); setUnits(String(c.units)) })
      .catch((e) => notify(`Cannot load the config (is the API running?): ${e}`, true))
    loadRuns()
  }, [loadRuns, notify])
  useEffect(loadRun, [loadRun])

  // Nothing is pre-filled: every related table needs an explicit min and max before Execute is enabled.
  const problems = cfg
    ? Object.keys(cfg.children).flatMap((c) => {
        const p = perKey[c]
        if (!p?.min || !p?.max) return [`${c}: enter min and max`]
        return Number(p.min) > Number(p.max) ? [`${c}: min must not exceed max`] : []
      })
    : ['config not loaded']
  const execute = (label: string) =>
    busy(label, api<{ run_id: string }>('/runs', 'POST', {
      units: Number(units), seed: Number(seed) || null,
      per_key: Object.fromEntries(Object.entries(perKey).map(([c, p]) => [c, [Number(p.min), Number(p.max)]])),
    }))
      .then((r) => { notify(`Run ${r.run_id} created`); loadRuns(r.run_id) })
      .catch((e) => notify(String(e), true))
  const current = runs.find((r) => r.run_id === runId)

  return (
    <Box sx={{ display: 'flex' }}>
      <AppBar position="fixed" sx={{ zIndex: (t) => t.zIndex.drawer + 1 }}>
        <Toolbar variant="dense">
          <Typography variant="h6" sx={{ flexGrow: 1 }}>Generated drafts - review</Typography>
          {cfg && <Typography variant="body2">{cfg.parent} · database {cfg.db_name}</Typography>}
        </Toolbar>
      </AppBar>
      <Drawer variant="permanent" sx={{ width: SIDE, [`& .MuiDrawer-paper`]: { width: SIDE, p: 2, boxSizing: 'border-box' } }}>
        <Toolbar variant="dense" />
        <Stack spacing={1.5}>
          <Typography variant="subtitle1">Run</Typography>
          <Stack direction="row" spacing={1}>
            <TextField label="Units" type="number" value={units} onChange={(e) => setUnits(e.target.value)} inputProps={{ min: 1, max: 500 }} />
            <TextField label="Seed (0 = random)" type="number" value={seed} onChange={(e) => setSeed(e.target.value)} inputProps={{ min: 0 }} />
          </Stack>
          {cfg && Object.entries(cfg.children).map(([c, info]) => (
            <Box key={c}>
              <Typography variant="body2" fontWeight={600}>{c}</Typography>
              <Typography variant="caption" color="text.secondary">
                {info.key_field} → {cfg.parent}.{cfg.key_field} (config default {info.min}..{info.max})
              </Typography>
              <Stack direction="row" spacing={1} sx={{ mt: 0.5 }}>
                {(['min', 'max'] as const).map((k) => (
                  <TextField key={k} label={k} type="number" placeholder="required" inputProps={{ min: 1 }}
                    value={perKey[c]?.[k] ?? ''} onChange={(e) => setPerKey((p) => ({ ...p, [c]: { ...(p[c] ?? { min: '', max: '' }), [k]: e.target.value } }))} />
                ))}
              </Stack>
            </Box>
          ))}
          {problems.map((p) => <Typography key={p} variant="caption" color="error">{p}</Typography>)}
          <Button variant="contained" disabled={problems.length > 0} onClick={() => execute('Supervisor: generate -> repair -> LLM ...')}>Execute</Button>
          <Divider />
          <TextField select label="Run file" value={runId} onChange={(e) => setRunId(e.target.value)} disabled={!runs.length}>
            {runs.map((r) => (
              <MenuItem key={r.run_id} value={r.run_id}>{r.run_id} · {r.completed}/{r.units} done{r.needs_review ? ` · ${r.needs_review} to review` : ''}</MenuItem>
            ))}
          </TextField>
          {current?.done && (
            <Button variant="outlined" disabled={problems.length > 0} onClick={() => execute('Running again (new run with the saved weights, supervised)...')}
              title="One new run with the settings above and the SAVED LLM feedback weights">Run again</Button>
          )}
          <Button onClick={reload} disabled={!runId}>Refresh</Button>
        </Stack>
      </Drawer>
      <Box component="main" sx={{ flexGrow: 1, p: 2, minWidth: 0 }}>
        <Toolbar variant="dense" />
        <Tabs value={tab} onChange={(_, t) => setTab(t)} sx={{ mb: 2 }}>
          <Tab value="review" label="Review" />
          <Tab value="feedback" label="LLM feedback" />
          <Tab value="supervisor" label={`Supervisor${run?.audit ? ` (audit: ${Object.values(run.audit.summary).reduce((n, s) => n + s.violations, 0)})` : ''}`} />
        </Tabs>
        {tab === 'feedback' && cfg && <FeedbackTab cfg={cfg} notify={notify} />}
        {tab !== 'feedback' && !run && (
          <Alert severity="info">{runs.length ? 'Loading the run...' : "No runs yet. Fill in the related tables and press 'Execute'."}</Alert>
        )}
        {tab === 'review' && run && cfg && <ReviewTab run={run} cfg={cfg} busy={busy} notify={notify} reload={reload} />}
        {tab === 'supervisor' && run && <SupervisorTab run={run} />}
      </Box>
      <Backdrop open={!!busyMsg} sx={{ zIndex: (t) => t.zIndex.modal + 1, color: '#fff', flexDirection: 'column', gap: 2 }}>
        <CircularProgress color="inherit" />
        <Typography>{busyMsg}</Typography>
      </Backdrop>
      <Snackbar open={!!msg} autoHideDuration={msg?.error ? null : 5000} onClose={() => setMsg(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}>
        <Alert severity={msg?.error ? 'error' : 'success'} onClose={() => setMsg(null)}>{msg?.text}</Alert>
      </Snackbar>
    </Box>
  )
}
