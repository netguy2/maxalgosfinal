import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { StrikeSelectionMode } from '@/types/strategy'
import { STRIKE_OFFSETS, STRIKE_SELECTION_MODES } from '@/types/strategy'

export interface StrikeSelectorValue {
  mode: StrikeSelectionMode
  /** Used when mode === 'offset' -- one of STRIKE_OFFSETS. */
  offsetValue: string
  /** Used when mode is 'premium' | 'delta' -- ignored for 'oi' (no target needed). */
  targetValue: string
}

/** Shared strike-selection control -- a mode picker (Offset / Premium /
 * Delta / Max OI) that swaps the field below it. Used everywhere a user
 * configures an Options strike: the single-symbol add/edit forms in
 * ConfigureSymbols.tsx and the leg builder/quick-create in
 * LegGroupsPanel.tsx. Previously each of those 4 call sites hand-rolled an
 * identical `STRIKE_OFFSETS` dropdown; this factors that out and adds the
 * three new modes in one place. */
export default function StrikeSelector({
  value,
  onChange,
}: {
  value: StrikeSelectorValue
  onChange: (next: StrikeSelectorValue) => void
}) {
  return (
    <>
      <div className="space-y-2">
        <Label>Strike Selection</Label>
        <Select
          value={value.mode}
          onValueChange={(mode: StrikeSelectionMode) => onChange({ ...value, mode })}
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {STRIKE_SELECTION_MODES.map((m) => (
              <SelectItem key={m.value} value={m.value}>
                {m.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-xs text-muted-foreground">
          {STRIKE_SELECTION_MODES.find((m) => m.value === value.mode)?.description}
        </p>
      </div>

      {value.mode === 'offset' && (
        <div className="space-y-2">
          <Label>Strike</Label>
          <Select
            value={value.offsetValue}
            onValueChange={(offsetValue) => onChange({ ...value, offsetValue })}
          >
            <SelectTrigger>
              <SelectValue placeholder="Select strike" />
            </SelectTrigger>
            <SelectContent>
              {STRIKE_OFFSETS.map((s) => (
                <SelectItem key={s} value={s}>
                  {s}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {value.mode === 'premium' && (
        <div className="space-y-2">
          <Label>Target Premium (₹)</Label>
          <Input
            type="number"
            min="0"
            step="0.05"
            value={value.targetValue}
            onChange={(e) => onChange({ ...value, targetValue: e.target.value })}
            placeholder="e.g. 150"
          />
        </div>
      )}

      {value.mode === 'delta' && (
        <div className="space-y-2">
          <Label>Target Delta</Label>
          <Input
            type="number"
            min="0"
            max="1"
            step="0.05"
            value={value.targetValue}
            onChange={(e) => onChange({ ...value, targetValue: e.target.value })}
            placeholder="e.g. 0.3"
          />
        </div>
      )}
    </>
  )
}
