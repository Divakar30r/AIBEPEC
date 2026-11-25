// Unit review. 'All units' is the entry point: the Key opens the unit in a window of almost the whole page -
// editable for a unit under review, view-only for a completed one. In it: every record of every table, flagged
// cells red, LLM-converted / -proposed cells blue, your pending edits yellow; Edit (per record) opens the record
// dialog with every field editable; Before/After shows the values before the LLM changed them vs now. A related
// record's Options = Delete freezes the row and deletes it on re-run. Nothing reaches the run file until
// "Apply changes & re-run".
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Accordion, AccordionDetails, AccordionSummary, Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent,
  DialogTitle, IconButton, Link, MenuItem, Slider, Stack, TextField, ToggleButton, ToggleButtonGroup, Tooltip, Typography,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import EditIcon from '@mui/icons-material/Edit'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import { api, type Config, type Row, type Run, type Unit, type Violation } from './api'
import { EditableGrid, show, type GridCol } from './EditableGrid'
import RecordDialog from './RecordDialog'

type Busy = <T>(msg: string, p: Promise<T>) => Promise<T>
interface Ctx { run: Run; cfg: Config; busy: Busy; notify: (m: string, e?: boolean) => void; reload: () => void }

const ck = (t: string, r: number | null | undefined, f: string) => `${t}|${r ?? 'p'}|${f}`
const DELETE = 'Delete'

export default function ReviewTab(ctx: Ctx) {
  const { run, busy, notify, reload } = ctx
  const units = run.units
  const [openId, setOpenId] = useState<number | null>(null)
  const open = units.find((u) => u.unit_id === openId) ?? null // gone (deleted) -> the window closes
  const withA = units.filter((u) => u.status === 'needs_review' && u.llm_review?.conversions?.length).map((u) => u.unit_id)
  const nCount = units.reduce((n, u) => n + u.violations.filter((v) => v.kind === 'count').length, 0)
  const overview = useMemo(
    () =>
      units.map((u) => ({
        unit: u.unit_id, key: u.key, status: u.status, halted_before_level: u.halted_before_level,
        attempts: u.attempts ?? 0, llm: u.llm_review?.status ?? '',
        field_errors: u.violations.filter((v) => (v.kind ?? 'field') === 'field').length,
        count_errors: u.violations.filter((v) => v.kind === 'count').length,
      })),
    [units],
  )
  const ovCols: GridCol[] = [
    { key: 'unit', header: 'Unit', size: 70, filter: 'none' },
    {
      key: 'key', header: 'Key (open)', filter: 'text', group: false,
      render: (r) => (
        <Tooltip title={r.status === 'completed' ? 'Open to view' : 'Open to edit'}>
          <Link component="button" variant="body2" underline="always" onClick={() => setOpenId(r.unit)}>{r.key}</Link>
        </Tooltip>
      ),
    },
    { key: 'status', header: 'Status', filter: 'multi', tone: (r) => (r.status !== 'completed' ? 'bad' : undefined) },
    { key: 'halted_before_level', header: 'Halted before level', filter: 'multi' },
    { key: 'field_errors', header: 'Field errors', filter: 'range' },
    { key: 'count_errors', header: 'Count errors', filter: 'range' },
    { key: 'attempts', header: 'Re-runs', filter: 'range' },
    { key: 'llm', header: 'LLM review', filter: 'multi' },
  ]
  const applyA = () =>
    busy('Applying LLM conversions and re-running...', api<Record<string, string>>(`/runs/${run.run_id}/llm-apply`, 'POST', { unit_ids: withA }))
      .then((r) => { notify(Object.entries(r).map(([k, v]) => `unit ${k}: ${v}`).join(', ') || 'Nothing applied'); reload() })
      .catch((e) => notify(String(e), true))

  return (
    <Box>
      {run.warnings.map((w) => <Alert key={w} severity="warning" sx={{ mb: 1 }}>{w}</Alert>)}
      <Stack direction="row" spacing={1} sx={{ mb: 1 }}>
        <Chip label={`Units ${units.length}`} />
        <Chip color="success" label={`Completed ${units.filter((u) => u.status === 'completed').length}`} />
        <Chip color="warning" label={`Needs review ${units.filter((u) => u.status === 'needs_review').length}`} />
        <Chip color="error" label={`Error ${units.filter((u) => u.status === 'error').length}`} />
        <Chip label={`Count rule errors ${nCount}`} />
      </Stack>
      <Accordion disableGutters>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>Level plan (evaluation order)</AccordionSummary>
        <AccordionDetails>
          {run.levels.map((lv, i) => <Typography key={i} variant="body2"><b>Level {i}</b>: {lv.join(', ')}</Typography>)}
        </AccordionDetails>
      </Accordion>
      <Stack direction="row" alignItems="center" spacing={2} sx={{ mt: 2, mb: 1 }}>
        <Typography variant="h6">All units</Typography>
        <Typography variant="body2" color="text.secondary">Click a Key to open the unit (edit if under review, view if completed).</Typography>
        <Box flexGrow={1} />
        {withA.length > 0 && (
          <Button variant="contained" onClick={applyA}>Apply LLM conversions (A) to all {withA.length} unit(s) & re-run</Button>
        )}
      </Stack>
      <EditableGrid rows={overview} getId={(r) => String(r.unit)} columns={ovCols} maxHeight={640}
        rowTone={(r) => (r.unit === openId ? 'changed' : undefined)} />
      {open && <UnitDialog key={open.unit_id} u={open} {...ctx} onClose={() => setOpenId(null)} />}
    </Box>
  )
}

/** The unit in a window of almost the whole page; closing with pending changes asks first. */
function UnitDialog({ u, onClose, ...ctx }: Ctx & { u: Unit; onClose: () => void }) {
  const dirty = useRef(false)
  const close = () => {
    if (dirty.current && !window.confirm('Close and discard the pending changes of this unit?')) return
    onClose()
  }
  const rv = u.llm_review
  const stage = u.halted_before_level !== null ? `halted before level ${u.halted_before_level}` : u.status
  return (
    <Dialog open onClose={close} maxWidth={false} scroll="paper"
      PaperProps={{ sx: { width: '97vw', height: '95vh', maxWidth: 'none', m: 1 } }}>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1, py: 1 }}>
        <Box flexGrow={1}>
          <b>Unit {u.unit_id} - {u.key}</b> · {u.status} ({stage}){rv ? ` · LLM: ${rv.status}` : ''}
          {u.attempts ? ` · re-runs: ${u.attempts}` : ''}
          {u.status === 'completed' && <Chip size="small" label="view only" sx={{ ml: 1 }} />}
        </Box>
        <IconButton onClick={close} title="Close"><CloseIcon /></IconButton>
      </DialogTitle>
      <DialogContent dividers>
        <UnitBody key={`${u.unit_id}_${u.attempts ?? 0}`} u={u} {...ctx}
          onDirty={(d) => { dirty.current = d }} onGone={onClose} />
      </DialogContent>
    </Dialog>
  )
}

function fieldsOf(data: Row | Row[]): string[] {
  const rows = Array.isArray(data) ? data : [data]
  return [...new Set(rows.flatMap((r) => Object.keys(r)))]
}

const nonEmpty = (d: Record<string, number[]>) => Object.fromEntries(Object.entries(d).filter(([, v]) => v.length))

function UnitBody({ u, run, cfg, busy, notify, reload, onDirty, onGone }: Ctx & {
  u: Unit; onDirty: (dirty: boolean) => void; onGone: () => void
}) {
  const plan = u.edit
  // pending changes: LLM proposals (prefill) that differ from the current value apply unless changed
  const [start] = useState(() => {
    const f = Object.fromEntries((plan?.cells ?? []).filter((c) => c.prefill != null && show(c.prefill) !== show(c.current))
      .map((c) => [ck(c.table, c.record, c.field), c.prefill]))
    const d = { ...(plan?.delete ?? {}) }
    return { f, d, key: JSON.stringify([f, nonEmpty(d)]) }
  })
  const [fixes, setFixes] = useState<Record<string, unknown>>(start.f)
  const [dels, setDels] = useState<Record<string, number[]>>(start.d)
  useEffect(() => onDirty(JSON.stringify([fixes, nonEmpty(dels)]) !== start.key), [fixes, dels, start, onDirty])
  const [fbOpen, setFbOpen] = useState(false)
  const [rmOpen, setRmOpen] = useState(false)
  const [view, setView] = useState<'before' | 'after'>('after')
  const listErrors = u.violations.filter((v) => cfg.list_fields.includes(`${v.table}.${v.field}`)).length
  const [editing, setEditing] = useState<{ table: string; rec: number | null } | null>(null)
  const rv = u.llm_review
  const bad = useMemo(() => {
    const s = new Set<string>()
    u.violations.forEach((v: Violation) => {
      if (v.kind === 'count') (v.records ?? []).forEach((r) => s.add(ck(v.table, r, v.field)))
      else s.add(ck(v.table, v.record, v.field))
    })
    return s
  }, [u.violations])
  // cells the LLM converted (value before it) and cells it proposes (value it proposes)
  const llmApplied = useMemo(() => {
    const m = new Map<string, unknown>()
    for (const c of u.llm_applied ?? []) {
      const k = ck(c.table, c.record, c.field)
      if (!m.has(k)) m.set(k, c.from)
    }
    return m
  }, [u.llm_applied])
  const llmProposed = useMemo(
    () => new Map((plan?.cells ?? []).filter((c) => c.prefill != null && show(c.prefill) !== show(c.current))
      .map((c) => [ck(c.table, c.record, c.field), c.prefill] as [string, unknown])),
    [plan],
  )
  const halted = u.status === 'needs_review'
  const completed = u.status === 'completed'

  const onOpt = useCallback(
    (table: string) => (id: string, key: string, value: unknown) => {
      if (key !== '_opt') return
      const rec = Number(id)
      setDels((d) => {
        const cur = new Set(d[table] ?? [])
        if (value === DELETE) cur.add(rec)
        else cur.delete(rec)
        return { ...d, [table]: [...cur].sort((a, b) => a - b) }
      })
    },
    [],
  )
  // Save in the Edit dialog: this record's values become pending changes (a value back to the stored one is dropped)
  const saveRecord = (table: string, rec: number | null, vals: Row) => {
    const d = u.draft[table]
    const stored: Row = (Array.isArray(d) ? d[rec as number] : d) ?? {}
    setFixes((f) => {
      const out = { ...f }
      Object.entries(vals).forEach(([field, v]) => {
        const k = ck(table, rec, field)
        if (show(v) === show(stored[field])) delete out[k]
        else out[k] = v
      })
      return out
    })
    setEditing(null)
  }

  const fixList = Object.entries(fixes).map(([k, value]) => {
    const [table, r, field] = k.split('|')
    return { table, record: r === 'p' ? null : Number(r), field, value }
  })
  const delList = Object.fromEntries(Object.entries(dels).filter(([, v]) => v.length))
  const ready = fixList.length > 0 || Object.keys(delList).length > 0
  const pendingA = (rv?.conversions ?? []).filter((c: Row) => {
    const t = u.draft[c.table]
    const row = Array.isArray(t) ? t[c.record] : t
    return row && c.field in row && show(row[c.field]) !== show(c.to)
  })

  const rerun = () =>
    busy('Re-running, then supervisor: repair -> LLM -> (wait | audit) ...',
      api<{ status: string }>(`/runs/${run.run_id}/units/${u.unit_id}/rerun`, 'POST', { fixes: fixList, deletions: delList }))
      .then((r) => {
        notify(`Unit ${u.unit_id}: ${r.status}`)
        if (r.status === 'completed') onGone() // done: close the unit window; halted again -> stay open
        reload()
      })
      .catch((e) => notify(String(e), true))
  const applyA = () =>
    busy('Applying LLM conversions and re-running...', api<Record<string, string>>(`/runs/${run.run_id}/llm-apply`, 'POST', { unit_ids: [u.unit_id] }))
      .then((r) => {
        const st = r[String(u.unit_id)]
        notify(`Unit ${u.unit_id}: ${st ?? 'nothing applied'}`)
        if (st === 'completed') onGone()
        reload()
      })
      .catch((e) => notify(String(e), true))
  const removeUnit = () =>
    busy('Deleting unit...', api(`/runs/${run.run_id}/units/${u.unit_id}`, 'DELETE'))
      .then(() => { notify(`Unit ${u.unit_id} deleted`); setRmOpen(false); onGone(); reload() })
      .catch((e) => notify(String(e), true))

  return (
    <Box>
        <Stack direction="row" spacing={1} sx={{ mb: 1 }} alignItems="center">
          <ToggleButtonGroup size="small" exclusive value={view} onChange={(_, v) => v && setView(v)}>
            <ToggleButton value="before">Before LLM</ToggleButton>
            <ToggleButton value="after">After LLM</ToggleButton>
          </ToggleButtonGroup>
          <Typography variant="caption" color="text.secondary">
            {view === 'before' ? 'Values before the LLM converted them (blue = cells the LLM changed or proposes). Read-only.'
              : 'Now, with the LLM proposals: red = flagged · blue = LLM converted / proposed · yellow = your edit · struck = to delete'}
          </Typography>
          <Box flexGrow={1} />
          {!completed && (
            <>
              <Tooltip title={listErrors ? '' : 'Only errors on list-type fields can go into LLM feedback'}>
                <span><Button variant="outlined" disabled={!listErrors} onClick={() => setFbOpen(true)}>Add error to LLM feedback</Button></span>
              </Tooltip>
              <Button variant="outlined" color="error" onClick={() => setRmOpen(true)}>Remove unit</Button>
            </>
          )}
        </Stack>
        {Object.entries(u.draft).map(([table, data]) => (
          <UnitTable key={table} table={table} data={data} cfg={cfg} fixes={fixes} dels={dels[table] ?? []} bad={bad}
            view={view} llmApplied={llmApplied} llmProposed={llmProposed} onOpt={onOpt(table)}
            onEditRow={(rec) => setEditing({ table, rec })} editable={halted} />
        ))}
        {editing && (
          <RecordDialog u={u} cfg={cfg} table={editing.table} rec={editing.rec} fixes={fixes} flagged={bad}
            onSave={(vals) => saveRecord(editing.table, editing.rec, vals)} onClose={() => setEditing(null)} />
        )}
        {u.notes.length > 0 && (
          <Accordion disableGutters variant="outlined">
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>Notes ({u.notes.length})</AccordionSummary>
            <AccordionDetails>{u.notes.map((n, i) => <Typography key={i} variant="caption" display="block">{n}</Typography>)}</AccordionDetails>
          </Accordion>
        )}
        {rv ? (
          <Box sx={{ mt: 1 }}>
            <Typography variant="body2"><b>LLM review of this halt</b>: {rv.status}, {rv.rounds} round(s), trigger {rv.trigger ?? 'run'}
              {rv.conflicts?.length ? ` · conflicts: ${rv.conflicts.join('; ')}` : ''}</Typography>
            {pendingA.length > 0 && halted && (
              <Stack direction="row" spacing={1} alignItems="center" sx={{ my: 1 }}>
                <Typography variant="body2">A) not applied yet: {pendingA.map((c: Row) => `${c.table}.${c.field}=${show(c.to)}`).join(', ')}</Typography>
                <Button variant="outlined" onClick={applyA}>Apply LLM conversions (A) & re-run</Button>
              </Stack>
            )}
            {(['count_decisions', 'suggestions'] as const).filter((k) => rv[k]?.length).map((k) => (
              <Box key={k} sx={{ mt: 1 }}>
                <Typography variant="caption">{k === 'count_decisions' ? 'B) Count decisions' : 'C) Suggestions (prefilled above)'}</Typography>
                <EditableGrid rows={rv[k].map((r: Row, i: number) => ({ ...r, _i: i }))} getId={(r) => String(r._i)}
                  columns={Object.keys(rv[k][0]).map((f) => ({ key: f, header: f, filter: 'none' as const }))} groupBy={false} compact />
              </Box>
            ))}
          </Box>
        ) : halted ? <Typography variant="caption">No LLM review for this attempt (disabled, failed, or still running).</Typography> : null}
        {halted && (
          <Stack direction="row" spacing={2} alignItems="center" sx={{ mt: 2 }}>
            <Button variant="contained" disabled={!ready} onClick={rerun}>
              Apply changes & re-run from level {u.halted_before_level}
            </Button>
            <Typography variant="body2" color="text.secondary">
              {ready ? 'Will change: ' + [...fixList.map((f) => `${f.table}.${f.field}${f.record !== null ? `[${f.record}]` : ''} = ${show(f.value)}`),
                ...Object.entries(delList).map(([t, rs]) => `delete ${t} records ${rs.join(', ')}`)].join(' · ')
                : 'Edit a record (pencil), or set a related record to Delete'}
            </Typography>
          </Stack>
        )}
        {fbOpen && <FeedbackDialog u={u} run={run} cfg={cfg} onClose={() => setFbOpen(false)} notify={notify} reload={reload} busy={busy} />}
        <Dialog open={rmOpen} onClose={() => setRmOpen(false)}>
          <DialogTitle>Delete unit {u.unit_id} ({u.key})?</DialogTitle>
          <DialogContent>Deletes the {cfg.parent} record and all its related records from this run.</DialogContent>
          <DialogActions>
            <Button onClick={() => setRmOpen(false)}>Cancel</Button>
            <Button color="error" variant="contained" onClick={removeUnit}>Delete unit</Button>
          </DialogActions>
        </Dialog>
    </Box>
  )
}

function UnitTable({ table, data, cfg, fixes, dels, bad, view, llmApplied, llmProposed, onOpt, onEditRow, editable }: {
  table: string; data: Row | Row[]; cfg: Config; fixes: Record<string, unknown>; dels: number[]; bad: Set<string>
  view: 'before' | 'after'; llmApplied: Map<string, unknown>; llmProposed: Map<string, unknown>
  onOpt: (id: string, key: string, value: unknown) => void; onEditRow: (rec: number | null) => void; editable: boolean
}) {
  const isChild = Array.isArray(data)
  const fields = fieldsOf(data)
  const after = view === 'after'
  const rows = (isChild ? (data as Row[]) : [data as Row]).map((r, i) => {
    const rec = isChild ? i : null
    const out: Row = { ...r, _id: isChild ? String(i) : 'p', _rec: rec, _opt: isChild && dels.includes(i) ? DELETE : null }
    fields.forEach((f) => {
      const k = ck(table, rec, f)
      if (after && k in fixes) out[f] = fixes[k] // pending: LLM proposals + your saved edits
      else if (!after && llmApplied.has(k)) out[f] = llmApplied.get(k) // the value before the LLM changed it
    })
    return out
  })
  const columns: GridCol[] = [
    ...(isChild ? [
      { key: '_rec', header: '#', size: 50, filter: 'none' as const, group: false },
      ...(editable && after ? [{ key: '_opt', header: 'Options', size: 120, spec: () => ({ editor: 'choice' as const, options: [DELETE] }) }] : []),
    ] : []),
    ...fields.map((f): GridCol => ({
      key: f, header: f, filter: isChild ? 'multi' : 'none',
      tone: (r) => {
        const k = ck(table, r._rec, f)
        const llm = llmApplied.has(k) || llmProposed.has(k)
        if (!after) return llm ? 'llm' : undefined
        if (r._opt === DELETE) return 'muted'
        if (k in fixes) return llmProposed.has(k) && show(llmProposed.get(k)) === show(fixes[k]) ? 'llm' : 'changed'
        return bad.has(k) ? 'bad' : llm ? 'llm' : undefined
      },
    })),
  ]
  const kf = table === cfg.parent ? cfg.key_field : cfg.children[table]?.key_field
  const canEdit = editable && after
  return (
    <Box sx={{ mb: 1 }}>
      <Typography variant="body2" fontWeight={600}>{table}{kf ? ` (key ${kf})` : ''}</Typography>
      <EditableGrid rows={rows} getId={(r) => r._id} columns={columns} onEdit={canEdit ? onOpt : undefined} groupBy={false} compact
        rowAction={canEdit ? (r) => (
          <Tooltip title="Edit this record">
            <span>
              <IconButton size="small" disabled={r._opt === DELETE} onClick={() => onEditRow(r._rec)}><EditIcon fontSize="small" /></IconButton>
            </span>
          </Tooltip>
        ) : undefined} />
    </Box>
  )
}

// ------------------------------------------------------------------------------------- add error to feedback
function FeedbackDialog({ u, run, cfg, onClose, notify, reload, busy }: {
  u: Unit; run: Run; cfg: Config; onClose: () => void; notify: (m: string, e?: boolean) => void; reload: () => void; busy: Busy
}) {
  const label = (v: Violation) =>
    `${v.kind === 'count' ? 'count' : 'value'}: ${v.table}.${v.field}${v.record != null ? `[${v.record}]` : ''} = ${show(v.value)}`
  const [idx, setIdx] = useState(0)
  const errs = u.violations.filter((x) => cfg.list_fields.includes(`${x.table}.${x.field}`)) // list-type only
  const v = errs[idx]
  const isCount = v.kind === 'count'
  const parent = u.draft[cfg.parent] as Row
  const proposals = Object.fromEntries([...(u.llm_review?.conversions ?? []), ...(u.llm_review?.count_decisions ?? [])]
    .map((c: Row) => [ck(c.table, c.record, c.field), c.to]))
  const hint = (u.llm_review?.count_decisions ?? []).find((c: Row) => c.count_field === `${v.table}.${v.field}`)?.parent_field
  const parentFields = Object.keys(parent).filter((k) => k !== cfg.key_field).map((k) => `${cfg.parent}.${k}`)
    .filter((f) => cfg.list_fields.includes(f))
  const [to, setTo] = useState(show(proposals[ck(v.table, v.record, v.field)] ?? ''))
  const [pf, setPf] = useState<string>(parentFields.includes(hint) ? hint : '')
  const [pval, setPval] = useState(pf ? show(parent[pf.split('.')[1]]) : '')
  const [rfv, setRfv] = useState(show(v.value))
  const [count, setCount] = useState(Number(v.count ?? 0))
  const [w, setW] = useState(isCount ? -1 : 1)
  const pick = (i: number) => {
    const nv = errs[i]
    setIdx(i); setTo(show(proposals[ck(nv.table, nv.record, nv.field)] ?? '')); setRfv(show(nv.value))
    setCount(Number(nv.count ?? 0)); setW(nv.kind === 'count' ? -1 : 1)
  }
  const never = w <= -1
  const ok = isCount ? !!pf && rfv.trim() !== '' : to.trim() !== ''
  const confirm = () => {
    const cur = v.value
    const row = isCount
      ? { RelatedTable: v.table, RelatedField: `${v.table}.${v.field}`, RelatedFieldValue: rfv, Field: pf, value: pval, Count: count, Weightage: w }
      : { Table: v.table, Field: v.field, Type: typeof cur === 'number' ? 'number' : 'text', current_value: cur, LLM_value: to, Weightage: w }
    busy('Adding to LLM feedback...', api<{ unit_removed: boolean }>('/feedback/pair', 'POST',
      { section: isCount ? 'Count-based' : 'Value-based', row, run_id: run.run_id, unit_id: u.unit_id }))
      .then((r) => { notify(`Added to LLM feedback${r.unit_removed ? `; unit ${u.unit_id} removed` : ''}`); onClose(); reload() })
      .catch((e) => notify(String(e), true))
  }
  return (
    <Dialog open onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>Add to LLM feedback</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <TextField select label="Error" value={idx} onChange={(e) => pick(Number(e.target.value))}>
            {errs.map((x, i) => <MenuItem key={i} value={i}>{label(x)}</MenuItem>)}
          </TextField>
          {isCount ? (
            <>
              <Stack direction="row" spacing={2}>
                <TextField select label="Field (parent)" value={pf} sx={{ flex: 1 }} helperText="Prefilled from the LLM's B) decision when there is one"
                  onChange={(e) => { setPf(e.target.value); setPval(show(parent[e.target.value.split('.')[1]])) }}>
                  {parentFields.map((f) => <MenuItem key={f} value={f}>{f}</MenuItem>)}
                </TextField>
                <TextField label="value" value={pval} onChange={(e) => setPval(e.target.value)} sx={{ flex: 1 }} />
              </Stack>
              <Stack direction="row" spacing={2}>
                <TextField label="RelatedField" value={`${v.table}.${v.field}`} disabled sx={{ flex: 1 }} />
                <TextField label="RelatedFieldValue" value={rfv} onChange={(e) => setRfv(e.target.value)} sx={{ flex: 1 }} />
                <TextField label="Count" type="number" value={count} onChange={(e) => setCount(Number(e.target.value))} sx={{ width: 120 }} />
              </Stack>
            </>
          ) : (
            <Stack direction="row" spacing={2}>
              <TextField label="Table.Field" value={`${v.table}.${v.field}`} disabled sx={{ flex: 1 }} />
              <TextField label="current_value" value={show(v.value)} disabled sx={{ flex: 1 }} />
              <TextField label="LLM_value" value={to} onChange={(e) => setTo(e.target.value)} sx={{ flex: 1 }}
                helperText="Prefilled from the LLM's proposal when there is one" />
            </Stack>
          )}
          <Box>
            <Typography variant="body2">Weightage {w.toFixed(2)} (-1 never, 0 no preference, +1 always)</Typography>
            <Slider value={w} min={-1} max={1} step={0.05} onChange={(_, x) => setW(x as number)} />
          </Box>
          {never && <Alert severity="warning">Never (-1): on Confirm, unit {u.unit_id} ({u.key}) is REMOVED from this run; its data is kept with this pair.</Alert>}
          <Typography variant="caption">Added at the bottom of the list (lowest priority) - move it up in LLM feedback. Used only by NEW runs.</Typography>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" disabled={!ok} onClick={confirm}>{never ? 'Confirm & remove unit' : 'Confirm'}</Button>
      </DialogActions>
    </Dialog>
  )
}
