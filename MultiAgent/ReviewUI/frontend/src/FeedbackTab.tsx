// LLM feedback (LLMEffects/LLMfeedback.json): weigh the pairs for the next run.
// Options locks a row's cells at once; drag rows for priority; group by / filter any column; Save writes the file.
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Box, Button, Chip, FormControlLabel, Stack, Switch, Tab, Tabs, Typography } from '@mui/material'
import { api, type Config, type Row, type Spec } from './api'
import { EditableGrid, type GridCol } from './EditableGrid'

const CATS: [string, (w: number) => boolean][] = [
  ['Always (1)', (w) => w >= 1],
  ['Never (-1)', (w) => w <= -1],
  ['No pref (0)', (w) => w === 0],
  ['Positive (0..1)', (w) => w > 0 && w < 1],
  ['Negative (-1..0)', (w) => w < 0 && w > -1],
]
const REMOVE = 'Remove'
const ARCHIVE = 'Archive' // value pairs: hidden unless 'Show archived' - still applied at its priority
const WEIGHT: Spec = { editor: 'number', min: -1, max: 1, step: 0.05, help: '-1 never, 0 no preference, +1 always' }
const TEXT: Spec = { editor: 'text' }
const COUNT: Spec = { editor: 'int', min: 0, help: 'Number of related records with that value' }

type Section = 'Value-based' | 'Count-based'
type Lists = Record<Section, Row[]>

function move(rows: Row[], dragId: string, overId: string): Row[] {
  const out = [...rows]
  const from = out.findIndex((r) => r._id === dragId)
  const to = out.findIndex((r) => r._id === overId)
  if (from < 0 || to < 0) return rows
  out.splice(to, 0, out.splice(from, 1)[0])
  return out
}

export default function FeedbackTab({ cfg, notify }: { cfg: Config; notify: (msg: string, error?: boolean) => void }) {
  const { only: ONLY, max: MAX } = cfg.options
  const [lists, setLists] = useState<Lists>({ 'Value-based': [], 'Count-based': [] })
  const [dirty, setDirty] = useState(false)
  const [tab, setTab] = useState<Section>('Value-based')
  const [cats, setCats] = useState<number[]>([])
  const [showArchived, setShowArchived] = useState(false)

  const load = useCallback(() => {
    api<Lists>('/feedback')
      .then((d) => {
        setLists({
          'Value-based': d['Value-based'].map((r, i) => ({ ...r, _id: `v${i}`, Option: r.Option ?? null })),
          'Count-based': d['Count-based'].map((r, i) => ({ ...r, _id: `c${i}`, Option: r.Option ?? null })),
        })
        setDirty(false)
      })
      .catch((e) => notify(String(e), true))
  }, [notify])
  useEffect(load, [load])

  const edit = useCallback(
    (section: Section) => (id: string, key: string, value: unknown) => {
      setLists((l) => ({ ...l, [section]: l[section].map((r) => (r._id === id ? { ...r, [key]: value } : r)) }))
      setDirty(true)
    },
    [],
  )
  const reorder = useCallback(
    (section: Section) => (dragId: string, overId: string) => {
      setLists((l) => ({ ...l, [section]: move(l[section], dragId, overId) }))
      setDirty(true)
    },
    [],
  )
  const save = () =>
    api<Record<Section, number>>('/feedback', 'PUT', {
      'Value-based': lists['Value-based'].filter((r) => r.Option !== REMOVE),
      'Count-based': lists['Count-based'].filter((r) => r.Option !== REMOVE),
    })
      .then(() => { notify('LLM feedback saved - the next run uses it'); load() })
      .catch((e) => notify(String(e), true))

  // Priority = position in the full list; the weightage chips filter what is shown (drag moves among visible rows).
  // Archived value pairs keep their place (Priority counts them) but are hidden unless 'Show archived'.
  const visible = (rows: Row[]) =>
    rows
      .map((r, i): Row => ({ ...r, _prio: i + 1, _tfc: r.Table ? `${r.Table} / ${r.Field} / ${r.current_value}` : undefined }))
      .filter((r) => showArchived || r.Option !== ARCHIVE)
      .filter((r) => !cats.length || cats.some((c) => CATS[c][1](Number(r.Weightage ?? 0))))
  const nArchived = lists['Value-based'].filter((r) => r.Option === ARCHIVE).length

  const muted = (r: Row) => (r.Option === REMOVE ? 'muted' : r.Option === ARCHIVE ? 'archived' : undefined)
  const seen = (r: Row) => `${r.LastRun ?? '-'} (${r.Seen ?? 0})`
  const valueCols = useMemo<GridCol[]>(() => {
    const open = (r: Row) => r.Option !== REMOVE
    return [
      { key: '_prio', header: 'Priority', size: 70, filter: 'none', group: false },
      { key: 'Option', header: 'Options', size: 150, spec: () => ({ editor: 'choice', options: [REMOVE, ARCHIVE] }) },
      { key: '_tfc', header: 'Table / Field / current value', size: 320, filter: 'multi' },
      { key: 'LLM_value', header: 'LLM_value', filter: 'multi', spec: () => TEXT, editable: open },
      { key: 'Weightage', header: 'Weightage', size: 110, filter: 'range', spec: () => WEIGHT, editable: open },
      { key: 'Source', header: 'Source', filter: 'multi' },
      { key: '_seen', header: 'Last run (seen)', filter: 'none', group: false, render: seen },
    ]
  }, [])
  const countCols = useMemo<GridCol[]>(() => {
    // Remove: all locked but Options; Only Possibility: all locked; Max Possibility: only Weightage
    const plain = (r: Row) => !r.Option
    const weight = (r: Row) => !r.Option || r.Option === MAX
    return [
      { key: '_prio', header: 'Priority', size: 70, filter: 'none', group: false },
      { key: 'Option', header: 'Options', size: 170, spec: () => ({ editor: 'choice', options: [REMOVE, ONLY, MAX] }) },
      { key: 'Field', header: 'Field', filter: 'multi' },
      { key: 'value', header: 'value', filter: 'multi', spec: () => TEXT, editable: plain },
      { key: 'RelatedField', header: 'RelatedField', filter: 'multi' },
      { key: 'RelatedFieldValue', header: 'RelatedFieldValue', filter: 'multi', spec: () => TEXT, editable: plain },
      { key: 'Count', header: 'Count', size: 90, filter: 'range', spec: () => COUNT, editable: plain },
      { key: 'Weightage', header: 'Weightage', size: 110, filter: 'range', spec: () => WEIGHT, editable: weight },
      { key: 'Note', header: 'Note', filter: 'multi' },
      { key: '_seen', header: 'Last run (seen)', filter: 'none', group: false, render: seen },
    ]
  }, [ONLY, MAX])

  const editValue = useMemo(() => edit('Value-based'), [edit])
  const editCount = useMemo(() => edit('Count-based'), [edit])
  const moveValue = useMemo(() => reorder('Value-based'), [reorder])
  const moveCount = useMemo(() => reorder('Count-based'), [reorder])
  const getId = useCallback((r: Row) => r._id as string, [])

  return (
    <Box>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
        Weightage: <b>-1</b> never · <b>0</b> no preference · <b>+1</b> always (fractions = approximate share). Used only
        by NEW runs. Drag rows to set priority (earlier = considered first; off while grouped). <b>Archive</b> (value
        pairs): hidden from the list, still applied at its priority. <b>{ONLY}</b>: exactly
        Count, share predicted from the value pairs into the parent value. <b>{MAX}</b>: at most Count, share =
        predicted share x Weightage.
      </Typography>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1, flexWrap: 'wrap' }}>
        <Typography variant="body2">Show weightage:</Typography>
        {CATS.map(([label], i) => (
          <Chip key={label} label={label} size="small" color={cats.includes(i) ? 'primary' : 'default'}
            onClick={() => setCats((c) => (c.includes(i) ? c.filter((x) => x !== i) : [...c, i]))} />
        ))}
        <Box flexGrow={1} />
        {dirty && <Chip label="Unsaved changes" color="warning" size="small" />}
        <Button variant="outlined" disabled={!dirty} onClick={load}>Discard</Button>
        <Button variant="contained" disabled={!dirty} onClick={save}>Save</Button>
      </Stack>
      <Tabs value={tab} onChange={(_, t) => setTab(t)} sx={{ mb: 1 }}>
        <Tab value="Value-based" label={`Value-based (${lists['Value-based'].length})`} />
        <Tab value="Count-based" label={`Count-based (${lists['Count-based'].length})`} />
      </Tabs>
      {tab === 'Value-based' && (
        <EditableGrid rows={visible(lists['Value-based'])} getId={getId} columns={valueCols} onEdit={editValue}
          onMove={moveValue} rowTone={muted} maxHeight={640}
          toolbar={<FormControlLabel label={`Show archived (${nArchived})`}
            control={<Switch size="small" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />} />} />
      )}
      {tab === 'Count-based' && (
        <EditableGrid rows={visible(lists['Count-based'])} getId={getId} columns={countCols} onEdit={editCount}
          onMove={moveCount} rowTone={muted} maxHeight={640} />
      )}
      {!lists['Value-based'].length && !lists['Count-based'].length && (
        <Alert severity="info" sx={{ mt: 1 }}>No feedback yet - it is collected once a run is finished.</Alert>
      )}
    </Box>
  )
}
