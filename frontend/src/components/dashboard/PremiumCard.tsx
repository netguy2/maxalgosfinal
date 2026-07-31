// components/dashboard/PremiumCard.tsx
// Standardized card styling for the redesigned Dashboard — wraps the
// existing Card primitive (components/ui/card.tsx) instead of the
// hand-rolled `<div className="p-5 rounded-2xl bg-card border ...">`
// pattern the old Dashboard.tsx repeated per-section with inconsistent
// radii (mix of rounded-xl/rounded-2xl). Every dashboard subcomponent
// should use this instead of styling its own card shell.

import type * as React from 'react'
import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils'

const PREMIUM_CARD_CLASSES =
  'rounded-2xl border-border/60 shadow-sm hover:shadow-lg hover:-translate-y-0.5 transition-all duration-200'

export function PremiumCard({ className, ...props }: React.ComponentProps<typeof Card>) {
  return <Card className={cn(PREMIUM_CARD_CLASSES, className)} {...props} />
}
