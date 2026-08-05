import { Clock, Copy, Eye, Sparkles, Star } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import type { CatalogItem, CatalogTier } from '@/lib/marketplace-catalog'
import { cn } from '@/lib/utils'

const TIER_BADGE: Record<CatalogTier, { label: string; className: string }> = {
  free: { label: 'Free', className: 'bg-profit/15 text-profit border-profit/30' },
  pro: { label: 'Pro', className: 'bg-info/15 text-info border-info/30' },
  premium: { label: 'Premium', className: 'bg-brand/15 text-brand border-brand/30' },
  ai: { label: 'AI', className: 'bg-primary/15 text-primary border-primary/30' },
}

interface CatalogCardProps {
  item: CatalogItem
  isSubscribed?: boolean
  isTrial?: boolean
  onPrimary: (item: CatalogItem) => void
  onSecondary?: (item: CatalogItem) => void
  onStartTrial?: (item: CatalogItem) => void
}

/**
 * One marketplace/template card. Free & Pro items clone; Premium/AI items
 * offer 2-Day Free Trial or Subscribe.
 */
export function CatalogCard({
  item,
  isSubscribed,
  isTrial,
  onPrimary,
  onSecondary,
  onStartTrial,
}: CatalogCardProps) {
  const tier = TIER_BADGE[item.tier]
  const isTemplate = item.tier === 'free' || item.tier === 'pro'
  const isPremium = item.tier === 'premium' || item.tier === 'ai' || (item.price != null && item.price > 0)
  const hasMetrics = item.winRate != null || item.sharpe != null || item.monthlyReturn != null
  const isWiredTemplate = isTemplate && (item.signalId != null || item.optionsTemplateId != null)
  const isUnwiredTemplate = isTemplate && !isWiredTemplate

  const primaryLabel = isUnwiredTemplate
    ? 'Coming soon'
    : isTemplate
      ? 'Use Template'
      : isSubscribed
        ? 'Unsubscribe'
        : isTrial
          ? 'Trial Active'
          : item.strategyId
            ? 'Subscribe'
            : 'Preview'

  return (
    <Card
      className={cn(
        'relative flex flex-col justify-between overflow-hidden transition-colors border-border/80 shadow-xs',
        isUnwiredTemplate ? 'opacity-60' : 'interactive-surface'
      )}
    >
      {item.featured && <div className="absolute top-0 inset-x-0 h-1 bg-brand" />}
      <CardHeader className="p-3 space-y-1.5">
        <div className="flex items-center justify-between gap-1.5">
          <div className="flex items-center gap-1">
            <Badge
              variant="outline"
              className={cn('text-[9px] font-bold uppercase px-1.5 py-0 h-4', tier.className)}
            >
              {tier.label}
            </Badge>
            <Badge
              variant="outline"
              className="text-[9px] font-normal text-muted-foreground px-1.5 py-0 h-4"
            >
              {item.difficulty}
            </Badge>
          </div>
          {item.rating != null && (
            <span className="flex items-center gap-0.5 text-[11px] font-bold text-warning">
              <Star className="h-3 w-3 fill-current" />
              {item.rating}
            </span>
          )}
        </div>
        {isWiredTemplate && (
          <Badge
            variant="outline"
            className="w-fit text-[9px] font-semibold bg-profit/10 text-profit border-profit/30 px-1.5 py-0 h-4"
          >
            {item.optionsTemplateId ? 'Real option structure' : 'Generates working code'}
          </Badge>
        )}
        {isTrial && (
          <Badge
            variant="outline"
            className="w-fit text-[9px] font-semibold bg-warning/10 text-warning border-warning/30 px-1.5 py-0 h-4"
          >
            ⚡ 2-Day Trial Active
          </Badge>
        )}
        <CardTitle className="text-sm font-bold leading-tight">{item.name}</CardTitle>
        <CardDescription className="text-[11px] line-clamp-2 min-h-0 text-muted-foreground">
          {item.description}
        </CardDescription>
        <div className="flex flex-wrap gap-1 text-[9px] text-muted-foreground pt-0.5">
          <Badge variant="secondary" className="font-normal text-[9px] px-1.5 py-0 h-4">
            {item.category}
          </Badge>
          <Badge variant="secondary" className="font-normal text-[9px] px-1.5 py-0 h-4">
            {item.asset}
          </Badge>
        </div>
      </CardHeader>

      <CardContent className="space-y-2 p-3 pt-0">
        {hasMetrics && (
          <div className="grid grid-cols-3 gap-1 rounded-md bg-muted/40 p-1.5 text-center">
            {item.winRate != null && (
              <div>
                <span className="block text-[8px] font-bold uppercase text-muted-foreground">
                  Win
                </span>
                <span className="text-[11px] font-bold text-profit tabular-nums">
                  {item.winRate}%
                </span>
              </div>
            )}
            {item.maxDrawdown != null && (
              <div>
                <span className="block text-[8px] font-bold uppercase text-muted-foreground">
                  Max DD
                </span>
                <span className="text-[11px] font-bold text-loss tabular-nums">
                  -{item.maxDrawdown}%
                </span>
              </div>
            )}
            {item.monthlyReturn != null && (
              <div>
                <span className="block text-[8px] font-bold uppercase text-muted-foreground">
                  Monthly
                </span>
                <span className="text-[11px] font-bold text-info tabular-nums">
                  +{item.monthlyReturn}%
                </span>
              </div>
            )}
            {item.sharpe != null && (
              <div>
                <span className="block text-[8px] font-bold uppercase text-muted-foreground">
                  Sharpe
                </span>
                <span className="text-[11px] font-bold tabular-nums">{item.sharpe}</span>
              </div>
            )}
            {item.profitFactor != null && (
              <div>
                <span className="block text-[8px] font-bold uppercase text-muted-foreground">
                  PF
                </span>
                <span className="text-[11px] font-bold tabular-nums">{item.profitFactor}</span>
              </div>
            )}
            {item.subscribers != null && (
              <div>
                <span className="block text-[8px] font-bold uppercase text-muted-foreground">
                  Subs
                </span>
                <span className="text-[11px] font-bold tabular-nums">
                  {item.subscribers.toLocaleString()}
                </span>
              </div>
            )}
          </div>
        )}

        <div className="flex items-center justify-between gap-1.5 pt-1 flex-wrap">
          <div className="min-w-0">
            {item.price ? (
              <span className="text-xs font-black text-foreground">
                ₹{item.price.toLocaleString()}
                <span className="text-[9px] font-normal text-muted-foreground">/mo</span>
              </span>
            ) : (
              <span className="text-xs font-bold text-profit">Free</span>
            )}
            {item.version && (
              <span className="ml-1.5 text-[9px] text-muted-foreground">{item.version}</span>
            )}
          </div>

          <div className="flex items-center gap-1.5 shrink-0 ml-auto">
            {onSecondary && (
              <Button
                variant="ghost"
                size="sm"
                className="h-7 w-7 p-0"
                onClick={() => onSecondary(item)}
                title="Preview Strategy Details"
              >
                <Eye className="h-3.5 w-3.5" />
              </Button>
            )}

            {/* 2-Day Free Trial Button for Premium Items */}
            {isPremium && !isSubscribed && !isTrial && onStartTrial && (
              <Button
                size="sm"
                variant="outline"
                className="h-7 text-[11px] font-semibold px-2 border-warning/40 text-warning hover:bg-warning/10"
                onClick={() => onStartTrial(item)}
              >
                <Sparkles className="h-3 w-3 mr-1" />
                Try Free (2 Days)
              </Button>
            )}

            <Button
              size="sm"
              variant={isSubscribed ? 'destructive' : isUnwiredTemplate ? 'outline' : 'default'}
              className="h-7 text-[11px] font-semibold px-2.5"
              disabled={isUnwiredTemplate}
              onClick={() => onPrimary(item)}
            >
              {isUnwiredTemplate ? (
                <Clock className="h-3 w-3 mr-1" />
              ) : isTemplate ? (
                <Copy className="h-3 w-3 mr-1" />
              ) : null}
              {primaryLabel}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
