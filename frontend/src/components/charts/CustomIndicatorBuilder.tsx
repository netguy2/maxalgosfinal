// components/charts/CustomIndicatorBuilder.tsx
// Dialog for building a custom indicator from a fixed, safe menu of
// building blocks — no free-text formula input, no code execution. Two
// modes:
//   - Combine: operand A [op] operand B (e.g. EMA(20) − SMA(50)), plotted
//     as an overlay line.
//   - Threshold: operand A crosses above/below a fixed value (e.g. RSI(14)
//     crosses above 70), produces BUY/SELL markers.
//
// Reuses the exact Indicator/Period Select+Input vocabulary already
// established in components/flow/panels/ConfigPanel.tsx's
// IndicatorConditionNode editor (RSI/EMA/SMA/MACD/ATR/VWAP dropdown +
// conditional period field) rather than inventing new UI language —
// extended here with BOLLINGER (already supported server-side) and MACD
// excluded (multi-output, not a valid single-value operand).

import { useState } from 'react'
import {
  type CustomIndicatorFormula,
  type CustomIndicatorOperand,
  customIndicatorsApi,
} from '@/api/custom-indicators'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { showToast } from '@/utils/toast'

const OPERAND_INDICATORS: CustomIndicatorOperand['indicator'][] = [
  'EMA',
  'SMA',
  'VWAP',
  'RSI',
  'ATR',
  'BOLLINGER',
]

const COMBINE_OPS: { value: '+' | '-' | '*' | '/'; label: string }[] = [
  { value: '-', label: '− (difference)' },
  { value: '+', label: '+ (sum)' },
  { value: '*', label: '× (product)' },
  { value: '/', label: '÷ (ratio)' },
]

const COLOR_SWATCHES = ['#f59e0b', '#8b5cf6', '#06b6d4', '#ec4899', '#22c55e', '#ef4444', '#3b82f6']

const DEFAULT_PERIOD_BY_INDICATOR: Record<string, number> = {
  EMA: 20,
  SMA: 50,
  RSI: 14,
  ATR: 14,
  BOLLINGER: 20,
}

function OperandFields({
  label,
  operand,
  onChange,
}: {
  label: string
  operand: CustomIndicatorOperand
  onChange: (operand: CustomIndicatorOperand) => void
}) {
  return (
    <div className="grid grid-cols-2 gap-2">
      <div className="space-y-1">
        <Label className="text-[11px] text-muted-foreground">{label}</Label>
        <Select
          value={operand.indicator}
          onValueChange={(v: CustomIndicatorOperand['indicator']) =>
            onChange({ indicator: v, period: DEFAULT_PERIOD_BY_INDICATOR[v] })
          }
        >
          <SelectTrigger className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {OPERAND_INDICATORS.map((ind) => (
              <SelectItem key={ind} value={ind}>
                {ind}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {operand.indicator !== 'VWAP' && (
        <div className="space-y-1">
          <Label className="text-[11px] text-muted-foreground">Period</Label>
          <Input
            type="number"
            min={1}
            className="h-8 text-xs"
            value={operand.period ?? ''}
            onChange={(e) => onChange({ ...operand, period: parseInt(e.target.value, 10) || 1 })}
          />
        </div>
      )}
    </div>
  )
}

function formatOperand(op: CustomIndicatorOperand): string {
  return op.indicator === 'VWAP' ? 'VWAP' : `${op.indicator}(${op.period ?? '?'})`
}

interface CustomIndicatorBuilderProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated: () => void
}

export function CustomIndicatorBuilder({
  open,
  onOpenChange,
  onCreated,
}: CustomIndicatorBuilderProps) {
  const [name, setName] = useState('')
  const [mode, setMode] = useState<'combine' | 'threshold'>('combine')
  const [operandA, setOperandA] = useState<CustomIndicatorOperand>({ indicator: 'EMA', period: 20 })
  const [operandB, setOperandB] = useState<CustomIndicatorOperand>({ indicator: 'SMA', period: 50 })
  const [combineOp, setCombineOp] = useState<'+' | '-' | '*' | '/'>('-')
  const [threshold, setThreshold] = useState(70)
  const [invert, setInvert] = useState(false)
  const [color, setColor] = useState(COLOR_SWATCHES[0])
  const [saving, setSaving] = useState(false)

  const preview =
    mode === 'combine'
      ? `${formatOperand(operandA)} ${combineOp} ${formatOperand(operandB)}`
      : `${formatOperand(operandA)} crosses ${invert ? 'below' : 'above'} ${threshold}`

  const reset = () => {
    setName('')
    setMode('combine')
    setOperandA({ indicator: 'EMA', period: 20 })
    setOperandB({ indicator: 'SMA', period: 50 })
    setCombineOp('-')
    setThreshold(70)
    setInvert(false)
    setColor(COLOR_SWATCHES[0])
  }

  const handleSave = async () => {
    if (!name.trim()) {
      showToast.error('Enter a name for the indicator')
      return
    }

    const formula: CustomIndicatorFormula =
      mode === 'combine'
        ? { kind: 'combine', op: combineOp, a: operandA, b: operandB }
        : { kind: 'threshold', a: operandA, threshold, invert }

    setSaving(true)
    try {
      const resp = await customIndicatorsApi.create(name.trim(), formula, color)
      if (resp.status === 'success') {
        showToast.success(`Custom indicator "${name.trim()}" saved`)
        reset()
        onOpenChange(false)
        onCreated()
      } else {
        showToast.error(resp.message || 'Failed to save indicator')
      }
    } catch (err) {
      showToast.error(err instanceof Error ? err.message : 'Failed to save indicator')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Create Custom Indicator</DialogTitle>
          <DialogDescription>
            Combine built-in indicators, or detect a threshold crossover — no code, built from a
            fixed set of safe building blocks.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div className="space-y-1">
            <Label className="text-[11px] text-muted-foreground">Name</Label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. EMA-SMA Spread"
              className="h-8 text-xs"
            />
          </div>

          <div className="inline-flex h-8 w-full overflow-hidden rounded-md border bg-background">
            <button
              type="button"
              onClick={() => setMode('combine')}
              className={cn(
                'flex-1 text-xs font-semibold transition-colors',
                mode === 'combine'
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:bg-muted'
              )}
            >
              Combine (line)
            </button>
            <button
              type="button"
              onClick={() => setMode('threshold')}
              className={cn(
                'flex-1 border-l text-xs font-semibold transition-colors',
                mode === 'threshold'
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:bg-muted'
              )}
            >
              Threshold cross (signal)
            </button>
          </div>

          <OperandFields
            label={mode === 'combine' ? 'Operand A' : 'Indicator'}
            operand={operandA}
            onChange={setOperandA}
          />

          {mode === 'combine' ? (
            <>
              <div className="space-y-1">
                <Label className="text-[11px] text-muted-foreground">Operator</Label>
                <Select
                  value={combineOp}
                  onValueChange={(v: '+' | '-' | '*' | '/') => setCombineOp(v)}
                >
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {COMBINE_OPS.map((o) => (
                      <SelectItem key={o.value} value={o.value}>
                        {o.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <OperandFields label="Operand B" operand={operandB} onChange={setOperandB} />
            </>
          ) : (
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <Label className="text-[11px] text-muted-foreground">Direction</Label>
                <Select
                  value={invert ? 'below' : 'above'}
                  onValueChange={(v) => setInvert(v === 'below')}
                >
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="above">Crosses above</SelectItem>
                    <SelectItem value="below">Crosses below</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label className="text-[11px] text-muted-foreground">Value</Label>
                <Input
                  type="number"
                  step="0.01"
                  className="h-8 text-xs"
                  value={threshold}
                  onChange={(e) => setThreshold(parseFloat(e.target.value) || 0)}
                />
              </div>
            </div>
          )}

          <div className="space-y-1">
            <Label className="text-[11px] text-muted-foreground">Color</Label>
            <div className="flex gap-1.5">
              {COLOR_SWATCHES.map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => setColor(c)}
                  className={cn(
                    'h-6 w-6 rounded-full border-2 transition-transform',
                    color === c ? 'scale-110 border-foreground' : 'border-transparent'
                  )}
                  style={{ backgroundColor: c }}
                  aria-label={`Choose color ${c}`}
                />
              ))}
            </div>
          </div>

          <div className="rounded-md border bg-muted/30 px-3 py-2 text-xs">
            <span className="text-muted-foreground">Formula: </span>
            <span className="font-mono">{preview}</span>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? 'Saving…' : 'Save Indicator'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
