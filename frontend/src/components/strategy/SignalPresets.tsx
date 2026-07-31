import { ArrowLeftRight, LogOut, Minus, Plus, Shield, TrendingDown, TrendingUp } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import type { MappingAction, SignalAction } from '@/types/strategy'

/** One leg a preset will create. Mirrors the add-symbol payload, but only
 * the fields a preset actually decides -- the underlying, expiry and
 * quantity still come from what the user picked in the form above, so a
 * preset never silently overrides an explicit choice. */
export interface PresetLeg {
  action: MappingAction
  signalAction: SignalAction
  optionType?: 'CE' | 'PE'
  orderSide?: 'BUY' | 'SELL'
  strikeOffset?: string
  legBasket?: string
  label: string
}

export interface SignalPreset {
  id: string
  name: string
  description: string
  /** Plain-English "what will happen", shown before the user commits. */
  outcome: string
  icon: typeof TrendingUp
  legs: PresetLeg[]
}

/**
 * One-click starting points.
 *
 * The Configure Symbols form exposes ~18 controls. That is the right amount
 * of power for someone who knows exactly what they want, and far too many
 * decisions for someone setting up their first webhook -- there was no
 * guided path at all, just an empty table and a wall of dropdowns.
 *
 * Each preset collapses that into a single click by filling every field
 * that the preset itself implies, then leaving the user to confirm. They
 * are deliberately the shapes people actually trade off a TradingView
 * alert, not an exhaustive catalogue.
 */
export const SIGNAL_PRESETS: SignalPreset[] = [
  {
    id: 'long-call',
    name: 'Buy Call on BUY',
    description: 'Simplest bullish setup.',
    outcome: 'A BUY signal buys one ATM Call. Nothing happens on SELL.',
    icon: TrendingUp,
    legs: [
      {
        action: 'BUY',
        signalAction: 'ENTER',
        optionType: 'CE',
        orderSide: 'BUY',
        strikeOffset: 'ATM',
        label: 'Long Call',
      },
    ],
  },
  {
    id: 'long-put',
    name: 'Buy Put on SELL',
    description: 'Simplest bearish setup.',
    outcome: 'A SELL signal buys one ATM Put. Nothing happens on BUY.',
    icon: TrendingDown,
    legs: [
      {
        action: 'SELL',
        signalAction: 'ENTER',
        optionType: 'PE',
        orderSide: 'BUY',
        strikeOffset: 'ATM',
        label: 'Long Put',
      },
    ],
  },
  {
    id: 'call-put-flip',
    name: 'Call / Put Reversal',
    description: 'Flip sides on every signal.',
    outcome:
      'BUY exits any Put and enters a Call. SELL exits any Call and enters a Put. Always one side on.',
    icon: ArrowLeftRight,
    legs: [
      {
        action: 'BUY',
        signalAction: 'EXIT',
        optionType: 'PE',
        strikeOffset: 'ATM',
        label: 'Exit Put',
      },
      {
        action: 'BUY',
        signalAction: 'ENTER',
        optionType: 'CE',
        orderSide: 'BUY',
        strikeOffset: 'ATM',
        label: 'Enter Call',
      },
      {
        action: 'SELL',
        signalAction: 'EXIT',
        optionType: 'CE',
        strikeOffset: 'ATM',
        label: 'Exit Call',
      },
      {
        action: 'SELL',
        signalAction: 'ENTER',
        optionType: 'PE',
        orderSide: 'BUY',
        strikeOffset: 'ATM',
        label: 'Enter Put',
      },
    ],
  },
  {
    id: 'long-straddle',
    name: 'Long Straddle',
    description: 'Buy both sides — profits from a big move either way.',
    outcome: 'One BUY signal buys an ATM Call AND an ATM Put together, as one basket.',
    icon: Plus,
    legs: [
      {
        action: 'BUY',
        signalAction: 'ENTER',
        optionType: 'CE',
        orderSide: 'BUY',
        strikeOffset: 'ATM',
        legBasket: 'straddle',
        label: 'Straddle Call',
      },
      {
        action: 'BUY',
        signalAction: 'ENTER',
        optionType: 'PE',
        orderSide: 'BUY',
        strikeOffset: 'ATM',
        legBasket: 'straddle',
        label: 'Straddle Put',
      },
    ],
  },
  {
    id: 'short-strangle',
    name: 'Short Strangle',
    description: 'Sell OTM both sides — profits if price stays put.',
    outcome: 'One SELL signal sells an OTM2 Call AND an OTM2 Put together, as one basket.',
    icon: Minus,
    legs: [
      {
        action: 'SELL',
        signalAction: 'ENTER',
        optionType: 'CE',
        orderSide: 'SELL',
        strikeOffset: 'OTM2',
        legBasket: 'strangle',
        label: 'Strangle Call',
      },
      {
        action: 'SELL',
        signalAction: 'ENTER',
        optionType: 'PE',
        orderSide: 'SELL',
        strikeOffset: 'OTM2',
        legBasket: 'strangle',
        label: 'Strangle Put',
      },
    ],
  },
  {
    id: 'iron-condor',
    name: 'Iron Condor',
    description: 'Sell a range, buy wings for protection.',
    outcome:
      'One SELL signal builds all 4 legs together: sell OTM2 Call+Put, buy OTM4 wings to cap risk.',
    icon: Shield,
    legs: [
      {
        action: 'SELL',
        signalAction: 'ENTER',
        optionType: 'CE',
        orderSide: 'SELL',
        strikeOffset: 'OTM2',
        legBasket: 'iron-condor',
        label: 'Short Call',
      },
      {
        action: 'SELL',
        signalAction: 'ENTER',
        optionType: 'CE',
        orderSide: 'BUY',
        strikeOffset: 'OTM4',
        legBasket: 'iron-condor',
        label: 'Long Call Wing',
      },
      {
        action: 'SELL',
        signalAction: 'ENTER',
        optionType: 'PE',
        orderSide: 'SELL',
        strikeOffset: 'OTM2',
        legBasket: 'iron-condor',
        label: 'Short Put',
      },
      {
        action: 'SELL',
        signalAction: 'ENTER',
        optionType: 'PE',
        orderSide: 'BUY',
        strikeOffset: 'OTM4',
        legBasket: 'iron-condor',
        label: 'Long Put Wing',
      },
    ],
  },
  {
    id: 'iron-fly',
    name: 'Iron Butterfly',
    description: 'Sell ATM straddle, buy wings.',
    outcome:
      'One SELL signal builds 4 legs: sell the ATM Call+Put, buy OTM3 wings so loss is capped.',
    icon: Shield,
    legs: [
      {
        action: 'SELL',
        signalAction: 'ENTER',
        optionType: 'CE',
        orderSide: 'SELL',
        strikeOffset: 'ATM',
        legBasket: 'iron-fly',
        label: 'Short Call',
      },
      {
        action: 'SELL',
        signalAction: 'ENTER',
        optionType: 'PE',
        orderSide: 'SELL',
        strikeOffset: 'ATM',
        legBasket: 'iron-fly',
        label: 'Short Put',
      },
      {
        action: 'SELL',
        signalAction: 'ENTER',
        optionType: 'CE',
        orderSide: 'BUY',
        strikeOffset: 'OTM3',
        legBasket: 'iron-fly',
        label: 'Long Call Wing',
      },
      {
        action: 'SELL',
        signalAction: 'ENTER',
        optionType: 'PE',
        orderSide: 'BUY',
        strikeOffset: 'OTM3',
        legBasket: 'iron-fly',
        label: 'Long Put Wing',
      },
    ],
  },
  {
    id: 'bull-call-spread',
    name: 'Bull Call Spread',
    description: 'Bullish, with a capped cost and capped gain.',
    outcome: 'One BUY signal buys the ATM Call and sells an OTM2 Call to fund it.',
    icon: TrendingUp,
    legs: [
      {
        action: 'BUY',
        signalAction: 'ENTER',
        optionType: 'CE',
        orderSide: 'BUY',
        strikeOffset: 'ATM',
        legBasket: 'bull-call',
        label: 'Long Call',
      },
      {
        action: 'BUY',
        signalAction: 'ENTER',
        optionType: 'CE',
        orderSide: 'SELL',
        strikeOffset: 'OTM2',
        legBasket: 'bull-call',
        label: 'Short Call',
      },
    ],
  },
  {
    id: 'bear-put-spread',
    name: 'Bear Put Spread',
    description: 'Bearish, with a capped cost and capped gain.',
    outcome: 'One SELL signal buys the ATM Put and sells an OTM2 Put to fund it.',
    icon: TrendingDown,
    legs: [
      {
        action: 'SELL',
        signalAction: 'ENTER',
        optionType: 'PE',
        orderSide: 'BUY',
        strikeOffset: 'ATM',
        legBasket: 'bear-put',
        label: 'Long Put',
      },
      {
        action: 'SELL',
        signalAction: 'ENTER',
        optionType: 'PE',
        orderSide: 'SELL',
        strikeOffset: 'OTM2',
        legBasket: 'bear-put',
        label: 'Short Put',
      },
    ],
  },
  {
    id: 'exit-only',
    name: 'Exit Only',
    description: 'Close positions on a signal, never open.',
    outcome: 'An EXIT signal flattens this instrument. Entries are handled elsewhere.',
    icon: LogOut,
    legs: [
      {
        action: 'EXIT',
        signalAction: 'EXIT',
        optionType: 'CE',
        strikeOffset: 'ATM',
        label: 'Flatten',
      },
    ],
  },
]

interface Props {
  onApply: (preset: SignalPreset) => void
  disabled?: boolean
  /** Why presets can't be used yet, if they can't. Shown in place of the
   * grid rather than fired as an error toast after the user clicks -- a
   * control that looks available but rejects every click is worse than one
   * that plainly says what it needs first. */
  blockedReason?: string | null
  /** Underlying/expiry chosen in Step 1, echoed so the user can see what
   * the preset will actually be applied to before committing. */
  contextLabel?: string
}

/**
 * Preset picker shown above the manual form. Applying one adds every leg
 * it defines, so a straddle is one click instead of two full passes
 * through an 18-field form.
 */
export function SignalPresets({ onApply, disabled, blockedReason, contextLabel }: Props) {
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center gap-2">
          <CardTitle className="text-base">Quick Start</CardTitle>
          {/* Echoes what Step 1 resolved, so the user can see what a preset
          will be applied to before committing. Only shown once ready. */}
          {contextLabel && (
            <Badge variant="secondary" className="text-[10px]">
              {contextLabel}
            </Badge>
          )}
        </div>
        <CardDescription>
          Pick a common setup and we&apos;ll fill everything in. You can edit or remove any row
          afterwards — or skip this and build it manually below.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {blockedReason ? (
          <div className="rounded-lg border border-dashed p-6 text-center">
            <p className="text-sm font-medium">{blockedReason}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Finish choosing what you&apos;re trading above and these setups will unlock.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {SIGNAL_PRESETS.map((preset) => {
              const Icon = preset.icon
              return (
                <button
                  key={preset.id}
                  type="button"
                  disabled={disabled}
                  onClick={() => onApply(preset)}
                  className="flex flex-col gap-1.5 rounded-lg border p-3 text-left transition-colors hover:border-brand/50 hover:bg-muted/50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <div className="flex items-center gap-2">
                    <Icon className="h-4 w-4 shrink-0 text-brand" />
                    <span className="text-sm font-medium">{preset.name}</span>
                    <Badge variant="secondary" className="ml-auto text-[10px]">
                      {preset.legs.length} leg{preset.legs.length > 1 ? 's' : ''}
                    </Badge>
                  </div>
                  <p className="text-xs text-muted-foreground">{preset.description}</p>
                  <p className="text-[11px] leading-tight text-muted-foreground/80">
                    {preset.outcome}
                  </p>
                </button>
              )
            })}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
