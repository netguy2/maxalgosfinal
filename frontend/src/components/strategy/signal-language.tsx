import {
  ArrowLeftRight,
  ArrowRight,
  BadgeHelp,
  Ban,
  LogIn,
  LogOut,
  Minus,
  Plus,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { Badge } from '@/components/ui/badge'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'

/**
 * Shared visual language for the webhook configuration surface.
 *
 * The page previously gave every field and every value identical weight, so
 * nothing communicated meaning at a glance -- a BUY row and an EXIT row
 * looked the same. Colour and iconography carry that meaning here, defined
 * ONCE so the flow diagram, the mapping cards and the form can't drift into
 * three different dialects of the same idea.
 *
 * Colour rule: opening/bullish reads profit-green, closing/bearish reads
 * loss-red, reversal reads brand, muted reads grey. Semantic tokens only
 * (text-profit / text-loss / text-brand) -- never raw hex -- so light and
 * dark themes both work.
 */

export interface Tone {
  /** Badge/chip classes. */
  chip: string
  /** Foreground-only, for icons and inline text. */
  fg: string
  /** Subtle background for panels/nodes. */
  panel: string
}

const TONES: Record<string, Tone> = {
  positive: {
    chip: 'bg-profit/10 text-profit border-profit/30',
    fg: 'text-profit',
    panel: 'bg-profit/5 border-profit/20',
  },
  negative: {
    chip: 'bg-loss/10 text-loss border-loss/30',
    fg: 'text-loss',
    panel: 'bg-loss/5 border-loss/20',
  },
  brand: {
    chip: 'bg-brand/10 text-brand border-brand/30',
    fg: 'text-brand',
    panel: 'bg-brand/5 border-brand/20',
  },
  muted: {
    chip: 'bg-muted text-muted-foreground border-border',
    fg: 'text-muted-foreground',
    panel: 'bg-muted/30 border-border',
  },
}

/** Which incoming webhook signal a mapping listens for. */
export const SIGNAL_TONE: Record<string, Tone> = {
  BUY: TONES.positive,
  SELL: TONES.negative,
  SHORT: TONES.negative,
  EXIT: TONES.muted,
  BOTH: TONES.brand,
}

/** What the mapping DOES when that signal arrives. */
export const VERB_META: Record<
  string,
  { tone: Tone; icon: typeof LogIn; label: string; help: string }
> = {
  ENTER: {
    tone: TONES.positive,
    icon: LogIn,
    label: 'Enter',
    help: 'Opens a new position.',
  },
  ADD: {
    tone: TONES.positive,
    icon: Plus,
    label: 'Add',
    help: 'Adds to a position you already hold (pyramiding).',
  },
  EXIT: {
    tone: TONES.negative,
    icon: LogOut,
    label: 'Exit',
    help: 'Closes the open position for this instrument.',
  },
  REDUCE: {
    tone: TONES.negative,
    icon: Minus,
    label: 'Reduce',
    help: 'Partially closes an existing position.',
  },
  REVERSE: {
    tone: TONES.brand,
    icon: ArrowLeftRight,
    label: 'Reverse',
    help: 'Closes what is open, then enters the opposite side.',
  },
  IGNORE: {
    tone: TONES.muted,
    icon: Ban,
    label: 'Ignore',
    help: 'Does nothing — mutes this signal without deleting the row.',
  },
}

export function toneForSignal(signal?: string | null): Tone {
  return SIGNAL_TONE[(signal || '').toUpperCase()] ?? TONES.muted
}

export function metaForVerb(verb?: string | null) {
  return VERB_META[(verb || 'ENTER').toUpperCase()] ?? VERB_META.ENTER
}

/**
 * Plain-English explanations for the jargon this page unavoidably uses.
 *
 * A trader who already knows what NRML means loses nothing; a first-time
 * user previously had no way to find out without leaving the page. Keyed by
 * the field the term belongs to.
 */
export const FIELD_HELP: Record<string, string> = {
  reactToSignal:
    'Which incoming webhook signal fires this rule. Your TradingView alert sends BUY, SELL, SHORT or EXIT — this row only reacts to the one you pick.',
  orderSide:
    'The actual BUY or SELL order sent to your broker. Leave on Default unless you want a signal to place the opposite order — e.g. a SELL signal buying a Put.',
  instrumentType:
    'Equity trades the share itself. Futures and Options trade derivative contracts, which are resolved live on every signal so they never go stale.',
  underlying: 'The base instrument the contract derives from, e.g. NIFTY or RELIANCE.',
  exchange:
    'Where the order is routed. NFO is NSE derivatives, BFO is BSE derivatives, MCX is commodities.',
  expiry:
    'Which contract cycle to trade. Re-resolved on every signal, so "Current Weekly" always means the live weekly contract — never an expired one.',
  optionType: 'CE is a Call (gains when price rises). PE is a Put (gains when price falls).',
  strikeSelection:
    'How the strike is chosen. Offset picks a fixed distance from ATM; Premium/Delta pick whichever strike is closest to a target value right now; Max OI picks the most-traded strike.',
  strikeOffset:
    'How far from the at-the-money strike. ATM is nearest to spot, OTM1/2 are further out-of-the-money (cheaper, lower probability), ITM1/2 are in-the-money (costlier, higher probability).',
  quantity:
    'Number of units sent to the broker. For F&O this is contracts — use Lots below if you would rather size in lots and let the platform apply the lot size.',
  productType:
    'MIS is intraday and auto-squared-off by the exchange. CNC is delivery for equity. NRML carries F&O positions overnight.',
  signalAction: 'What this rule does when its signal arrives.',
  orderType:
    'Market fills immediately at the going price. Limit waits for your price. SL/SL-M trigger once price reaches a level.',
  stopLoss: 'Exits automatically if price moves against you by this much.',
  target: 'Books profit automatically at this move in your favour.',
  trailing:
    'Follows price as it moves your way, tightening the stop and locking in gains. Managed by the platform, so it works even on brokers with no trailing support.',
  lots: 'Size in lots instead of raw quantity. The contract lot size is resolved from the live contract.',
  legBasket:
    'Legs sharing a basket name are placed together on one signal — that is how a straddle or spread enters as a unit. If any leg cannot be resolved, none are sent.',
  label: 'A friendly name for this rule, shown in the execution flow above.',
  conditions:
    'Extra checks that must also pass before this rule fires — e.g. only trade after 09:20.',
}

/** A small "?" that reveals an explanation on hover/focus. */
export function HelpTip({ text, className }: { text: string; className?: string }) {
  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            // Not a form control -- keep it out of tab order for keyboard
            // users filling the form, but still hoverable and focusable via
            // the tooltip's own handling.
            tabIndex={-1}
            aria-label="What does this mean?"
            className={`inline-flex text-muted-foreground/60 transition-colors hover:text-foreground ${className ?? ''}`}
          >
            <BadgeHelp className="h-3.5 w-3.5" />
          </button>
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-[260px] text-xs leading-relaxed">
          {text}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}

/** A field label with its jargon explanation attached. */
export function FieldLabel({
  children,
  help,
  htmlFor,
}: {
  children: ReactNode
  help?: string
  htmlFor?: string
}) {
  return (
    <div className="flex items-center gap-1.5">
      <label htmlFor={htmlFor} className="text-xs font-medium leading-none text-foreground/90">
        {children}
      </label>
      {help && <HelpTip text={help} />}
    </div>
  )
}

/** Coloured chip for a signal or verb. */
export function ToneBadge({
  tone,
  icon: Icon,
  children,
  className,
}: {
  tone: Tone
  icon?: typeof LogIn
  children: ReactNode
  className?: string
}) {
  return (
    <Badge variant="outline" className={`gap-1 font-semibold ${tone.chip} ${className ?? ''}`}>
      {Icon && <Icon className="h-3 w-3" />}
      {children}
    </Badge>
  )
}

/** Chevron used between steps of the execution flow. */
export function FlowArrow({ vertical = false }: { vertical?: boolean }) {
  return (
    <ArrowRight
      aria-hidden
      className={`h-3.5 w-3.5 shrink-0 text-muted-foreground/50 ${vertical ? 'rotate-90' : ''}`}
    />
  )
}
