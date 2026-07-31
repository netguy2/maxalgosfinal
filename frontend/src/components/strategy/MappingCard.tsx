import { Copy, Layers, Pause, Pencil, Play, Trash2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { StrategySymbolMapping } from '@/types/strategy'
import { FlowChain } from './ExecutionFlow'
import { metaForVerb, ToneBadge, toneForSignal } from './signal-language'

interface Props {
  mapping: StrategySymbolMapping
  onEdit: (m: StrategySymbolMapping) => void
  onClone: (m: StrategySymbolMapping) => void
  onToggle: (m: StrategySymbolMapping) => void
  onDelete: (id: number) => void
  toggling?: boolean
}

function title(m: StrategySymbolMapping): string {
  if (m.label) return m.label
  if (m.instrument_type === 'OPT') {
    const strike =
      m.strike_selection_mode && m.strike_selection_mode !== 'offset'
        ? m.strike_selection_mode.toUpperCase()
        : m.strike_offset || 'ATM'
    return `${m.underlying} ${strike} ${m.option_type || ''}`.trim()
  }
  if (m.instrument_type === 'FUT') return `${m.underlying} Futures`
  return m.instrument || m.symbol
}

/**
 * One rule, as a card.
 *
 * Replaces a dense 9-column table where every cell had identical visual
 * weight and the actual behaviour ("a BUY signal buys an ATM call with a 2%
 * stop") had to be reconstructed by reading across the row. A card leads
 * with the signal and the verb in colour, states the instrument as a title,
 * and embeds the same execution chain drawn at the top of the page -- so
 * the rule reads the same way everywhere it appears.
 */
export function MappingCard({ mapping, onEdit, onClone, onToggle, onDelete, toggling }: Props) {
  const paused = mapping.is_active === false
  const signal = (mapping.action || mapping.symbol || 'BUY').toUpperCase()
  const signalTone = toneForSignal(signal)
  const verb = metaForVerb(mapping.signal_action)
  const VerbIcon = verb.icon

  return (
    <div
      className={`group rounded-lg border transition-colors hover:border-foreground/20 ${
        paused ? 'opacity-60' : ''
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3 p-3">
        <div className="min-w-0 space-y-1.5">
          <div className="flex flex-wrap items-center gap-1.5">
            <ToneBadge tone={signalTone}>{signal}</ToneBadge>
            <ToneBadge tone={verb.tone} icon={VerbIcon}>
              {verb.label}
            </ToneBadge>
            {mapping.leg_basket && (
              <Badge variant="outline" className="gap-1 text-[10px]">
                <Layers className="h-2.5 w-2.5" />
                {mapping.leg_basket}
              </Badge>
            )}
            {paused && (
              <Badge variant="secondary" className="text-[10px]">
                Paused
              </Badge>
            )}
          </div>
          <p className="truncate text-sm font-semibold">{title(mapping)}</p>
          <p className="text-xs text-muted-foreground">
            {mapping.exchange} · {mapping.product_type} ·{' '}
            {mapping.lots ? `${mapping.lots} lot${mapping.lots > 1 ? 's' : ''}` : mapping.quantity}
          </p>
        </div>

        {/* Actions stay visible on touch devices, where hover doesn't exist. */}
        <div className="flex shrink-0 items-center gap-0.5">
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={() => onToggle(mapping)}
            disabled={toggling}
            title={paused ? 'Resume' : 'Pause'}
            aria-label={paused ? `Resume ${title(mapping)}` : `Pause ${title(mapping)}`}
          >
            {paused ? <Play className="h-3.5 w-3.5" /> : <Pause className="h-3.5 w-3.5" />}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={() => onClone(mapping)}
            title="Duplicate"
            aria-label={`Duplicate ${title(mapping)}`}
          >
            <Copy className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={() => onEdit(mapping)}
            title="Edit"
            aria-label={`Edit ${title(mapping)}`}
          >
            <Pencil className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 text-loss hover:bg-loss/10 hover:text-loss"
            onClick={() => onDelete(mapping.id)}
            title="Delete"
            aria-label={`Delete ${title(mapping)}`}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      <div className="overflow-x-auto border-t bg-muted/20 px-3 py-2">
        <FlowChain mapping={mapping} />
      </div>
    </div>
  )
}
