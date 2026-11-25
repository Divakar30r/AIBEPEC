// Thin client for ReviewUI/backend (FastAPI). Everything goes through /api (proxied by Vite in dev).
export type Row = Record<string, any>

export interface Spec {
  editor: 'select' | 'choice' | 'int' | 'number' | 'date' | 'text'
  options?: string[]
  min?: number | string | null
  max?: number | string | null
  step?: number
  format?: string // date token the value is stored in, e.g. YYYYMMDD
  help?: string | null
  rule?: string | null
  scoped?: boolean
}

/** Editor of one field in the Edit dialog (POST /api/field-options). */
export type FieldSpec = Spec & { depends_on: string[]; missing: string[] }

export interface Config {
  parent: string
  key_field: string
  db_name: string
  units: number
  llm_review: boolean
  children: Record<string, { key_field: string; fk: string; min: number; max: number }>
  levels: string[][]
  options: { only: string; max: string }
  list_fields: string[] // 'Table.Field' with a list rule - the only fields LLM feedback takes
}

export interface RunSummary {
  run_id: string
  units: number
  completed: number
  needs_review: number
  error: number
  done: boolean
  status: string | null
}

export interface EditCell {
  table: string
  record: number | null
  field: string
  current: unknown
  violation: boolean
  prefill: unknown
  spec: Spec
}

export interface Violation {
  kind?: 'field' | 'count'
  table: string
  record?: number | null
  field: string
  value: unknown
  reason: string
  count?: number
  allowed_count?: [number, number]
  records?: number[]
}

export interface Unit {
  unit_id: number
  key: string
  status: 'completed' | 'needs_review' | 'error'
  halted_before_level: number | null
  levels_done: number
  attempts?: number
  violations: Violation[]
  notes: string[]
  draft: Record<string, Row | Row[]>
  llm_applied?: Row[]
  user_applied?: Row[]
  llm_review: Row | null
  edit: { cells: EditCell[]; delete: Record<string, number[]> } | null
}

export interface Run {
  run_id: string
  units: Unit[]
  warnings: string[]
  levels: string[][]
  supervisor?: { round?: number; status?: string; trace?: Row[] }
  audit?: { round: number; at: string; summary: Record<string, { checks: number; violations: number }>; findings: Row[] }
}

export async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) {
    let msg = await res.text()
    try {
      msg = JSON.parse(msg).detail ?? msg
    } catch {
      /* plain text */
    }
    throw new Error(`${res.status}: ${msg}`)
  }
  return res.json() as Promise<T>
}
