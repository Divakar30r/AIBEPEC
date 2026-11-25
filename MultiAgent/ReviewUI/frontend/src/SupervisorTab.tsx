// Supervisor (multi-agent): the agent trace and the end-of-round audit - read-only.
import { useMemo, useState } from 'react'
import { Alert, Box, Chip, FormControlLabel, Stack, Switch, Typography } from '@mui/material'
import type { Row, Run } from './api'
import { EditableGrid, type GridCol } from './EditableGrid'

const TRACE: GridCol[] = [
  { key: 'round', header: 'Round', size: 70, filter: 'multi' },
  { key: 'node', header: 'Agent / node', filter: 'multi' },
  { key: 'summary', header: 'Summary', size: 600, filter: 'text', group: false },
  { key: 'at', header: 'At', filter: 'none', group: false },
]
const FINDINGS: GridCol[] = [
  { key: 'author', header: 'Author', filter: 'multi' },
  { key: 'verdict', header: 'Verdict', filter: 'multi' },
  { key: 'check', header: 'Check', filter: 'multi' },
  { key: 'unit_id', header: 'Unit', size: 70, filter: 'multi' },
  { key: 'key', header: 'Key', filter: 'text' },
  { key: 'table', header: 'Table', filter: 'multi' },
  { key: 'record', header: 'Record', size: 80, filter: 'multi' },
  { key: 'field', header: 'Field', filter: 'multi' },
  { key: 'from', header: 'From', filter: 'text' },
  { key: 'to', header: 'To', filter: 'text' },
  { key: 'detail', header: 'Detail', size: 420, filter: 'text', group: false },
]

export default function SupervisorTab({ run }: { run: Run }) {
  const sv = run.supervisor
  const aud = run.audit
  const [onlyViol, setOnlyViol] = useState(true)
  const trace = useMemo(() => (sv?.trace ?? []).map((r, i) => ({ ...r, _i: i })), [sv])
  const findings = useMemo(
    () => (aud?.findings ?? []).map((r, i) => ({ ...r, _i: i })).filter((r: Row) => !onlyViol || r.verdict === 'violation'),
    [aud, onlyViol],
  )
  if (!sv) return <Alert severity="info">This run was not started through the supervisor (use Execute).</Alert>
  return (
    <Box>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
        Agents: generate (Agent 1, rules) → repair (swaps related sets between halted units, no LLM) → llm (Agent 2) →
        await_human (Agent 3, this UI) → audit (once every unit is completed). Round {sv.round ?? '-'}, status {sv.status ?? '-'}.
      </Typography>
      <Typography variant="h6">Agent trace</Typography>
      <EditableGrid rows={trace} getId={(r) => String(r._i)} columns={TRACE} maxHeight={360} />
      <Typography variant="h6" sx={{ mt: 2 }}>Audit (end of round - report only)</Typography>
      {!aud ? (
        <Alert severity="info">Not audited yet: the audit runs when every unit of the round is completed.</Alert>
      ) : (
        <>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
            {Object.entries(aud.summary).map(([a, s]) => (
              <Chip key={a} color={s.violations ? 'error' : 'success'} label={`${a}: ${s.violations} violation(s) / ${s.checks} check(s)`} />
            ))}
            <Typography variant="caption">Round {aud.round}, audited {aud.at}</Typography>
            <Box flexGrow={1} />
            <FormControlLabel control={<Switch checked={onlyViol} onChange={(e) => setOnlyViol(e.target.checked)} />} label="Violations only" />
          </Stack>
          <EditableGrid rows={findings} getId={(r) => String(r._i)} columns={FINDINGS} grouping={['author']} maxHeight={520}
            rowTone={(r) => (r.verdict === 'violation' ? 'bad' : undefined)} />
        </>
      )}
    </Box>
  )
}
