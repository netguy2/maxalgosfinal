import { Radio, Send, ShieldCheck, Target, Timer, TrendingDown } from 'lucide-react'
import type { ReactNode } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import type { StrategySymbolMapping } from '@/types/strategy'
import { FlowArrow, metaForVerb, toneForSignal } from './signal-language'

/** One box in the chain. */
function Step({
  label,
  value,
  icon: Icon,
  className,
}: {
  label: string
  value: ReactNode
  icon?: typeof Radio
  className?: string
}) {
  return (
    <div
      className={`flex min-w-0 shrink-0 flex-col gap-0.5 rounded-md border px-2.5 py-1.5 ${className ?? 'bg-muted/30'}`}
    >
      <span className="flex items-center gap-1 text-[10px] uppercase tracking-wide text-muted-foreground">
        {Icon && <Icon className="h-2.5 w-2.5" />}
        {label}
      </span>
      <span className="truncate text-xs font-semibold">{value}</span>
    </div>
  )
}

function instrumentLabel(m: Partial<StrategySymbolMapping>): string {
  if (m.instrument_type === 'OPT') {
    const strike =
      m.strike_selection_mode && m.strike_selection_mode !== 'offset'
        ? m.strike_selection_mode.toUpperCase()
        : m.strike_offset || 'ATM'
    return `${m.underlying || '—'} ${strike} ${m.option_type || ''}`.trim()
  }
  if (m.instrument_type === 'FUT') return `${m.underlying || '—'} FUT`
  return m.instrument || m.underlying || '—'
}

function riskChips(m: Partial<StrategySymbolMapping>) {
  const unit = (t?: string | null) => (t === 'points' ? 'pt' : '%')
  const out: { label: string; value: string; icon: typeof Target }[] = []
  if (m.stop_loss_value)
    out.push({
      label: 'Stop',
      value: `${m.stop_loss_value}${unit(m.stop_loss_type)}`,
      icon: TrendingDown,
    })
  if (m.target_value)
    out.push({ label: 'Target', value: `${m.target_value}${unit(m.target_type)}`, icon: Target })
  if (m.trailing_value)
    out.push({
      label: 'Trail',
      value: `${m.trailing_value}${unit(m.trailing_type)}`,
      icon: ShieldCheck,
    })
  return out
}

/** One left-to-right chain: signal -> instrument -> order -> risk -> broker. */
export function FlowChain({ mapping }: { mapping: Partial<StrategySymbolMapping> }) {
  const signal = (mapping.action || mapping.symbol || 'BUY').toUpperCase()
  const verb = metaForVerb(mapping.signal_action)
  const signalTone = toneForSignal(signal)
  const risks = riskChips(mapping)
  const VerbIcon = verb.icon

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Step label="Signal" value={signal} icon={Radio} className={signalTone.panel} />
      <FlowArrow />
      <Step label="Action" value={verb.label} icon={VerbIcon} className={verb.tone.panel} />
      <FlowArrow />
      <Step label="Instrument" value={instrumentLabel(mapping)} />
      <FlowArrow />
      <Step
        label="Order"
        value={`${mapping.order_type || 'MARKET'} · ${
          mapping.lots ? `${mapping.lots} lot` : (mapping.quantity ?? 1)
        }`}
      />
      {risks.length > 0 && (
        <>
          <FlowArrow />
          {risks.map((r) => (
            <Step key={r.label} label={r.label} value={r.value} icon={r.icon} />
          ))}
        </>
      )}
      <FlowArrow />
      <Step label="Broker" value="Send" icon={Send} className="bg-brand/5 border-brand/20" />
    </div>
  )
}

interface Props {
  /** Saved rules. */
  mappings: StrategySymbolMapping[]
  /** The rule currently being built in the form, drawn as a live preview. */
  draft?: Partial<StrategySymbolMapping> | null
  isStateful: boolean
}

/**
 * The automation, drawn.
 *
 * This card used to say "No active signal actions yet" and otherwise sit
 * empty -- a large piece of prime real estate carrying no information. It
 * now renders the actual execution chain for every rule, and previews the
 * rule being built as the user fills the form, so the answer to "what will
 * this actually do?" is visible before anything is saved.
 */
export function ExecutionFlow({ mappings, draft, isStateful }: Props) {
  if (isStateful) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Radio className="h-4 w-4" />
            Execution Flow
          </CardTitle>
          <CardDescription>
            This strategy rotates between legs — it tracks which leg is open so one signal can close
            it and enter the other. Configure the legs below.
          </CardDescription>
        </CardHeader>
      </Card>
    )
  }

  const active = mappings.filter((m) => m.is_active !== false)
  const hasDraft = Boolean(
    draft && (draft.underlying || draft.instrument || draft.instrument_type === 'EQ')
  )

  // Group by the signal that triggers them, so the reader sees "when BUY
  // arrives, these things happen" rather than a flat list of rules.
  const signals = ['BUY', 'SELL', 'SHORT', 'EXIT']
  const grouped = signals
    .map((sig) => ({
      signal: sig,
      rows: active.filter((m) => (m.action || m.symbol || '').toUpperCase() === sig),
    }))
    .filter((g) => g.rows.length > 0)

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Radio className="h-4 w-4" />
          Execution Flow
        </CardTitle>
        <CardDescription>
          Exactly what happens when a signal arrives from your webhook.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {grouped.length === 0 && !hasDraft && (
          <div className="rounded-lg border border-dashed p-6 text-center">
            <p className="text-sm font-medium">No rules yet</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Pick a Quick Start below, or build one manually — your automation will appear here as
              you go.
            </p>
          </div>
        )}

        {grouped.map(({ signal, rows }) => (
          <div key={signal} className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                When {signal} arrives
              </span>
              <div className="h-px flex-1 bg-border" />
            </div>
            {rows.map((m) => (
              <div key={m.id} className="overflow-x-auto pb-1">
                <FlowChain mapping={m} />
              </div>
            ))}
          </div>
        ))}

        {hasDraft && draft && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wide text-brand">
                <Timer className="h-3 w-3" />
                Preview — not saved yet
              </span>
              <div className="h-px flex-1 bg-brand/30" />
            </div>
            <div className="overflow-x-auto rounded-lg border border-dashed border-brand/40 bg-brand/[0.03] p-2 pb-2">
              <FlowChain mapping={draft} />
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
