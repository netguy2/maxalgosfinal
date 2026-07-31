import { Check, CircleDollarSign, LineChart, Pencil, TrendingUp } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { ExpiryType, InstrumentType } from '@/types/strategy'
import { EXPIRY_TYPES } from '@/types/strategy'
import { FIELD_HELP, FieldLabel } from './signal-language'

/** Instrument type drives everything downstream -- which fields exist,
 * which presets are possible, which exchange applies. It has to be the
 * FIRST decision, not one buried below the presets that depend on it. */
const INSTRUMENT_CHOICES: {
  value: InstrumentType
  label: string
  hint: string
  icon: typeof TrendingUp
}[] = [
  {
    value: 'OPT',
    label: 'Options',
    hint: 'Calls & Puts. Strike and expiry resolved live on every signal.',
    icon: LineChart,
  },
  {
    value: 'FUT',
    label: 'Futures',
    hint: 'Futures contracts. Expiry resolved live on every signal.',
    icon: TrendingUp,
  },
  {
    value: 'EQ',
    label: 'Equity / Index',
    hint: 'Trade the share itself on the cash segment.',
    icon: CircleDollarSign,
  },
]

interface Props {
  instrumentType: InstrumentType
  onInstrumentType: (t: InstrumentType) => void
  underlying: string
  underlyingControl: React.ReactNode
  exchange: string
  exchanges: readonly string[]
  onExchange: (e: string) => void
  expiryType: ExpiryType | ''
  onExpiryType: (e: ExpiryType) => void
  /** True once everything a preset needs has been chosen. */
  ready: boolean
  /** True once the user has pressed Confirm on this step. While false, this
   * is the only card shown -- Quick Start / Add Symbols stay hidden so
   * there's one decision on screen at a time instead of every section
   * visible (and interactable) simultaneously. */
  confirmed: boolean
  onConfirm: () => void
  /** Return to editing after confirming, without losing what was chosen. */
  onEdit: () => void
}

function expiryLabelFor(expiryType: ExpiryType | ''): string {
  return EXPIRY_TYPES.find((e) => e.value === expiryType)?.label || expiryType
}

/**
 * Step 1: what are we trading?
 *
 * Previously Instrument Type sat inside the Add Symbols form BELOW the
 * Quick Start presets -- so a new user was shown ten preset cards, clicked
 * one, and got "Switch Instrument Type to Options" pointing at a control
 * they had not scrolled to yet. The dependency ran backwards.
 *
 * Making this the first card fixes the order of decisions: choose the
 * instrument, choose the underlying/expiry, and only then are the presets
 * meaningful (and enabled). Everything below reacts to what is chosen here.
 */
export function SetupStep({
  instrumentType,
  onInstrumentType,
  underlying,
  underlyingControl,
  exchange,
  exchanges,
  onExchange,
  expiryType,
  onExpiryType,
  ready,
  confirmed,
  onConfirm,
  onEdit,
}: Props) {
  const isDerivative = instrumentType !== 'EQ'

  // Once confirmed, collapse to a one-line summary. This is what makes the
  // page read as "step 1 done, now step 2" instead of every section (this
  // card, Quick Start, Add Symbols) sitting open and interactable at once --
  // which is what made the page feel like two overlapping setup panels.
  if (confirmed) {
    const choice = INSTRUMENT_CHOICES.find((c) => c.value === instrumentType)
    const Icon = choice?.icon ?? CircleDollarSign
    return (
      <Card>
        <CardContent className="flex flex-wrap items-center justify-between gap-3 py-4">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <Badge variant="outline" className="gap-1 border-profit/30 bg-profit/10 text-profit">
              <Check className="h-3 w-3" />
              Confirmed
            </Badge>
            <span className="flex items-center gap-1.5 font-medium">
              <Icon className="h-4 w-4 text-brand" />
              {choice?.label}
            </span>
            <span className="text-muted-foreground">·</span>
            <span className="font-medium">{underlying}</span>
            <span className="text-muted-foreground">on {exchange}</span>
            {isDerivative && expiryType && (
              <>
                <span className="text-muted-foreground">·</span>
                <span>{expiryLabelFor(expiryType)}</span>
              </>
            )}
          </div>
          <Button type="button" variant="outline" size="sm" onClick={onEdit}>
            <Pencil className="h-3.5 w-3.5 mr-1.5" />
            Change
          </Button>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center gap-2">
          <CardTitle className="text-base">What are you trading?</CardTitle>
          {ready && (
            <Badge variant="outline" className="gap-1 border-profit/30 bg-profit/10 text-profit">
              <Check className="h-3 w-3" />
              Ready
            </Badge>
          )}
        </div>
        <CardDescription>
          This decides everything below — which fields apply and which quick-start setups are
          available.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Instrument type as cards rather than a dropdown: it is the most
        consequential choice on the page and deserves more weight than a
        one-line select. */}
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          {INSTRUMENT_CHOICES.map((choice) => {
            const Icon = choice.icon
            const selected = instrumentType === choice.value
            return (
              <button
                key={choice.value}
                type="button"
                onClick={() => onInstrumentType(choice.value)}
                aria-pressed={selected}
                className={`flex flex-col gap-1 rounded-lg border p-3 text-left transition-colors ${
                  selected
                    ? 'border-brand bg-brand/5 ring-1 ring-brand/30'
                    : 'hover:border-foreground/20 hover:bg-muted/50'
                }`}
              >
                <span className="flex items-center gap-2 text-sm font-medium">
                  <Icon
                    className={`h-4 w-4 ${selected ? 'text-brand' : 'text-muted-foreground'}`}
                  />
                  {choice.label}
                  {selected && <Check className="ml-auto h-3.5 w-3.5 text-brand" />}
                </span>
                <span className="text-[11px] leading-tight text-muted-foreground">
                  {choice.hint}
                </span>
              </button>
            )
          })}
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div className="space-y-2">
            <FieldLabel help={isDerivative ? FIELD_HELP.underlying : FIELD_HELP.instrumentType}>
              {isDerivative ? 'Underlying' : 'Symbol'}
            </FieldLabel>
            {underlyingControl}
          </div>

          <div className="space-y-2">
            <FieldLabel help={FIELD_HELP.exchange}>Exchange</FieldLabel>
            <Select value={exchange} onValueChange={onExchange}>
              <SelectTrigger aria-label="Exchange">
                <SelectValue placeholder="Select exchange" />
              </SelectTrigger>
              <SelectContent>
                {exchanges.map((e) => (
                  <SelectItem key={e} value={e}>
                    {e}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Expiry only exists for derivatives -- hiding it for Equity is
          the "dynamic form" behaviour: a field that cannot apply should not
          be visible at all. */}
          {isDerivative && (
            <div className="space-y-2">
              <FieldLabel help={FIELD_HELP.expiry}>Expiry</FieldLabel>
              <Select value={expiryType} onValueChange={(v) => onExpiryType(v as ExpiryType)}>
                <SelectTrigger aria-label="Expiry">
                  <SelectValue placeholder="Select expiry" />
                </SelectTrigger>
                <SelectContent>
                  {EXPIRY_TYPES.map((e) => (
                    <SelectItem key={e.value} value={e.value}>
                      {e.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
        </div>

        {!underlying && (
          <p className="text-xs text-muted-foreground">
            Pick {isDerivative ? 'an underlying' : 'a symbol'} to continue.
          </p>
        )}

        <div className="flex justify-end border-t pt-4">
          <Button
            type="button"
            onClick={onConfirm}
            disabled={!underlying || !exchange || (isDerivative && !expiryType)}
          >
            <Check className="h-4 w-4 mr-1.5" />
            Confirm
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
