// One table component for every screen (Material React Table):
//  * editors IN the cells (dropdown / number / date / text) - spec(row) decides per row, null = read-only
//  * per-row locking: editable(row) - e.g. an Options value freezes that row's cells at once
//  * drag rows to reorder (onMove) - off while grouped
//  * group by any SET of columns (the 'Group by' picker in the toolbar, or a column's menu), value filters per column
import { ReactNode, useEffect, useMemo, useState } from 'react'
import { MaterialReactTable, useMaterialReactTable, type MRT_ColumnDef } from 'material-react-table'
import { Autocomplete, MenuItem, Stack, TextField, Tooltip, Typography } from '@mui/material'
import type { Row, Spec } from './api'

export type Tone = 'bad' | 'changed' | 'llm' | 'muted' | 'archived' | undefined

export interface GridCol {
  key: string
  header: string
  size?: number
  spec?: (row: Row) => Spec | null // the cell's editor; null/undefined = read-only
  editable?: (row: Row) => boolean // lock rule on top of spec (e.g. from the row's Options)
  filter?: 'multi' | 'range' | 'text' | 'none'
  group?: boolean // may be grouped by (default true)
  render?: (row: Row) => ReactNode
  tone?: (row: Row) => Tone
}

interface Props {
  rows: Row[]
  getId: (row: Row) => string
  columns: GridCol[]
  onEdit?: (id: string, key: string, value: unknown) => void
  onMove?: (dragId: string, overId: string) => void
  grouping?: string[] // initial grouping
  toolbar?: ReactNode
  showFilters?: boolean
  maxHeight?: number
  rowTone?: (row: Row) => Tone
  groupBy?: boolean // show the 'Group by' picker (default true)
  rowAction?: (row: Row) => ReactNode // e.g. an Edit button at the start of each row
  compact?: boolean // dense: no toolbar / column menus / filters, narrow wrapping columns (unit window)
}

const TONES: Record<string, object> = {
  bad: { bgcolor: '#fde2e2', color: '#7a0000', fontWeight: 600 },
  changed: { bgcolor: '#fff4cc' },
  llm: { bgcolor: '#e3f0ff' },
  muted: { color: 'text.disabled', textDecoration: 'line-through' },
  archived: { color: 'text.secondary', fontStyle: 'italic', bgcolor: '#f3f3f3' },
}

export function show(v: unknown): string {
  if (v === null || v === undefined) return ''
  return typeof v === 'object' ? JSON.stringify(v) : String(v)
}

export function EditableGrid({ rows, getId, columns, onEdit, onMove, grouping: initial = [], toolbar,
  showFilters = false, maxHeight, rowTone, groupBy = true, rowAction, compact = false }: Props) {
  const [grouping, setGrouping] = useState<string[]>(initial)
  // Multi-select filter options as TEXT, built here: the library sorts its own options with localeCompare,
  // which throws on numbers (ages, amounts, unit ids) and crashed the page.
  const options = useMemo(() => {
    const out: Record<string, string[]> = {}
    columns.filter((c) => c.filter === 'multi').forEach((c) => {
      out[c.key] = [...new Set(rows.map((r) => show(r[c.key])).filter((s) => s !== ''))]
        .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }))
    })
    return out
  }, [rows, columns])
  const cols = useMemo<MRT_ColumnDef<Row>[]>(
    () =>
      columns.map((c) => ({
        id: c.key,
        accessorFn: (r: Row) => r[c.key] ?? null,
        header: c.header,
        size: c.size,
        enableGrouping: c.group !== false,
        enableColumnFilter: c.filter !== 'none',
        filterVariant: c.filter === 'multi' ? 'multi-select' : c.filter === 'range' ? 'range' : 'text',
        ...(c.filter === 'multi' ? {
          filterSelectOptions: options[c.key],
          filterFn: (row: { getValue: (id: string) => unknown }, id: string, picked: string[]) =>
            !picked?.length || picked.includes(show(row.getValue(id))),
        } : {}),
        enableEditing: (row) =>
          !!onEdit && !row.getIsGrouped() && !!c.spec?.(row.original) && (c.editable ? c.editable(row.original) : true),
        Cell: ({ row, cell }) => (c.render ? c.render(row.original) : show(cell.getValue())),
        Edit: ({ row, cell }) => (
          <CellEditor spec={c.spec!(row.original)!} value={cell.getValue()}
            onCommit={(v) => onEdit!(getId(row.original), c.key, v)} />
        ),
        muiTableBodyCellProps: ({ row }) => {
          const t = row.getIsGrouped() ? undefined : (c.tone?.(row.original) ?? rowTone?.(row.original))
          return { sx: t ? TONES[t] : {} }
        },
      })),
    [columns, onEdit, getId, rowTone, options],
  )
  const groupable = columns.filter((c) => c.group !== false)
  const table = useMaterialReactTable({
    columns: cols,
    data: rows,
    getRowId: (r) => getId(r),
    enableEditing: !!onEdit,
    editDisplayMode: 'table',
    enableGrouping: true,
    groupedColumnMode: false,
    positionToolbarDropZone: 'top',
    state: { grouping },
    onGroupingChange: setGrouping,
    initialState: { density: 'compact', expanded: true, showColumnFilters: showFilters },
    enableRowOrdering: !!onMove && grouping.length === 0,
    enableRowActions: !!rowAction,
    positionActionsColumn: 'first',
    displayColumnDefOptions: { 'mrt-row-actions': { header: '', size: 56 } },
    renderRowActions: ({ row }) => (row.getIsGrouped() || !rowAction ? null : rowAction(row.original)),
    enableSorting: !onMove,
    enablePagination: false,
    enableBottomToolbar: false,
    columnFilterDisplayMode: 'subheader',
    enableDensityToggle: false,
    enableTopToolbar: !compact,
    enableColumnActions: !compact,
    enableColumnFilters: !compact,
    ...(compact ? { defaultColumn: { minSize: 40, size: 110, maxSize: 600 } } : {}),
    muiTableHeadCellProps: compact ? { sx: { '& .Mui-TableHeadCell-Content-Wrapper': { whiteSpace: 'normal' } } } : undefined,
    enableFullScreenToggle: false,
    enableStickyHeader: true,
    muiTableContainerProps: { sx: maxHeight ? { maxHeight } : {} },
    muiRowDragHandleProps: ({ table }) => ({
      onDragEnd: () => {
        const { draggingRow, hoveredRow } = table.getState()
        if (onMove && draggingRow && hoveredRow?.id && hoveredRow.id !== draggingRow.id) onMove(draggingRow.id, hoveredRow.id)
      },
    }),
    renderTopToolbarCustomActions: () => (
      <Stack direction="row" spacing={1.5} alignItems="center" sx={{ flexWrap: 'wrap' }}>
        {groupBy && (
          <Autocomplete multiple size="small" sx={{ minWidth: 260 }} options={groupable.map((c) => c.key)}
            getOptionLabel={(k) => columns.find((c) => c.key === k)?.header ?? k} value={grouping}
            onChange={(_, v) => setGrouping(v)} filterSelectedOptions
            renderInput={(p) => <TextField {...p} label="Group by" placeholder={grouping.length ? '' : 'columns...'} />} />
        )}
        {groupBy && onMove && grouping.length > 0 && (
          <Typography variant="caption" color="text.secondary">Drag to reorder is off while grouped</Typography>
        )}
        {toolbar}
      </Stack>
    ),
  })
  return <MaterialReactTable table={table} />
}

// ---------------------------------------------------------------------------------------------- cell editors
const DMY = /^(\d{2})[/.-](\d{2})[/.-](\d{4})$/

/** A stored date (any known format) as YYYY-MM-DD for the date input; '' if not a date. */
export function toIso(v: string): string {
  const s = v.trim()
  let m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s)
  if (m) return `${m[1]}-${m[2]}-${m[3]}`
  if ((m = /^(\d{4})(\d{2})(\d{2})$/.exec(s))) return `${m[1]}-${m[2]}-${m[3]}`
  if ((m = /^(\d{4})(\d{2})$/.exec(s))) return `${m[1]}-${m[2]}-01`
  if ((m = DMY.exec(s))) return `${m[3]}-${m[2]}-${m[1]}`
  return ''
}

export function CellEditor({ spec, value, onCommit }: { spec: Spec; value: unknown; onCommit: (v: unknown) => void }) {
  const initial = show(value)
  const [v, setV] = useState(initial)
  useEffect(() => setV(initial), [initial])
  const common = { size: 'small' as const, variant: 'standard' as const, fullWidth: true }
  let el: JSX.Element
  switch (spec.editor) {
    case 'choice': // closed list, commits at once (e.g. Options -> locks the row immediately)
      el = (
        <TextField select {...common} value={v} SelectProps={{ displayEmpty: true }}
          onChange={(e) => { setV(e.target.value); onCommit(e.target.value || null) }}>
          <MenuItem value=""><em>-</em></MenuItem>
          {(spec.options ?? []).map((o) => <MenuItem key={o} value={o}>{o}</MenuItem>)}
        </TextField>
      )
      break
    case 'select': // rule options for this row; typing a custom value overrides (re-validated on re-run)
      el = (
        <Autocomplete freeSolo autoSelect size="small" options={spec.options ?? []} value={v || null}
          onChange={(_, nv) => { const s = nv ?? ''; setV(s); if (s !== initial) onCommit(s) }}
          renderInput={(p) => <TextField {...p} variant="standard" placeholder="pick or type" />} />
      )
      break
    case 'int':
    case 'number':
      el = (
        <TextField type="number" {...common} value={v}
          inputProps={{ min: spec.min ?? undefined, max: spec.max ?? undefined, step: spec.step ?? (spec.editor === 'int' ? 1 : 0.05) }}
          onChange={(e) => setV(e.target.value)}
          onBlur={() => { if (v !== initial) onCommit(v === '' ? null : Number(v)) }} />
      )
      break
    case 'date':
      el = (
        <TextField type="date" {...common} value={toIso(v)}
          inputProps={{ min: spec.min ?? undefined, max: spec.max ?? undefined }}
          onChange={(e) => { setV(e.target.value); onCommit(e.target.value || null) }} />
      )
      break
    default:
      el = (
        <TextField {...common} value={v} onChange={(e) => setV(e.target.value)}
          onBlur={() => { if (v !== initial) onCommit(v) }} />
      )
  }
  return spec.help ? <Tooltip title={spec.help} placement="top"><span style={{ display: 'block' }}>{el}</span></Tooltip> : el
}
