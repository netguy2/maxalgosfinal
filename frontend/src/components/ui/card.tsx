import type * as React from 'react'

import { cn } from '@/lib/utils'

function Card({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="card"
      className={cn(
        'bg-card text-card-foreground flex flex-col gap-6 rounded-xl border py-6 shadow-sm',
        className
      )}
      {...props}
    />
  )
}

function CardHeader({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="card-header"
      className={cn(
        '@container/card-header grid auto-rows-min grid-rows-[auto_auto] items-start gap-2 px-6 has-data-[slot=card-action]:grid-cols-[1fr_auto] [.border-b]:pb-6',
        className
      )}
      {...props}
    />
  )
}

/**
 * Card title sizes. `default` is correct for essentially every card; the
 * others exist so the handful of legitimate exceptions are named rather than
 * improvised.
 *
 * This shipped with no size at all, so all ~120 call sites picked their own
 * (`text-sm`, `text-base`, `text-lg`, `text-2xl`, `text-xs`...). Cards sitting
 * side by side in the same grid had different title sizes. Defaulting here
 * means a plain <CardTitle> is automatically consistent.
 */
type CardTitleSize = 'sm' | 'default' | 'lg'

const CARD_TITLE_SIZE: Record<CardTitleSize, string> = {
  /** Dense/secondary cards and compact side panels. */
  sm: 'text-sm',
  /** The standard card heading. */
  default: 'text-base',
  /** Feature/hero cards that lead a page section. */
  lg: 'text-lg',
}

function CardTitle({
  className,
  size = 'default',
  ...props
}: React.ComponentProps<'div'> & { size?: CardTitleSize }) {
  return (
    <div
      data-slot="card-title"
      className={cn('leading-none font-semibold', CARD_TITLE_SIZE[size], className)}
      {...props}
    />
  )
}

function CardDescription({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="card-description"
      className={cn('text-muted-foreground text-sm', className)}
      {...props}
    />
  )
}

function CardAction({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="card-action"
      className={cn('col-start-2 row-span-2 row-start-1 self-start justify-self-end', className)}
      {...props}
    />
  )
}

function CardContent({ className, ...props }: React.ComponentProps<'div'>) {
  return <div data-slot="card-content" className={cn('px-6', className)} {...props} />
}

function CardFooter({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="card-footer"
      className={cn('flex items-center px-6 [.border-t]:pt-6', className)}
      {...props}
    />
  )
}

export { Card, CardHeader, CardFooter, CardTitle, CardAction, CardDescription, CardContent }
