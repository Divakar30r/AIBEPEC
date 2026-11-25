// Edit one record of a unit in a large modal window (the page behind is frozen until Save / Cancel).
// Every field is editable. A list field gets a dropdown only when all fields it depends on have a value - the
// options come from POST /api/field-options with the CURRENT dialog values (so a value picked a moment ago
// already narrows the next dropdown). Nothing is stored until Save; Save hands the edits to the unit's
// pending changes (applied with "Apply changes & re-run").
import { useEffect, useMemo, useRef, useState } from 'react'
import RefreshIcon from '@mui/icons-material/Refresh'
import {
  Alert, Autocomplete, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, LinearProgress,
  TextField, Typography,
} from '@mui/material'
import { api, type Config, type FieldSpec, type Row, type Unit } from './api'
import { show, toIso } from './EditableGrid'

interface Props {
  u: Unit
  cfg: Config
  table: string
  rec: number | null
  fixes: Record<string, unknown> // the unit's pending changes, keyed table|record|field
  flagged: Set<string> // violation cells, same keys
  onSave: (edits: Record<string, unknown>) => void // field -> value for THIS record (all its fields)
  onClose: () => void
}

const ck = (t: string, r: number | null, f: string) => `${t}|${r ?? 'p'}|${f}`

export default function RecordDialog({ u, cfg, table, rec, fixes, flagged, onSave, onClose }: Props) {
  const isParent = rec === null
  const original: Row = useMemo(() => {
    const d = u.draft[table]
    return (Array.isArray(d) ? d[rec as number] : d) ?? {}
  }, [u, table, rec])
  const keyField = isParent ? cfg.key_field : cfg.children[table]?.key_field
  const fields = useMemo(() => Object.keys(original).filter((f) => f !== keyField), [original, keyField])
  // start from the record as shown in the unit: stored values + pending (unsaved-to-run) changes
  const [vals, setVals] = useState<Row>(() =>
    Object.fromEntries(fields.map((f) => [f, ck(table, rec, f) in fixes ? fixes[ck(table, rec, f)] : original[f]])))
  const [specs, setSpecs] = useState<Record<string, FieldSpec>>({})
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [tick, setTick] = useState(0) // 'Refresh lists': fetch the dropdowns again for the current selection
  const [refreshedAt, setRefreshedAt] = useState('')
  const seq = useRef(0)

  // Dependency context: this record (dialog values) + its parent record (stored + pending changes)
  useEffect(() => {
    const parent = u.draft[cfg.parent] as Row
    const values: Row = {}
    Object.keys(parent).forEach((f) => {
      const k = ck(cfg.parent, null, f)
      values[`${cfg.parent}.${f}`] = k in fixes ? fixes[k] : parent[f]
    })
    fields.forEach((f) => { values[`${table}.${f}`] = vals[f] })
    const my = ++seq.current
    setLoading(true)
    const t = setTimeout(() => {
      api<Record<string, FieldSpec>>('/field-options', 'POST', { table, fields, values })
        .then((s) => {
          if (my === seq.current) { setSpecs(s); setErr(''); setRefreshedAt(new Date().toLocaleTimeString()) }
        })
        .catch((e) => setErr(String(e)))
        .finally(() => { if (my === seq.current) setLoading(false) })
    }, tick ? 0 : 200)
    return () => clearTimeout(t)
  }, [vals, u, cfg, table, fields, fixes, tick])

  const set = (f: string, v: unknown) => setVals((x) => ({ ...x, [f]: v }))
  const changed = fields.filter((f) => show(vals[f]) !== show(original[f]))

  return (
    <Dialog open onClose={onClose} maxWidth="lg" fullWidth scroll="paper">
      <DialogTitle>
        Edit {table} {isParent ? 'record' : `record #${rec}`} · unit {u.unit_id} ({u.key})
        {keyField && <Typography variant="body2" color="text.secondary">{keyField}: {show(original[keyField])}</Typography>}
      </DialogTitle>
      {loading && <LinearProgress />}
      <DialogContent dividers>
        {err && <Alert severity="error" sx={{ mb: 2 }}>{err}</Alert>}
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          A list field shows a dropdown once every field it depends on has a value - fill those first. Nothing is
          stored until <b>Save</b>; the changes then wait in the unit until "Apply changes &amp; re-run".
        </Typography>
        <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 2 }}>
          {fields.map((f) => (
            <FieldInput key={f} field={f} value={vals[f]} spec={specs[f]} original={original[f]}
              flagged={flagged.has(ck(table, rec, f))} onChange={(v) => set(f, v)} />
          ))}
        </Box>
      </DialogContent>
      <DialogActions>
        <Button startIcon={<RefreshIcon />} onClick={() => setTick((t) => t + 1)} disabled={loading}
          title="Rebuild every dropdown of this record from the values selected now">Refresh lists</Button>
        {refreshedAt && <Typography variant="caption" color="text.secondary">lists as of {refreshedAt}</Typography>}
        {changed.length > 0 && <Chip size="small" color="warning" label={`${changed.length} change(s): ${changed.join(', ')}`} />}
        <Box flexGrow={1} />
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={() => onSave(vals)}>Save</Button>
      </DialogActions>
    </Dialog>
  )
}

function FieldInput({ field, value, spec, original, flagged, onChange }: {
  field: string; value: unknown; spec?: FieldSpec; original: unknown; flagged: boolean; onChange: (v: unknown) => void
}) {
  const [text, setText] = useState(show(value))
  useEffect(() => setText(show(value)), [value])
  const isChanged = show(value) !== show(original)
  const deps = spec?.depends_on?.length ? `Depends on ${spec.depends_on.join(', ')}. ` : ''
  const offList = spec?.editor === 'select' && show(value) !== '' &&
    !(spec.options ?? []).some((o) => o.toLowerCase() === show(value).toLowerCase())
  const helper = `${offList ? 'Not in the list for the current selection. ' : ''}${isChanged ? `was ${show(original) || '(empty)'} · ` : ''}${deps}${spec?.help ?? ''}`
  const common = {
    label: field, size: 'small' as const, fullWidth: true, error: offList || (flagged && !isChanged), helperText: helper,
    sx: isChanged ? { '& .MuiOutlinedInput-root': { bgcolor: '#fff4cc' } } : undefined,
  }
  if (spec?.editor === 'select') {
    return (
      <Autocomplete freeSolo autoSelect options={spec.options ?? []} value={show(value) || null}
        onChange={(_, v) => onChange(v ?? '')}
        renderInput={(p) => <TextField {...p} {...common} placeholder="pick or type" />} />
    )
  }
  if (spec?.editor === 'date') {
    return (
      <TextField {...common} type="date" value={toIso(show(value))} InputLabelProps={{ shrink: true }}
        inputProps={{ min: spec.min ?? undefined, max: spec.max ?? undefined }}
        onChange={(e) => onChange(e.target.value || null)} />
    )
  }
  const numeric = spec?.editor === 'int' || spec?.editor === 'number'
  return (
    <TextField {...common} type={numeric ? 'number' : 'text'} value={text}
      inputProps={numeric ? { min: spec?.min ?? undefined, max: spec?.max ?? undefined, step: spec?.editor === 'int' ? 1 : 'any' } : undefined}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => { if (text !== show(value)) onChange(text === '' ? null : numeric ? Number(text) : text) }} />
  )
}
