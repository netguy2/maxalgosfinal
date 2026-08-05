import { Search, Sparkles, Star } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchCSRFToken } from '@/api/client'
import { PageHeader } from '@/components/layout/PageHeader'
import { CatalogCard } from '@/components/marketplace/CatalogCard'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  type CatalogItem,
  type CatalogTier,
  categoriesForTier,
  itemsByTier,
} from '@/lib/marketplace-catalog'
import { openCheckout } from '@/lib/razorpay'
import { showToast } from '@/utils/toast'

interface BackendListing {
  id: number
  strategy_id: number
  name: string
  price: number
  rating: number
  reviews_count: number
  win_rate: number
  drawdown: number
  returns: number
  featured: boolean
  creator: string
  description: string
  is_subscribed: boolean
  is_trial?: boolean
}

type Tab = 'templates' | CatalogTier | 'subscriptions'

const TAB_META: { tab: Tab; label: string; tagline: string }[] = [
  {
    tab: 'templates',
    label: 'Free Templates',
    tagline: 'Editable starting points — clone, customize, deploy.',
  },
  {
    tab: 'premium',
    label: 'Premium Strategies',
    tagline:
      'Real, subscribable strategies with 2-Day Free Trials — compiled and deployed on live execution engine.',
  },
  {
    tab: 'subscriptions',
    label: 'My Strategies',
    tagline: '',
  },
]

export default function Marketplace() {
  const navigate = useNavigate()
  const [listings, setListings] = useState<BackendListing[]>([])
  const [subscribed, setSubscribed] = useState<Set<number>>(new Set())
  const [trials, setTrials] = useState<Set<number>>(new Set())
  const [activeTab, setActiveTab] = useState<Tab>('templates')
  const [category, setCategory] = useState('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [wiredOnly] = useState(true)
  const [previewItem, setPreviewItem] = useState<CatalogItem | null>(null)

  const fetchMarketplace = async () => {
    try {
      const res = await fetch('/strategy/api/marketplace')
      if (res.ok) {
        const data = await res.json()
        if (data.status === 'success') {
          setListings(data.listings || [])
          setSubscribed(
            new Set(
              (data.listings || [])
                .filter((l: BackendListing) => l.is_subscribed)
                .map((l: BackendListing) => l.strategy_id)
            )
          )
          setTrials(
            new Set(
              (data.listings || [])
                .filter((l: BackendListing) => l.is_trial)
                .map((l: BackendListing) => l.strategy_id)
            )
          )
        }
      }
    } catch {
      // Backend marketplace unavailable — curated catalog still renders
    }
  }

  useEffect(() => {
    fetchMarketplace()
  }, [fetchMarketplace])

  // Real backend listings become subscribable Premium catalog items.
  const backendPremium: CatalogItem[] = useMemo(
    () =>
      listings.map((l) => ({
        id: `backend-${l.strategy_id}`,
        name: l.name,
        tier: 'premium' as const,
        category: 'Published',
        asset: 'Any' as const,
        difficulty: 'Advanced' as const,
        description: l.description,
        strategyId: l.strategy_id,
        rating: l.rating,
        subscribers: l.reviews_count,
        winRate: l.win_rate,
        maxDrawdown: l.drawdown,
        monthlyReturn: l.returns,
        price: l.price,
        featured: l.featured,
        isTrial: l.is_trial,
      })),
    [listings]
  )

  const tierItems = useMemo((): CatalogItem[] => {
    if (activeTab === 'subscriptions') {
      return backendPremium.filter(
        (i) => i.strategyId != null && (subscribed.has(i.strategyId) || trials.has(i.strategyId))
      )
    }
    if (activeTab === 'templates') {
      return [...itemsByTier('free'), ...itemsByTier('pro')]
    }
    const base = itemsByTier(activeTab)
    if (activeTab !== 'premium') return base

    const backendNames = new Set(backendPremium.map((b) => b.name.toLowerCase()))
    const deduplicatedStatic = base.filter((b) => !backendNames.has(b.name.toLowerCase()))
    return [...backendPremium, ...deduplicatedStatic]
  }, [activeTab, backendPremium, subscribed, trials])

  const categories = useMemo(() => {
    if (activeTab === 'subscriptions') return ['Published']
    if (activeTab === 'templates') {
      const set = new Set<string>()
      categoriesForTier('free').forEach((c) => set.add(c))
      categoriesForTier('pro').forEach((c) => set.add(c))
      return Array.from(set)
    }
    return categoriesForTier(activeTab as CatalogTier)
  }, [activeTab])

  const isTemplateTab = activeTab === 'templates'

  const filtered = useMemo(() => {
    const q = searchQuery.toLowerCase()
    return tierItems.filter((item) => {
      if (category !== 'all' && item.category !== category) return false
      if (q && !item.name.toLowerCase().includes(q) && !item.description.toLowerCase().includes(q))
        return false
      if (isTemplateTab && wiredOnly && item.signalId == null && item.optionsTemplateId == null)
        return false
      return true
    })
  }, [tierItems, category, searchQuery, isTemplateTab, wiredOnly])

  const subscribeWithPayment = async (item: CatalogItem) => {
    const csrfToken = await fetchCSRFToken()

    const orderRes = await fetch(`/payments/marketplace/${item.strategyId}/create-order`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
      body: JSON.stringify({}),
    })
    const orderData = await orderRes.json()
    if (!orderRes.ok) {
      showToast.error(orderData.message || 'Could not start payment', 'strategy')
      return
    }

    let checkoutResult
    try {
      checkoutResult = await openCheckout({
        keyId: orderData.key_id,
        orderId: orderData.order_id,
        amountPaise: orderData.amount,
        currency: orderData.currency,
        name: 'Max Algos',
        description: `Subscribe to ${item.name}`,
      })
    } catch {
      showToast.info('Payment cancelled', 'strategy')
      return
    }

    const verifyRes = await fetch('/payments/marketplace/verify', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
      body: JSON.stringify({
        razorpay_order_id: checkoutResult.razorpay_order_id,
        razorpay_payment_id: checkoutResult.razorpay_payment_id,
        razorpay_signature: checkoutResult.razorpay_signature,
      }),
    })
    const verifyData = await verifyRes.json()
    if (verifyRes.ok && verifyData.status === 'success') {
      showToast.success(verifyData.message || 'Subscribed', 'strategy')
      fetchMarketplace()
      navigate('/deployments')
    } else {
      showToast.error(verifyData.message || 'Payment verification failed', 'strategy')
    }
  }

  const handleStartTrial = async (item: CatalogItem) => {
    if (item.strategyId) {
      try {
        const csrfToken = await fetchCSRFToken()
        const res = await fetch(`/strategy/api/marketplace/${item.strategyId}/trial`, {
          method: 'POST',
          headers: { 'X-CSRFToken': csrfToken },
        })
        const data = await res.json()
        if (res.ok && data.status === 'success') {
          showToast.success(data.message || '2-Day Free Trial activated!', 'strategy')
          fetchMarketplace()
          navigate('/deployments')
        } else {
          showToast.error(data.message || 'Could not start trial', 'strategy')
        }
      } catch {
        showToast.error('Failed to start free trial', 'strategy')
      }
    } else {
      showToast.success(
        `2-Day Free Trial started for ${item.name}! Configure and deploy your rules.`,
        'strategy'
      )
      if (item.optionsTemplateId) {
        navigate(`/visual-builder?template=${encodeURIComponent(item.id)}`)
      } else {
        navigate(`/strategy/configure?template=${encodeURIComponent(item.id)}`)
      }
    }
  }

  const handleSubscribe = async (item: CatalogItem) => {
    if (item.strategyId == null) {
      // For static catalog entry without strategyId, launch configurator directly
      if (item.optionsTemplateId) {
        navigate(`/visual-builder?template=${encodeURIComponent(item.id)}`)
      } else {
        navigate(`/strategy/configure?template=${encodeURIComponent(item.id)}`)
      }
      return
    }
    const isSubbed = subscribed.has(item.strategyId)

    if (!isSubbed && item.price && item.price > 0) {
      try {
        await subscribeWithPayment(item)
      } catch {
        showToast.error('Network error. Please try again.', 'strategy')
      }
      return
    }

    try {
      const res = await fetch(
        `/strategy/api/marketplace/${item.strategyId}/${isSubbed ? 'unsubscribe' : 'subscribe'}`,
        { method: 'POST' }
      )
      const data = await res.json()
      if (data.status === 'success') {
        showToast.success(data.message || 'Done', 'strategy')
        fetchMarketplace()
        if (!isSubbed) navigate('/deployments')
      } else {
        showToast.error(data.message || 'Operation failed', 'strategy')
      }
    } catch {
      showToast.error('Network error. Please try again.', 'strategy')
    }
  }

  const handlePrimary = (item: CatalogItem) => {
    if (item.tier === 'free' || item.tier === 'pro') {
      if (item.optionsTemplateId) {
        navigate(`/visual-builder?template=${encodeURIComponent(item.id)}`)
      } else {
        navigate(`/strategy/configure?template=${encodeURIComponent(item.id)}`)
      }
      return
    }
    handleSubscribe(item)
  }

  const setTab = (tab: string) => {
    setActiveTab(tab as Tab)
    setCategory('all')
  }

  const currentTabMeta = TAB_META.find((t) => t.tab === activeTab) || TAB_META[0]

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)] overflow-hidden px-4 sm:px-6 py-3 space-y-3 max-w-7xl mx-auto">
      {/* Header. This page owns its own height (it is a fixed-height column
          with an internally scrolling grid), so it keeps its own root wrapper
          rather than PageContainer -- but it still needs the standard title,
          which it was missing entirely: every other page announced itself and
          this one opened straight onto a tab strip. mb-0 because the parent
          already supplies the vertical rhythm. */}
      <div className="shrink-0 space-y-3">
        <PageHeader
          title="Marketplace"
          description="Browse strategy templates and premium strategies"
          className="mb-0"
        />
        <Tabs value={activeTab} onValueChange={setTab}>
          <div className="flex items-center justify-between gap-3 border-b border-border pb-2">
            <TabsList className="h-9">
              {TAB_META.map((t) => (
                <TabsTrigger key={t.tab} value={t.tab} className="text-xs font-semibold px-3.5">
                  {t.label}
                </TabsTrigger>
              ))}
            </TabsList>
            <Button
              variant="outline"
              size="sm"
              className="gap-1.5 text-xs font-bold shrink-0"
              onClick={() => navigate('/strategy/wizard')}
            >
              <Sparkles className="h-3.5 w-3.5 text-warning" />
              AI Strategy Wizard
            </Button>
          </div>
        </Tabs>

        <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
          <p className="text-muted-foreground">{currentTabMeta.tagline}</p>
        </div>

        {/* Filter bar */}
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative flex-1 min-w-48 max-w-xs">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground pointer-events-none" />
            <Input
              placeholder="Search marketplace..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-8 h-8 text-xs"
            />
          </div>

          <div className="flex items-center gap-1 overflow-x-auto">
            <button
              type="button"
              onClick={() => setCategory('all')}
              className={`h-7 px-3 text-xs rounded-full font-medium transition-colors whitespace-nowrap ${
                category === 'all'
                  ? 'bg-foreground text-background'
                  : 'text-muted-foreground hover:text-foreground hover:bg-muted'
              }`}
            >
              All
            </button>
            {categories.map((c) => (
              <button
                key={c}
                type="button"
                onClick={() => setCategory(c)}
                className={`h-7 px-3 text-xs rounded-full font-medium transition-colors whitespace-nowrap ${
                  category === c
                    ? 'bg-foreground text-background'
                    : 'text-muted-foreground hover:text-foreground hover:bg-muted'
                }`}
              >
                {c}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Grid */}
      <div className="flex-1 overflow-y-auto min-h-0 pr-1">
        {filtered.length === 0 ? (
          <div className="py-20 text-center text-muted-foreground text-xs space-y-2">
            <p>No items found matching your filters.</p>
            <Button
              variant="link"
              size="sm"
              className="text-xs"
              onClick={() => {
                setSearchQuery('')
                setCategory('all')
              }}
            >
              Clear filters
            </Button>
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 pb-6">
            {filtered.map((item) => (
              <CatalogCard
                key={item.id}
                item={item}
                isSubscribed={item.strategyId != null && subscribed.has(item.strategyId)}
                isTrial={item.strategyId != null ? trials.has(item.strategyId) : item.isTrial}
                onPrimary={handlePrimary}
                onSecondary={(i) => setPreviewItem(i)}
                onStartTrial={handleStartTrial}
              />
            ))}
          </div>
        )}
      </div>

      {/* Strategy Preview Modal */}
      {previewItem && (
        <Dialog open={Boolean(previewItem)} onOpenChange={() => setPreviewItem(null)}>
          <DialogContent size="default">
            <DialogHeader>
              <div className="flex items-center gap-2">
                <Badge variant="outline" className="text-[10px] uppercase font-bold">
                  {previewItem.tier}
                </Badge>
                {previewItem.rating != null && (
                  <span className="flex items-center gap-0.5 text-xs font-bold text-warning">
                    <Star className="h-3.5 w-3.5 fill-current" />
                    {previewItem.rating}
                  </span>
                )}
              </div>
              <DialogTitle className="text-base font-bold mt-1">{previewItem.name}</DialogTitle>
              <DialogDescription className="text-xs text-muted-foreground">
                {previewItem.description}
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-4 py-2">
              <div className="grid grid-cols-3 gap-2 rounded-lg border border-border bg-muted/30 p-3 text-center text-xs">
                <div>
                  <span className="block text-[10px] text-muted-foreground font-semibold uppercase">
                    Win Rate
                  </span>
                  <span className="font-bold text-profit text-sm">
                    {previewItem.winRate ?? '71'}%
                  </span>
                </div>
                <div>
                  <span className="block text-[10px] text-muted-foreground font-semibold uppercase">
                    Max DD
                  </span>
                  <span className="font-bold text-loss text-sm">
                    -{previewItem.maxDrawdown ?? '8.5'}%
                  </span>
                </div>
                <div>
                  <span className="block text-[10px] text-muted-foreground font-semibold uppercase">
                    Monthly
                  </span>
                  <span className="font-bold text-info text-sm">
                    +{previewItem.monthlyReturn ?? '5.4'}%
                  </span>
                </div>
              </div>

              <div className="space-y-1.5 text-xs border-t border-border pt-3">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Asset Class:</span>
                  <span className="font-semibold">{previewItem.asset}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Difficulty:</span>
                  <span className="font-semibold">{previewItem.difficulty}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Execution Engine:</span>
                  <span className="font-semibold text-profit">Condition-Based (Real Orders)</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Free Trial:</span>
                  <span className="font-semibold text-warning">2 Days (Full Access)</span>
                </div>
              </div>
            </div>

            <div className="flex gap-2 pt-2">
              <Button
                variant="outline"
                className="flex-1 text-xs font-bold border-warning/40 text-warning hover:bg-warning/10"
                onClick={() => {
                  const item = previewItem
                  setPreviewItem(null)
                  handleStartTrial(item)
                }}
              >
                <Sparkles className="h-3.5 w-3.5 mr-1.5" />
                Try Free (2-Day Trial)
              </Button>
              <Button
                className="flex-1 text-xs font-bold"
                onClick={() => {
                  const item = previewItem
                  setPreviewItem(null)
                  handlePrimary(item)
                }}
              >
                Subscribe ({previewItem.price ? `₹${previewItem.price}/mo` : 'Free'})
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      )}
    </div>
  )
}
