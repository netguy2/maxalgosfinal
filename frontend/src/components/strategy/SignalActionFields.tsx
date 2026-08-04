import { ChevronDown, Layers, ShieldAlert, Sliders } from 'lucide-react'
import { useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  ORDER_TYPES,
  type OrderType,
  RISK_VALUE_TYPES,
  type RiskValueType,
  SIGNAL_ACTIONS,
  type SignalAction,
} from '@/types/strategy'

/** The subset of the page's form state this component owns. Kept
 * structural (rather than importing the page's interface) so the page can
 * evolve its own fields without churning this file. */
export interface SignalActionFormFields {
  signalAction: SignalAction
  orderType: OrderType
  limitPrice: string
  triggerPrice: string
  stopLossValue: string
  stopLossType: RiskValueType
  targetValue: string
  targetType: RiskValueType
  trailingValue: string
  trailingType: RiskValueType
  lots: string
  legBasket: string
  label: string
}

interface Props<T extends SignalActionFormFields> {
  form: T
  setForm: React.Dispatch<React.SetStateAction<T>>
  isOption: boolean
  isDerivative: boolean
  /** Render without the collapsible chrome (used inside the edit dialog,
   * which is already a focused surface). */
  alwaysOpen?: boolean
  /** Hide the "On Signal, Do" select -- set when the caller renders it
   * itself in a more prominent spot (directly under "React to Signal",
   * where the old BUY/SELL "Order Side" override used to sit). The
   * underlying signalAction form field is unaffected either way; this only
   * controls where its control appears. */
  hideSignalAction?: boolean
}

/** One risk row: a numeric value plus its percent/points unit. */
function RiskRow<T extends SignalActionFormFields>({
  label,
  hint,
  valueKey,
  typeKey,
  form,
  setForm,
}: {
  label: string
  hint: string
  valueKey: 'stopLossValue' | 'targetValue' | 'trailingValue'
  typeKey: 'stopLossType' | 'targetType' | 'trailingType'
  form: T
  setForm: React.Dispatch<React.SetStateAction<T>>
}) {
  return (
    <div className="space-y-2">
      <Label className="text-xs">{label}</Label>
      <div className="flex gap-1">
        <Input
          type="number"
          min="0"
          step="0.01"
          inputMode="decimal"
          placeholder="Off"
          value={form[valueKey]}
          onChange={(e) => setForm((f) => ({ ...f, [valueKey]: e.target.value }))}
          aria-label={label}
          // Chrome autofilled these unlabeled inputs with junk (a stray "0"
          // into Trailing Stop), which then submitted as REAL trading config
          // -- a silently-wrong stop is worse than no stop. name+autoComplete
          // off is what actually suppresses it; autoComplete alone is not
          // enough in Chrome.
          name={`risk-${valueKey}`}
          autoComplete="off"
          data-1p-ignore
          data-lpignore="true"
        />
        <Select
          value={form[typeKey]}
          onValueChange={(v: RiskValueType) => setForm((f) => ({ ...f, [typeKey]: v }))}
        >
          <SelectTrigger className="w-[70px] shrink-0" aria-label={`${label} unit`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {RISK_VALUE_TYPES.map((t) => (
              <SelectItem key={t.value} value={t.value}>
                {t.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <p className="text-[11px] leading-tight text-muted-foreground">{hint}</p>
    </div>
  )
}

/**
 * Advanced per-signal configuration: what the signal DOES, how the order
 * is placed, the protective orders that follow a fill, lot sizing, and
 * multi-leg basket grouping.
 *
 * Collapsed by default. Everything here is optional — leaving it untouched
 * produces exactly the payload the form produced before these fields
 * existed, so the simple "add a symbol" flow is unaffected.
 */
export function SignalActionFields<T extends SignalActionFormFields>({
  form,
  setForm,
  isOption,
  isDerivative,
  alwaysOpen = false,
  hideSignalAction = false,
}: Props<T>) {
  const [open, setOpen] = useState(alwaysOpen)

  // Count what the user has actually configured, so the collapsed header
  // shows at a glance that this section is non-empty.
  const configured = [
    form.signalAction !== 'ENTER',
    form.orderType !== 'MARKET',
    Boolean(form.stopLossValue.trim()),
    Boolean(form.targetValue.trim()),
    Boolean(form.trailingValue.trim()),
    Boolean(form.lots.trim()),
    Boolean(form.legBasket.trim()),
  ].filter(Boolean).length

  const needsLimit = form.orderType === 'LIMIT' || form.orderType === 'SL'
  const needsTrigger = form.orderType === 'SL' || form.orderType === 'SL-M'

  const body = (
    <div className="space-y-5 rounded-lg border bg-muted/20 p-4">
      {/* What the signal does + how the order is placed */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
        {!hideSignalAction && (
          <div className="space-y-2">
            <Label className="text-xs">On Signal, Do</Label>
            <Select
              value={form.signalAction}
              onValueChange={(v: SignalAction) => setForm((f) => ({ ...f, signalAction: v }))}
            >
              <SelectTrigger aria-label="On signal, do">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SIGNAL_ACTIONS.map((a) => (
                  <SelectItem key={a.value} value={a.value}>
                    {a.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-[11px] leading-tight text-muted-foreground">
              {SIGNAL_ACTIONS.find((a) => a.value === form.signalAction)?.description}
            </p>
          </div>
        )}

        <div className="space-y-2">
          <Label className="text-xs">Order Type</Label>
          <Select
            value={form.orderType}
            onValueChange={(v: OrderType) => setForm((f) => ({ ...f, orderType: v }))}
          >
            <SelectTrigger aria-label="Order type">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {ORDER_TYPES.map((t) => (
                <SelectItem key={t.value} value={t.value}>
                  {t.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {needsLimit && (
          <div className="space-y-2">
            <Label className="text-xs">Limit Price</Label>
            <Input
              type="number"
              min="0"
              step="0.05"
              inputMode="decimal"
              value={form.limitPrice}
              onChange={(e) => setForm((f) => ({ ...f, limitPrice: e.target.value }))}
              name="signal-limit-price"
              autoComplete="off"
              data-1p-ignore
              data-lpignore="true"
              aria-label="Limit price"
            />
          </div>
        )}

        {needsTrigger && (
          <div className="space-y-2">
            <Label className="text-xs">Trigger Price</Label>
            <Input
              type="number"
              min="0"
              step="0.05"
              inputMode="decimal"
              value={form.triggerPrice}
              onChange={(e) => setForm((f) => ({ ...f, triggerPrice: e.target.value }))}
              name="signal-trigger-price"
              autoComplete="off"
              data-1p-ignore
              data-lpignore="true"
              aria-label="Trigger price"
            />
          </div>
        )}
      </div>

      {/* Protective orders */}
      <div>
        <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
          <ShieldAlert className="h-3.5 w-3.5" />
          Risk Management
          <span className="font-normal">— placed automatically after entry fills</span>
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <RiskRow
            label="Stop Loss"
            hint="Exit if price moves against you by this much."
            valueKey="stopLossValue"
            typeKey="stopLossType"
            form={form}
            setForm={setForm}
          />
          <RiskRow
            label="Target"
            hint="Book profit at this move in your favour."
            valueKey="targetValue"
            typeKey="targetType"
            form={form}
            setForm={setForm}
          />
          <RiskRow
            label="Trailing Stop"
            hint="Trail the stop as price moves your way."
            valueKey="trailingValue"
            typeKey="trailingType"
            form={form}
            setForm={setForm}
          />
        </div>
      </div>

      {/* Sizing + multi-leg */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {isDerivative && (
          <div className="space-y-2">
            <Label className="text-xs">Lots</Label>
            <Input
              type="number"
              min="1"
              step="1"
              inputMode="numeric"
              placeholder="Use quantity"
              value={form.lots}
              onChange={(e) => setForm((f) => ({ ...f, lots: e.target.value }))}
              aria-label="Lots"
              name="signal-lots"
              autoComplete="off"
              data-1p-ignore
              data-lpignore="true"
            />
            <p className="text-[11px] leading-tight text-muted-foreground">
              Overrides Quantity. Lot size is resolved from the live contract.
            </p>
          </div>
        )}

        {isOption && (
          <div className="space-y-2">
            <Label className="flex items-center gap-1.5 text-xs">
              <Layers className="h-3.5 w-3.5" />
              Multi-Leg Basket
            </Label>
            <Input
              placeholder="e.g. straddle"
              value={form.legBasket}
              onChange={(e) => setForm((f) => ({ ...f, legBasket: e.target.value }))}
              aria-label="Multi-leg basket name"
              // Chrome autofilled this with "new" from unrelated saved form
              // data, silently grouping a standalone leg into a basket.
              name="signal-leg-basket"
              autoComplete="off"
              data-1p-ignore
              data-lpignore="true"
            />
            <p className="text-[11px] leading-tight text-muted-foreground">
              Legs sharing a name fire together on one signal.
            </p>
          </div>
        )}

        <div className="space-y-2">
          <Label className="text-xs">Label</Label>
          <Input
            placeholder="e.g. Long Call"
            value={form.label}
            onChange={(e) => setForm((f) => ({ ...f, label: e.target.value }))}
            aria-label="Label"
            name="signal-label"
            autoComplete="off"
            data-1p-ignore
            data-lpignore="true"
          />
          <p className="text-[11px] leading-tight text-muted-foreground">
            Shown in the Signal Flow overview.
          </p>
        </div>
      </div>
    </div>
  )

  if (alwaysOpen) return body

  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 rounded-md border px-3 py-2 text-sm font-medium transition-colors hover:bg-muted/50"
      >
        <Sliders className="h-4 w-4" />
        Signal Action, Risk &amp; Multi-Leg
        {configured > 0 && (
          <Badge variant="secondary" className="text-[10px]">
            {configured} set
          </Badge>
        )}
        <ChevronDown
          className={`ml-auto h-4 w-4 transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>
      {open && body}
    </div>
  )
}
